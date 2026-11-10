"""备份导出与导入。

导出两种形态：
- 明文：keys.value 放明文，无 auth 块（导入时用当前密码加密入库）
- 加密：整包用导出密码派生 KEK 加密，keys 保持字段密文并携带 auth 块
  （覆盖导入会连同登录凭证一起恢复；合并导入需要导出密码来解字段密文）
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, crypto, db
from .channels import require_data_key

router = APIRouter(prefix="/api/backup", tags=["backup"])

FORMAT = "keyfolio-backup"
VERSION = 1
TABLES = ("templates", "balance_records", "models", "keys", "channels")


class ExportIn(BaseModel):
    password: str = ""  # 空 = 明文导出


class ImportIn(BaseModel):
    backup: dict
    mode: str = "merge"  # overwrite | merge
    password: str = ""


@router.post("/export")
def export_backup(payload: ExportIn, request: Request):
    data_key = auth.require_data_key(request)
    if payload.password and len(payload.password) < 8:
        raise HTTPException(400, "备份加密密码至少 8 位")

    with db.get_conn() as conn:
        data = {
            "channels": [dict(r) for r in conn.execute("SELECT * FROM channels ORDER BY id").fetchall()],
            "keys": _export_keys(conn, data_key, encrypt=bool(payload.password)),
            "models": [dict(r) for r in conn.execute("SELECT * FROM models ORDER BY id").fetchall()],
            "balance_records": [dict(r) for r in conn.execute("SELECT * FROM balance_records ORDER BY id").fetchall()],
            "templates": [dict(r) for r in conn.execute("SELECT * FROM templates ORDER BY id").fetchall()],
        }

    if payload.password:
        data["auth"] = auth.export_auth_state()
        # 额外用导出密码包一层 data key：合并导入时用它解字段密文，
        # 不要求用户提供主密码
        data["backup_wrap"] = crypto.wrap_data_key(
            data_key, payload.password, crypto.AAD_BACKUP)
        kdf = crypto.make_kdf_params()
        kek = crypto.derive_kek(payload.password, kdf, crypto.AAD_BACKUP)
        wrapped = crypto.encrypt_payload(kek, json.dumps(data).encode(), crypto.AAD_BACKUP)
        doc = {
            "format": FORMAT,
            "version": VERSION,
            "created_at": db.now(),
            "encrypted": True,
            "kdf": kdf,
            **wrapped,
        }
    else:
        doc = {
            "format": FORMAT,
            "version": VERSION,
            "created_at": db.now(),
            "encrypted": False,
            "data": data,
        }

    return Response(
        content=json.dumps(doc, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="keyfolio-backup.json"'},
    )


def _export_keys(conn, data_key: bytes, encrypt: bool) -> list[dict]:
    out = []
    for row in conn.execute("SELECT * FROM keys ORDER BY id").fetchall():
        item = dict(row)
        if encrypt:
            item["value_encrypted"] = True  # value_enc 原样带走
        else:
            value = crypto.field_decrypt(data_key, item.pop("value_enc"))
            item["value"] = value
            item["value_encrypted"] = False
        out.append(item)
    return out


@router.post("/import")
def import_backup(payload: ImportIn, request: Request):
    data_key = auth.require_data_key(request)
    backup = payload.backup
    if backup.get("format") != FORMAT:
        raise HTTPException(400, "不是 Keyfolio 备份文件")
    if backup.get("version") != VERSION:
        raise HTTPException(400, f"备份版本不支持：{backup.get('version')}")

    if backup.get("encrypted"):
        if not payload.password:
            raise HTTPException(400, "加密备份需要提供导出时设置的密码")
        try:
            kek = crypto.derive_kek(payload.password, backup["kdf"], crypto.AAD_BACKUP)
            blob = crypto.decrypt_payload(
                {"nonce": backup["nonce"], "ct": backup["ct"]}, kek, crypto.AAD_BACKUP)
            data = json.loads(blob)
        except Exception:
            raise HTTPException(400, "解密失败：密码错误或备份文件损坏")
    else:
        data = backup.get("data")

    _validate(data)

    backup_data_key = None
    if payload.password:
        # 优先用 backup_wrap（导出密码包裹），兜底用 auth 块（主密码包裹）
        for wrap, aad in (
            (data.get("backup_wrap"), crypto.AAD_BACKUP),
            ((data.get("auth") or {}).get("auth_wrap_pw"), crypto.AAD_WRAP_PW),
        ):
            if not wrap:
                continue
            try:
                backup_data_key = crypto.unwrap_data_key(wrap, payload.password, aad)
                break
            except Exception:
                continue

    if payload.mode == "overwrite":
        relogin = _import_overwrite(data, data_key, backup_data_key)
        return {"ok": True, "mode": "overwrite", "relogin": relogin}
    if payload.mode == "merge":
        stats = _import_merge(data, data_key, backup_data_key)
        return {"ok": True, "mode": "merge", **stats}
    raise HTTPException(400, "mode 只能是 overwrite 或 merge")


def _validate(data: dict) -> None:
    for table in ("channels", "keys"):
        if not isinstance(data.get(table), list):
            raise HTTPException(400, f"备份缺少 {table} 数据")


def _import_overwrite(data: dict, data_key: bytes, backup_data_key) -> bool:
    relogin = False
    with db.get_conn() as conn:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        for row in data["channels"]:
            sql, params = _insert_sql(conn, "channels", row)
            conn.execute(sql, params)
        for row in data["keys"]:
            value_enc = _prepare_key_value(row, data_key, backup_data_key)
            row = {**row, "value_enc": value_enc}
            sql, params = _insert_sql(conn, "keys", row)
            conn.execute(sql, params)
        for table in ("models", "balance_records", "templates"):
            for row in data.get(table, []):
                sql, params = _insert_sql(conn, table, row)
                conn.execute(sql, params)
    if data.get("auth"):
        # 在连接关闭后再恢复认证块，避免同线程嵌套写连接锁库
        auth.restore_auth_state(data["auth"])
        relogin = True
    if relogin:
        auth.drop_all_sessions()
    return relogin


def _import_merge(data: dict, data_key: bytes, backup_data_key) -> dict:
    stats = {"channels": 0, "keys": 0, "models": 0, "templates": 0}
    with db.get_conn() as conn:
        existing_channels = {
            (r["base_url"].lower(), r["name"]): r["id"]
            for r in conn.execute("SELECT id, name, base_url FROM channels").fetchall()
        }
        for row in data["channels"]:
            match = existing_channels.get((row["base_url"].lower(), row["name"]))
            if match is None:
                sql, params = _insert_sql(conn, "channels", row)
                cur = conn.execute(sql, params)
                channel_id = cur.lastrowid
                stats["channels"] += 1
            else:
                channel_id = match
            for key_row in data["keys"]:
                if key_row.get("channel_id") != row["id"]:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM keys WHERE channel_id=? AND name=?",
                    (channel_id, key_row["name"]),
                ).fetchone()
                if exists:
                    continue
                item = {**key_row, "channel_id": channel_id}
                item["value_enc"] = _prepare_key_value(key_row, data_key, backup_data_key)
                sql, params = _insert_sql(conn, "keys", item)
                conn.execute(sql, params)
                stats["keys"] += 1
            for model_row in data.get("models", []):
                if model_row.get("channel_id") != row["id"]:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM models WHERE channel_id=? AND model_id=?",
                    (channel_id, model_row["model_id"]),
                ).fetchone()
                if exists:
                    continue
                item = {**model_row, "channel_id": channel_id}
                sql, params = _insert_sql(conn, "models", item)
                conn.execute(sql, params)
                stats["models"] += 1
        for tpl in data.get("templates", []):
            exists = conn.execute(
                "SELECT 1 FROM templates WHERE name=?", (tpl["name"],)
            ).fetchone()
            if not exists:
                sql, params = _insert_sql(conn, "templates", tpl)
                conn.execute(sql, params)
                stats["templates"] += 1
    return stats


def _prepare_key_value(row: dict, data_key: bytes, backup_data_key) -> str:
    if row.get("value_encrypted"):
        if backup_data_key is None:
            raise HTTPException(
                400, "备份里的 Key 是密文，需要提供导出时的密码才能合并导入")
        return crypto.field_encrypt(
            data_key, crypto.field_decrypt(backup_data_key, row["value_enc"]))
    return crypto.field_encrypt(data_key, row.get("value", ""))


def _table_cols(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_sql(conn, table: str, row: dict) -> tuple[str, list]:
    cols = [c for c in row.keys() if c in _table_cols(conn, table)]
    sql = (
        f"INSERT INTO {table}({', '.join(cols)}) "
        f"VALUES({', '.join('?' for _ in cols)})"
    )
    return sql, [row[c] for c in cols]

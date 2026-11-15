"""备份导出与导入。

导出两种形态：
- 明文：keys.value 放明文，无 auth 块（导入时用当前密码加密入库）
- 加密：整包用导出密码派生 KEK 加密，keys 保持字段密文并携带 auth 块
  （覆盖导入会连同登录凭证一起恢复；合并导入需要导出密码来解字段密文）
"""
import json
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, crypto, db
from .settings import validate_scheduler

router = APIRouter(prefix="/api/backup", tags=["backup"])

FORMAT = "keyfolio-backup"
VERSION = 1
TABLES = ("templates", "balance_records", "models", "keys", "channels")
SCHEDULER_DEFAULTS = {
    "sched_enabled": False,
    "sched_balance_hours": 12,
    "sched_models_hours": 24,
}


class ExportIn(BaseModel):
    password: str = ""  # 空 = 明文导出


class ImportIn(BaseModel):
    backup: dict
    mode: str = "merge"  # overwrite | merge
    password: str = ""
    restore_settings: bool = False


@router.post("/export")
def export_backup(payload: ExportIn, request: Request):
    data_key = auth.require_data_key(request)
    if payload.password and len(payload.password) < 8:
        raise HTTPException(400, "备份加密密码至少 8 位")

    with db.get_conn() as conn:
        conn.execute("BEGIN")
        data = {
            "channels": [dict(r) for r in conn.execute("SELECT * FROM channels ORDER BY id").fetchall()],
            "keys": _export_keys(conn, data_key, encrypt=bool(payload.password)),
            "models": [dict(r) for r in conn.execute("SELECT * FROM models ORDER BY id").fetchall()],
            "balance_records": [dict(r) for r in conn.execute("SELECT * FROM balance_records ORDER BY id").fetchall()],
            "templates": [dict(r) for r in conn.execute("SELECT * FROM templates ORDER BY id").fetchall()],
            "settings": {
                key: db.get_setting(key, default, conn=conn)
                for key, default in SCHEDULER_DEFAULTS.items()
            },
        }
        if payload.password:
            data["auth"] = auth.export_auth_state(conn=conn)

    if payload.password:
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

    settings_restored = payload.restore_settings and "settings" in data
    if payload.mode == "overwrite":
        relogin = _import_overwrite(data, data_key, backup_data_key, settings_restored)
        return {"ok": True, "mode": "overwrite", "relogin": relogin,
                "settings_restored": settings_restored}
    if payload.mode == "merge":
        stats = _import_merge(data, data_key, backup_data_key, settings_restored)
        return {"ok": True, "mode": "merge", **stats,
                "settings_restored": settings_restored}
    raise HTTPException(400, "mode 只能是 overwrite 或 merge")


def _validate(data: dict) -> None:
    for table in ("channels", "keys"):
        if not isinstance(data.get(table), list):
            raise HTTPException(400, f"备份缺少 {table} 数据")


def _restore_settings(conn, settings) -> None:
    if not isinstance(settings, dict) or any(key not in settings for key in SCHEDULER_DEFAULTS):
        raise HTTPException(400, "备份里的定时任务设置不完整")
    validate_scheduler(settings["sched_enabled"], settings["sched_balance_hours"],
                       settings["sched_models_hours"])
    # 只恢复配置，保留目标实例的 last_* 运行时间。
    for key in SCHEDULER_DEFAULTS:
        db.set_setting(key, settings[key], conn=conn)


def _import_overwrite(data: dict, data_key: bytes, backup_data_key,
                      restore_settings: bool = False) -> bool:
    auth_block = data.get("auth") or {}
    # 加密备份的 Key 密文与备份里的 data key 绑定；覆盖导入恢复 auth 块时
    # 必须原样保留密文，否则重登后 data key 与密文对不上。
    restore_auth = bool(auth_block) and all(
        row.get("value_encrypted") for row in data["keys"]
    )
    with db.get_conn() as conn:
        columns = {table: _table_cols(conn, table) for table in TABLES}
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        for row in data["channels"]:
            sql, params = _insert_sql(columns, "channels", row)
            conn.execute(sql, params)
        for row in data["keys"]:
            if restore_auth:
                value_enc = row.get("value_enc") or ""
                if not value_enc:
                    raise HTTPException(400, "备份里的 Key 缺少密文，无法恢复")
            else:
                value_enc = _prepare_key_value(row, data_key, backup_data_key)
            row = {**row, "value_enc": value_enc}
            sql, params = _insert_sql(columns, "keys", row)
            conn.execute(sql, params)
        for table in ("models", "balance_records", "templates"):
            for row in data.get(table, []):
                sql, params = _insert_sql(columns, table, row)
                conn.execute(sql, params)
        if restore_auth:
            auth.restore_auth_state(auth_block, conn=conn)
        if restore_settings:
            _restore_settings(conn, data["settings"])
    if restore_auth:
        auth.drop_all_sessions()
        return True
    return False


def _import_merge(data: dict, data_key: bytes, backup_data_key,
                  restore_settings: bool = False) -> dict:
    stats = {"channels": 0, "keys": 0, "models": 0, "templates": 0}
    inserted_key_map: dict[int, int] = {}  # 备份里的 key.id → 新 key.id
    keys_by_channel = defaultdict(list)
    models_by_channel = defaultdict(list)
    for row in data["keys"]:
        keys_by_channel[row.get("channel_id")].append(row)
    for row in data.get("models", []):
        models_by_channel[row.get("channel_id")].append(row)
    with db.get_conn() as conn:
        columns = {table: _table_cols(conn, table) for table in TABLES}
        existing_channels = {
            (r["base_url"].lower(), r["name"]): r["id"]
            for r in conn.execute("SELECT id, name, base_url FROM channels").fetchall()
        }
        existing_keys = defaultdict(list)
        for row in conn.execute("SELECT channel_id, name, value_enc FROM keys").fetchall():
            existing_keys[(row["channel_id"], row["name"])].append(row["value_enc"])
        # 只解密本次需要比较的同名 Key，每个已有密文最多解密一次。
        known_key_values = {}
        existing_models = {
            (r["channel_id"], r["model_id"])
            for r in conn.execute("SELECT channel_id, model_id FROM models").fetchall()
        }
        existing_templates = {
            r["name"] for r in conn.execute("SELECT name FROM templates").fetchall()
        }
        for row in data["channels"]:
            channel_match = (row["base_url"].lower(), row["name"])
            match = existing_channels.get(channel_match)
            if match is None:
                item = _without_id(row)
                sql, params = _insert_sql(columns, "channels", item)
                channel_id = conn.execute(sql, params).lastrowid
                existing_channels[channel_match] = channel_id
                stats["channels"] += 1
            else:
                channel_id = match
            for key_row in keys_by_channel.get(row["id"], ()):
                value = _key_value(key_row, backup_data_key)
                key_match = (channel_id, key_row["name"])
                if key_match not in known_key_values:
                    known_key_values[key_match] = {
                        crypto.field_decrypt(data_key, value_enc)
                        for value_enc in existing_keys.get(key_match, ())
                    }
                same_name = known_key_values[key_match]
                if value in same_name:
                    continue
                item = _without_id({**key_row, "channel_id": channel_id})
                item["value_enc"] = crypto.field_encrypt(data_key, value)
                sql, params = _insert_sql(columns, "keys", item)
                new_key_id = conn.execute(sql, params).lastrowid
                same_name.add(value)
                inserted_key_map[key_row["id"]] = new_key_id
                stats["keys"] += 1
            for model_row in models_by_channel.get(row["id"], ()):
                model_match = (channel_id, model_row["model_id"])
                if model_match in existing_models:
                    continue
                item = _without_id({**model_row, "channel_id": channel_id})
                sql, params = _insert_sql(columns, "models", item)
                conn.execute(sql, params)
                existing_models.add(model_match)
                stats["models"] += 1
        # 只给本次新插入的 Key 带回余额历史
        for record in data.get("balance_records", []):
            new_key_id = inserted_key_map.get(record.get("key_id"))
            if new_key_id is None:
                continue
            item = _without_id({**record, "key_id": new_key_id})
            sql, params = _insert_sql(columns, "balance_records", item)
            conn.execute(sql, params)
        for tpl in data.get("templates", []):
            if tpl["name"] not in existing_templates:
                sql, params = _insert_sql(columns, "templates", _without_id(tpl))
                conn.execute(sql, params)
                existing_templates.add(tpl["name"])
                stats["templates"] += 1
        if restore_settings:
            _restore_settings(conn, data["settings"])
    return stats


def _without_id(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "id"}


def _key_value(row: dict, backup_data_key) -> str:
    if row.get("value_encrypted"):
        if backup_data_key is None:
            raise HTTPException(
                400, "备份里的 Key 是密文，需要提供导出时设置的密码才能导入")
        return crypto.field_decrypt(backup_data_key, row["value_enc"])
    return row.get("value", "")


def _prepare_key_value(row: dict, data_key: bytes, backup_data_key) -> str:
    return crypto.field_encrypt(data_key, _key_value(row, backup_data_key))


def _table_cols(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_sql(columns: dict[str, set[str]], table: str, row: dict) -> tuple[str, list]:
    cols = [c for c in row if c in columns[table]]
    sql = (
        f"INSERT INTO {table}({', '.join(cols)}) "
        f"VALUES({', '.join('?' for _ in cols)})"
    )
    return sql, [row[c] for c in cols]

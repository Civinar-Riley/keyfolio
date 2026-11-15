"""路由与定时任务共用的业务逻辑：验证、查余额、拉模型、同步。"""
import sqlite3

from . import crypto, db
from .adapters import registry
from .adapters.base import AdapterError
from .auth import State


def get_channel(channel_id: int) -> sqlite3.Row | None:
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()


def get_key(key_id: int) -> sqlite3.Row | None:
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM keys WHERE id=?", (key_id,)).fetchone()


def key_plaintext(key_row) -> str:
    if State.data_key is None:
        raise PermissionError("需要重新登录")
    return crypto.field_decrypt(State.data_key, key_row["value_enc"])


REQUEST_CHANGED = "渠道或 Key 已变更，本次结果已丢弃，请重试"


def current_request_key(conn, channel_row, key_row):
    """核对出站请求使用的凭证与地址，返回同一 Key 的最新手填信息。"""
    return conn.execute(
        "SELECT k.*, c.enabled AS channel_enabled FROM keys k "
        "JOIN channels c ON c.id=k.channel_id "
        "WHERE k.id=? AND k.channel_id=? AND k.value_enc=? "
        "AND c.id=? AND c.base_url=? AND c.type=?",
        (key_row["id"], key_row["channel_id"], key_row["value_enc"],
         channel_row["id"], channel_row["base_url"], channel_row["type"]),
    ).fetchone()


def _set_key_check(channel_row, key_row, ok: bool, message: str) -> bool:
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if current_request_key(conn, channel_row, key_row) is None:
            return False
        conn.execute(
            "UPDATE keys SET last_check=?, last_check_msg=? WHERE id=?",
            ("ok" if ok else "fail", message[:500], key_row["id"]),
        )
    return True


async def verify_key(channel_row, key_row, mode: str, model: str = "") -> dict:
    key = key_plaintext(key_row)
    try:
        if mode == "chat":
            if not model:
                raise AdapterError("请先选择一个模型用于对话测试")
            message = await registry.chat_test(channel_row["type"], channel_row["base_url"], key, model)
            result = {"ok": True, "message": message}
        else:
            ids = await registry.fetch_models(channel_row["type"], channel_row["base_url"], key)
            message = f"Key 可用，拉到 {len(ids)} 个模型"
            result = {"ok": True, "message": message, "models": ids}
    except AdapterError as exc:
        message = str(exc)
        result = {"ok": False, "error": message}
    if not _set_key_check(channel_row, key_row, result["ok"], message):
        return {"ok": False, "error": REQUEST_CHANGED}
    return result


async def check_balance(channel_row, key_row) -> dict:
    key = key_plaintext(key_row)
    try:
        result = await registry.fetch_balance(channel_row["type"], channel_row["base_url"], key)
    except AdapterError as exc:
        return {"ok": False, "error": str(exc)}

    now = db.now()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = current_request_key(conn, channel_row, key_row)
        if current is None:
            return {"ok": False, "error": REQUEST_CHANGED}
        # 等待接口期间也可能编辑到期日/币种；以写回时的记录为准。
        currency = result.get("currency") or current["currency"] or ""
        expires_at = result.get("expires_at") or current["expires_at"] or ""
        conn.execute(
            "UPDATE keys SET balance=?, currency=?, expires_at=?, balance_updated_at=? WHERE id=?",
            (result["balance"], currency, expires_at, now, key_row["id"]),
        )
        conn.execute(
            "INSERT INTO balance_records(key_id, balance, currency, expires_at, recorded_at) VALUES(?,?,?,?,?)",
            (key_row["id"], result["balance"], currency, expires_at, now),
        )
    return {"ok": True, **result, "currency": currency, "expires_at": expires_at}


def set_balance_manual(key_row, balance: float, currency: str, expires_at: str) -> dict:
    now = db.now()
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE keys SET balance=?, currency=?, expires_at=?, balance_updated_at=? WHERE id=?",
            (balance, currency, expires_at, now, key_row["id"]),
        )
        conn.execute(
            "INSERT INTO balance_records(key_id, balance, currency, expires_at, recorded_at) VALUES(?,?,?,?,?)",
            (key_row["id"], balance, currency, expires_at, now),
        )
    return {"ok": True, "balance": balance, "currency": currency}


async def pull_models_async(channel_row, key_row) -> list[str]:
    key = key_plaintext(key_row)
    return await registry.fetch_models(channel_row["type"], channel_row["base_url"], key)


def diff_models(channel_id: int, remote_ids: list[str]) -> dict:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT model_id, enabled, auto_disabled FROM models WHERE channel_id=?",
            (channel_id,),
        ).fetchall()
    all_local = {r["model_id"] for r in rows}
    enabled_local = {r["model_id"] for r in rows if r["enabled"]}
    auto_disabled = {r["model_id"] for r in rows if r["auto_disabled"] and not r["enabled"]}
    remote = set(remote_ids)
    return {
        "added": sorted(remote - all_local),
        "removed": sorted(enabled_local - remote),
        # 之前因远端消失被自动停用、现在又出现的模型
        "revived": sorted(auto_disabled & remote),
    }


def apply_sync(
    channel_id: int,
    added: list[str],
    removed: list[str],
    removed_action: str = "disable",
    revived: list[str] | None = None,
    *,
    request_rows: tuple | None = None,
) -> dict:
    now = db.now()
    revived = revived or []
    with db.get_conn() as conn:
        if request_rows is not None:
            conn.execute("BEGIN IMMEDIATE")
            current = current_request_key(conn, *request_rows)
            if current is None:
                raise AdapterError(REQUEST_CHANGED)
            if not current["enabled"] or not current["channel_enabled"]:
                raise AdapterError("渠道或 Key 已停用，本次同步已跳过")
        for model_id in added:
            conn.execute(
                "INSERT INTO models(channel_id, model_id, mtype, enabled, auto_disabled, fetched_at) "
                "VALUES(?,?,?,1,0,?) "
                "ON CONFLICT(channel_id, model_id) DO UPDATE SET "
                "enabled=1, auto_disabled=0, fetched_at=excluded.fetched_at",
                (channel_id, model_id, registry.classify_model(model_id), now),
            )
        for model_id in revived:
            # 只复活自动停用的条目，用户手动停用的不会被同步覆盖
            conn.execute(
                "UPDATE models SET enabled=1, auto_disabled=0, fetched_at=? "
                "WHERE channel_id=? AND model_id=? AND auto_disabled=1",
                (now, channel_id, model_id),
            )
        for model_id in removed:
            if removed_action == "delete":
                conn.execute(
                    "DELETE FROM models WHERE channel_id=? AND model_id=?",
                    (channel_id, model_id),
                )
            else:
                conn.execute(
                    "UPDATE models SET enabled=0, auto_disabled=1, fetched_at=? "
                    "WHERE channel_id=? AND model_id=?",
                    (now, channel_id, model_id),
                )
    return {"added": len(added), "removed": len(removed), "revived": len(revived)}


def first_enabled_key(channel_id: int):
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT * FROM keys WHERE channel_id=? AND enabled=1 ORDER BY id LIMIT 1",
            (channel_id,),
        ).fetchone()

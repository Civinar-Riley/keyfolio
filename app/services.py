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


def _set_key_check(key_id: int, ok: bool, message: str) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE keys SET last_check=?, last_check_msg=? WHERE id=?",
            ("ok" if ok else "fail", message[:500], key_id),
        )


async def verify_key(channel_row, key_row, mode: str, model: str = "") -> dict:
    key = key_plaintext(key_row)
    try:
        if mode == "chat":
            if not model:
                raise AdapterError("请先选择一个模型用于对话测试")
            message = await registry.chat_test(channel_row["type"], channel_row["base_url"], key, model)
            _set_key_check(key_row["id"], True, message)
            return {"ok": True, "message": message}
        ids = await registry.fetch_models(channel_row["type"], channel_row["base_url"], key)
        message = f"Key 可用，拉到 {len(ids)} 个模型"
        _set_key_check(key_row["id"], True, message)
        return {"ok": True, "message": message, "models": ids}
    except AdapterError as exc:
        _set_key_check(key_row["id"], False, str(exc))
        return {"ok": False, "error": str(exc)}


async def check_balance(channel_row, key_row) -> dict:
    key = key_plaintext(key_row)
    try:
        result = await registry.fetch_balance(channel_row["type"], channel_row["base_url"], key)
    except AdapterError as exc:
        return {"ok": False, "error": str(exc)}

    now = db.now()
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE keys SET balance=?, currency=?, expires_at=?, balance_updated_at=? WHERE id=?",
            (result["balance"], result.get("currency", ""), result.get("expires_at", ""), now, key_row["id"]),
        )
        conn.execute(
            "INSERT INTO balance_records(key_id, balance, currency, expires_at, recorded_at) VALUES(?,?,?,?,?)",
            (key_row["id"], result["balance"], result.get("currency", ""), result.get("expires_at", ""), now),
        )
    return {"ok": True, **result}


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
            "SELECT model_id FROM models WHERE channel_id=? AND enabled=1", (channel_id,)
        ).fetchall()
    local = {r["model_id"] for r in rows}
    remote = set(remote_ids)
    return {
        "added": sorted(remote - local),
        "removed": sorted(local - remote),
    }


def apply_sync(channel_id: int, added: list[str], removed: list[str], removed_action: str = "disable") -> dict:
    now = db.now()
    with db.get_conn() as conn:
        for model_id in added:
            conn.execute(
                "INSERT INTO models(channel_id, model_id, mtype, enabled, fetched_at) VALUES(?,?,?,1,?) "
                "ON CONFLICT(channel_id, model_id) DO UPDATE SET enabled=1, fetched_at=excluded.fetched_at",
                (channel_id, model_id, registry.classify_model(model_id), now),
            )
        for model_id in removed:
            if removed_action == "delete":
                conn.execute(
                    "DELETE FROM models WHERE channel_id=? AND model_id=?",
                    (channel_id, model_id),
                )
            else:
                conn.execute(
                    "UPDATE models SET enabled=0, fetched_at=? WHERE channel_id=? AND model_id=?",
                    (now, channel_id, model_id),
                )
    return {"added": len(added), "removed": len(removed)}


def first_enabled_key(channel_id: int):
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT * FROM keys WHERE channel_id=? AND enabled=1 ORDER BY id LIMIT 1",
            (channel_id,),
        ).fetchone()

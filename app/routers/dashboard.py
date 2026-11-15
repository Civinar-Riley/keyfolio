"""统一看板：全渠道/Key 聚合 + 余额趋势。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from .. import db
from ..adapters import registry
from .channels import require_data_key

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(_=Depends(require_data_key)):
    with db.get_conn() as conn:
        channels = conn.execute("SELECT * FROM channels ORDER BY id").fetchall()
        keys = conn.execute("SELECT * FROM keys ORDER BY channel_id, id").fetchall()
        model_counts = {
            r["channel_id"]: r["c"]
            for r in conn.execute(
                "SELECT channel_id, COUNT(*) AS c FROM models WHERE enabled=1 GROUP BY channel_id"
            ).fetchall()
        }
    balance_by_currency: dict[str, float] = {}
    balance_sources = {}
    account_counts: dict[tuple[int, str], int] = {}
    keys_total = 0
    keys_active = 0
    latest_update = ""
    for key in keys:
        keys_total += 1
        if key["enabled"]:
            keys_active += 1
        account = key["balance_account"]
        if account:
            account_id = (key["channel_id"], account)
            account_counts[account_id] = account_counts.get(account_id, 0) + 1
        if key["balance"] is not None and key["currency"]:
            source = ("account", key["channel_id"], account, key["currency"]) if account else ("key", key["id"])
            previous = balance_sources.get(source)
            if previous is None or (key["balance_updated_at"], key["id"]) > (previous["balance_updated_at"], previous["id"]):
                balance_sources[source] = key
        if key["balance_updated_at"] > latest_update:
            latest_update = key["balance_updated_at"]
    for key in balance_sources.values():
        balance_by_currency[key["currency"]] = balance_by_currency.get(key["currency"], 0.0) + key["balance"]

    keys_by_channel: dict[int, list] = {}
    for key in keys:
        data = dict(key)
        data.pop("value_enc", None)
        keys_by_channel.setdefault(key["channel_id"], []).append(data)

    return {
        "summary": {
            "keys_total": keys_total,
            "keys_active": keys_active,
            "channels_total": len(channels),
            "balance_by_currency": {k: round(v, 4) for k, v in balance_by_currency.items()},
            "shared_balance_accounts": sum(count > 1 for count in account_counts.values()),
            "latest_update": latest_update,
        },
        "channel_types": registry.CHANNEL_TYPES,
        "channels": [
            {
                **dict(channel),
                "models_count": model_counts.get(channel["id"], 0),
                "keys": keys_by_channel.get(channel["id"], []),
            }
            for channel in channels
        ],
    }


@router.get("/dashboard/trend")
def trend(
    key_id: int,
    days: int = Query(default=30, ge=1, le=365),
    _=Depends(require_data_key),
):
    with db.get_conn() as conn:
        key_row = conn.execute(
            "SELECT id, name, currency, balance FROM keys WHERE id=?", (key_id,)
        ).fetchone()
        if key_row is None:
            return {"ok": False, "error": "Key 不存在"}
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            "SELECT balance, currency, recorded_at FROM balance_records "
            "WHERE key_id=? AND recorded_at>=? ORDER BY recorded_at ASC, id ASC",
            (key_id, cutoff),
        ).fetchall()
    records = [dict(r) for r in rows]
    return {
        "ok": True,
        "key": dict(key_row),
        "records": records,
    }

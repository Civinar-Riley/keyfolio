"""统一看板：全渠道/Key 聚合 + 余额趋势。"""
from fastapi import APIRouter, Depends, Query

from .. import db
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
    keys_total = 0
    keys_active = 0
    latest_update = ""
    for key in keys:
        keys_total += 1
        if key["enabled"]:
            keys_active += 1
        if key["balance"] is not None and key["currency"]:
            balance_by_currency[key["currency"]] = (
                balance_by_currency.get(key["currency"], 0.0) + key["balance"]
            )
        if key["balance_updated_at"] > latest_update:
            latest_update = key["balance_updated_at"]

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
            "latest_update": latest_update,
        },
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
        rows = conn.execute(
            "SELECT balance, currency, recorded_at FROM balance_records "
            "WHERE key_id=? ORDER BY recorded_at ASC, id ASC",
            (key_id,),
        ).fetchall()
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = [dict(r) for r in rows if r["recorded_at"] >= cutoff]
    return {
        "ok": True,
        "key": dict(key_row),
        "records": records,
    }

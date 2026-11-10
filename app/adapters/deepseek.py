"""DeepSeek 官方余额接口：GET {base}/user/balance"""
from .base import AdapterError, get_json, strip_v1


async def fetch_balance(base_url: str, key: str) -> dict:
    data = await get_json(strip_v1(base_url) + "/user/balance", key)
    infos = data.get("balance_infos") or [] if isinstance(data, dict) else []
    if not infos:
        raise AdapterError("响应里没有 balance_infos，接口可能已变更")
    info = infos[0]
    try:
        balance = float(info["total_balance"])
    except (KeyError, ValueError, TypeError):
        raise AdapterError("total_balance 字段无法解析，接口可能已变更")
    return {
        "balance": balance,
        "currency": info.get("currency") or "CNY",
        "expires_at": info.get("clear_date") or "",
        "source": "/user/balance",
    }

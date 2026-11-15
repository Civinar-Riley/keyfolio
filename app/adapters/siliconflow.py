"""SiliconFlow（硅基流动）余额：GET {base}/v1/user/info。

响应无币种字段；国内平台为 CNY，国际平台 siliconflow.com 为 USD。
"""
from urllib.parse import urlsplit

from .base import AdapterError, get_json, strip_v1


async def fetch_balance(base_url: str, key: str) -> dict:
    data = await get_json(strip_v1(base_url) + "/v1/user/info", key)
    inner = data.get("data") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
        raise AdapterError("响应里没有 data 字段，接口可能已变更")
    raw = inner.get("balance")
    if raw is None:
        raise AdapterError("响应里没有 balance 字段，接口可能已变更")
    try:
        balance = float(raw)
    except (ValueError, TypeError):
        raise AdapterError("余额字段无法解析，接口可能已变更")
    host = urlsplit(base_url).hostname or ""
    currency = "USD" if host == "siliconflow.com" or host.endswith(".siliconflow.com") else "CNY"
    return {
        "balance": balance,
        "currency": inner.get("currency") or currency,
        "expires_at": "",
        "source": "/v1/user/info",
    }

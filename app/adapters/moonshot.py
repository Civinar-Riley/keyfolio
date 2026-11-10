"""Moonshot（Kimi）余额：GET {base}/v1/users/me/balance

官方形状：{"code":0,"data":{"available_balance":49.58894,"voucher_balance":46.58893,"cash_balance":3.0},"status":true}
CN 站（moonshot.cn）人民币，国际站（moonshot.ai）美元。
"""
from urllib.parse import urlparse

from .base import AdapterError, get_json, strip_v1


async def fetch_balance(base_url: str, key: str) -> dict:
    data = await get_json(strip_v1(base_url) + "/v1/users/me/balance", key)
    inner = data.get("data") if isinstance(data, dict) else None
    if not isinstance(inner, dict) or inner.get("available_balance") is None:
        raise AdapterError("响应里没有 data.available_balance，接口可能已变更")
    host = urlparse(strip_v1(base_url)).hostname or ""
    currency = "USD" if host.endswith(".ai") else "CNY"
    return {
        "balance": float(inner["available_balance"]),
        "currency": currency,
        "expires_at": "",
        "source": "/v1/users/me/balance",
    }

"""智谱（GLM）余额：GET {base}/api/paas/v4/users/me/balance

响应为 data.available_balance / voucher_balance / cash_balance
（与 Moonshot 形状相同）。CN 站 CNY，api.z.ai 美元。
失败（404/形状变化）由 registry 回退通用探测。
"""
from urllib.parse import urlparse

from .base import AdapterError, get_json, strip_v1

_BALANCE_SUFFIX = "/api/paas/v4"


def _root(base_url: str) -> str:
    base = strip_v1(base_url)
    if base.lower().endswith(_BALANCE_SUFFIX):
        return base[: -len(_BALANCE_SUFFIX)]
    return base


async def fetch_balance(base_url: str, key: str) -> dict:
    data = await get_json(_root(base_url) + _BALANCE_SUFFIX + "/users/me/balance", key)
    inner = data.get("data") if isinstance(data, dict) else None
    if not isinstance(inner, dict) or inner.get("available_balance") is None:
        raise AdapterError("响应里没有 data.available_balance，接口可能已变更")
    host = urlparse(_root(base_url)).hostname or ""
    currency = "USD" if host.endswith("z.ai") else "CNY"
    return {
        "balance": float(inner["available_balance"]),
        "currency": currency,
        "expires_at": "",
        "source": _BALANCE_SUFFIX + "/users/me/balance",
    }

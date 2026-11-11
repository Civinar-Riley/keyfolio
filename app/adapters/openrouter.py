"""OpenRouter 余额：GET {origin}/api/v1/credits，余额 = total_credits - total_usage（USD）。

/credits 需要管理型 Key；普通 Key 收到 403 时回退 GET /api/v1/key
读 data.limit_remaining（限额定额 Key），无限额度 Key 无余额概念。
"""
import httpx

from .base import AdapterError, DEFAULT_TIMEOUT, get_json, make_client, origin


async def fetch_balance(base_url: str, key: str) -> dict:
    base = origin(base_url)
    try:
        data = await get_json(base + "/api/v1/credits", key)
        inner = data.get("data") if isinstance(data, dict) else None
        total = inner.get("total_credits") if isinstance(inner, dict) else None
        used = inner.get("total_usage") if isinstance(inner, dict) else None
        if total is None or used is None:
            raise AdapterError("响应里没有 total_credits/total_usage，接口可能已变更")
        return {
            "balance": round(float(total) - float(used), 4),
            "currency": "USD",
            "expires_at": "",
            "source": "/api/v1/credits",
        }
    except AdapterError as exc:
        if exc.status != 403:
            raise

    # 普通 Key 回退：/api/v1/key
    hdrs = {"Authorization": f"Bearer {key}"}
    try:
        async with make_client(DEFAULT_TIMEOUT) as client:
            resp = await client.get(base + "/api/v1/key", headers=hdrs)
    except httpx.HTTPError:
        raise AdapterError("403：/credits 需要管理型 Key，回退接口也请求失败")
    if resp.status_code >= 400:
        raise AdapterError("403：/credits 需要管理型 Key，普通 Key 也查不到余额")
    inner = resp.json().get("data") or {}
    limit_remaining = inner.get("limit_remaining")
    if limit_remaining is None:
        raise AdapterError("这是无限额度的 Key，没有余额概念，请在看板手动记录")
    return {
        "balance": float(limit_remaining),
        "currency": "USD",
        "expires_at": "",
        "source": "/api/v1/key",
    }

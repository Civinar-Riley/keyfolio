"""通用余额探测：对没有专属适配器的渠道，并发尝试常见余额端点（只读）。"""
import asyncio

import httpx

from .base import (
    AdapterError,
    PROBE_TIMEOUT,
    first_number,
    get_json,
    make_client,
    normalize_base,
    origin,
    strip_v1,
)

# 常见余额/账户信息端点，按命中概率排序
CANDIDATE_PATHS = [
    "/user/balance",
    "/v1/user/balance",
    "/dashboard/billing/credit_grants",
    "/v1/dashboard/billing/credit_grants",
    "/v1/dashboard/billing/subscription",
    "/v1/user/info",
    "/api/v1/user/info",
    "/v1/credits",
    "/api/v1/credits",
    "/v1/users/me/balance",
    "/api/paas/v4/account/overview",
]

NUMERIC_FIELDS = (
    "total_balance", "totalBalance", "available_balance", "availableBalance",
    "balance", "remaining_balance", "total_available_amount", "credits",
    "total_credits", "credit", "grants_available",
)

MAX_CONCURRENCY = 8


async def probe_balance(base_url: str, key: str) -> dict:
    bases = []
    for candidate in (strip_v1(base_url), normalize_base(base_url), origin(base_url)):
        if candidate and candidate not in bases:
            bases.append(candidate)

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    saw_auth_error = False

    async def probe_one(url: str, client: httpx.AsyncClient):
        nonlocal saw_auth_error
        async with semaphore:
            try:
                data = await get_json(url, key, timeout=PROBE_TIMEOUT, client=client)
            except AdapterError as exc:
                if exc.status in (401, 403):
                    saw_auth_error = True
                return None
            balance, currency = first_number(data, NUMERIC_FIELDS)
            if balance is None:
                return None
            return {
                "balance": balance,
                "currency": currency,
                "expires_at": "",
                "source": url,
            }

    # 复用同一个连接池，避免每个探测路径都新建客户端/SSL 上下文
    async with make_client(PROBE_TIMEOUT) as client:
        probes = [
            (base_index * len(CANDIDATE_PATHS) + path_index,
             probe_one(base + path, client))
            for base_index, base in enumerate(bases)
            for path_index, path in enumerate(CANDIDATE_PATHS)
        ]
        results = await asyncio.gather(*(coro for _, coro in probes), return_exceptions=True)

    best_rank = None
    best = None
    for (rank, _), result in zip(probes, results):
        if isinstance(result, dict) and (best_rank is None or rank < best_rank):
            best_rank = rank
            best = result
    if best is not None:
        return best

    if saw_auth_error:
        raise AdapterError("401：Key 无效或无权限（探测到的余额接口均拒绝访问）", status=401)
    raise AdapterError("未识别出余额接口（试过常见路径均无数字字段），请手动填写余额")

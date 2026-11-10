"""通用余额探测：对没有专属适配器的渠道，逐个尝试常见余额端点（只读）。"""
from .base import (
    AdapterError,
    PROBE_TIMEOUT,
    first_number,
    get_json,
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


async def probe_balance(base_url: str, key: str) -> dict:
    bases = []
    for candidate in (strip_v1(base_url), normalize_base(base_url), origin(base_url)):
        if candidate and candidate not in bases:
            bases.append(candidate)

    saw_auth_error = False
    saw_path = ""
    for base in bases:
        for path in CANDIDATE_PATHS:
            url = base + path
            try:
                data = await get_json(url, key, timeout=PROBE_TIMEOUT)
            except AdapterError as exc:
                if exc.status in (401, 403):
                    saw_auth_error = True
                elif exc.status == 404:
                    saw_path = saw_path or path
                continue
            balance, currency = first_number(data, NUMERIC_FIELDS)
            if balance is not None:
                return {
                    "balance": balance,
                    "currency": currency,
                    "expires_at": "",
                    "source": url,
                }
    if saw_auth_error:
        raise AdapterError("401：Key 无效或无权限（探测到的余额接口均拒绝访问）", status=401)
    raise AdapterError("未识别出余额接口（试过常见路径均无数字字段），请手动填写余额")

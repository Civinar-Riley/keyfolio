"""适配器公共层：HTTP 出站请求、错误归一化。"""
import httpx

DEFAULT_TIMEOUT = 15.0
PROBE_TIMEOUT = 8.0


class AdapterError(Exception):
    """对外展示的失败原因。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def normalize_base(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    return base


def strip_v1(base_url: str) -> str:
    base = normalize_base(base_url)
    if base.lower().endswith("/v1"):
        return base[:-3]
    return base


def origin(base_url: str) -> str:
    base = normalize_base(base_url)
    for marker in ("/v1beta", "/v1", "/api"):
        idx = base.lower().rfind(marker)
        # 只切掉作为路径后缀的版本段
        if idx > len("https://") and base.lower().endswith(marker):
            return base[:idx]
    return base


async def get_json(
    url: str,
    key: str | None = None,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
):
    hdrs = {}
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    if headers:
        hdrs.update(headers)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=hdrs)
    except httpx.TimeoutException:
        raise AdapterError("请求超时（15 秒）")
    except httpx.HTTPError as exc:
        raise AdapterError(f"网络错误：{exc.__class__.__name__}")
    return _raise_for_status(resp)


async def post_json(
    url: str,
    payload: dict,
    key: str | None = None,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
):
    hdrs = {"Content-Type": "application/json"}
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    if headers:
        hdrs.update(headers)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(url, json=payload, headers=hdrs)
    except httpx.TimeoutException:
        raise AdapterError("请求超时（15 秒）")
    except httpx.HTTPError as exc:
        raise AdapterError(f"网络错误：{exc.__class__.__name__}")
    return _raise_for_status(resp)


def _raise_for_status(resp: httpx.Response):
    code = resp.status_code
    if code in (401, 403):
        raise AdapterError(f"{code}：Key 无效或无权限", status=code)
    if code == 404:
        raise AdapterError("404：接口不存在，检查 Base URL", status=code)
    if code == 429:
        raise AdapterError("429：请求过于频繁", status=code)
    if code >= 400:
        raise AdapterError(f"{code}：服务端返回错误", status=code)
    try:
        return resp.json()
    except ValueError:
        raise AdapterError("响应不是合法 JSON，Base URL 可能不对")


def first_number(payload, fields: tuple[str, ...]):
    """在任意形状的 JSON 里按字段名找第一个数值（兼容字符串数字）。"""
    stack = [payload]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            for name in fields:
                value = node.get(name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value), str(node.get("currency") or node.get("unit") or "")
                if isinstance(value, str):
                    try:
                        return float(value), str(node.get("currency") or node.get("unit") or "")
                    except ValueError:
                        pass
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None, ""

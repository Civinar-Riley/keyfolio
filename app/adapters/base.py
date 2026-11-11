"""适配器公共层：HTTP 出站请求、URL 归一化、错误归一化。"""
import re
import ssl
from urllib.parse import urlsplit

import httpx

DEFAULT_TIMEOUT = 15.0
PROBE_TIMEOUT = 8.0

_SSL_CONTEXT: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """复用系统证书上下文，避免每次建客户端都重新加载证书库。"""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def make_client(timeout: float = DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, verify=ssl_context()
    )


# 用户经常直接粘贴文档里的完整端点，拼接前先剥掉
_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/completions",
    "/responses",
    "/embeddings",
    "/models",
    "/messages",
)

_VERSION_SUFFIX = re.compile(r"/v\d+[a-z0-9]*$", re.I)


class AdapterError(Exception):
    """对外展示的失败原因。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def normalize_base(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    lower = base.lower()
    for suffix in _ENDPOINT_SUFFIXES:
        if lower.endswith(suffix):
            return base[: -len(suffix)].rstrip("/")
    return base


def strip_v1(base_url: str) -> str:
    base = normalize_base(base_url)
    if base.lower().endswith("/v1"):
        return base[:-3]
    return base


def origin(base_url: str) -> str:
    """只保留 scheme://host[:port]，用于 OpenRouter 这类固定绝对路径的接口。"""
    base = normalize_base(base_url)
    parts = urlsplit(base)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return base


def api_base(base_url: str, version: str = "v1") -> str:
    """模板/客户端用的 API 根地址：已有版本段则原样返回，否则补上版本段。"""
    base = normalize_base(base_url)
    if _VERSION_SUFFIX.search(base):
        return base
    return f"{base}/{version.lstrip('/')}"


async def get_json(
    url: str,
    key: str | None = None,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
):
    hdrs = {}
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    if headers:
        hdrs.update(headers)
    try:
        if client is not None:
            resp = await client.get(url, headers=hdrs)
        else:
            async with make_client(timeout) as own:
                resp = await own.get(url, headers=hdrs)
    except httpx.TimeoutException:
        raise AdapterError(f"请求超时（{timeout:g} 秒）")
    except httpx.HTTPError as exc:
        raise AdapterError(f"网络错误：{exc.__class__.__name__}")
    return _raise_for_status(resp)


async def post_json(
    url: str,
    payload: dict,
    key: str | None = None,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
):
    hdrs = {"Content-Type": "application/json"}
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    if headers:
        hdrs.update(headers)
    try:
        if client is not None:
            resp = await client.post(url, json=payload, headers=hdrs)
        else:
            async with make_client(timeout) as own:
                resp = await own.post(url, json=payload, headers=hdrs)
    except httpx.TimeoutException:
        raise AdapterError(f"请求超时（{timeout:g} 秒）")
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

"""Anthropic Claude：模型列表 /v1/models + 消息接口测试（余额官方不开放，手动填）。"""
from .base import get_json, normalize_base, post_json

HEADERS = {"x-api-key": "{key}", "anthropic-version": "2023-06-01"}


def _headers(key: str) -> dict:
    return {"x-api-key": key, "anthropic-version": "2023-06-01"}


def _api_url(base_url: str, suffix: str) -> str:
    base = normalize_base(base_url)
    if base.lower().endswith("/v1"):
        return base + suffix
    return base + "/v1" + suffix


async def fetch_models(base_url: str, key: str) -> list[str]:
    data = await get_json(_api_url(base_url, "/models"), key, headers=_headers(key))
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    ids = [str(m["id"]) for m in items if isinstance(m, dict) and m.get("id")]
    return sorted(set(ids))


async def chat_test(base_url: str, key: str, model: str) -> str:
    payload = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    await post_json(_api_url(base_url, "/messages"), payload, headers=_headers(key))
    return f"消息请求成功（model={model}）"

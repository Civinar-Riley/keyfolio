"""OpenAI 兼容：模型拉取与对话测试的通用实现，也是大多数渠道类型的默认。

Base URL 允许带或不带 /v1 后缀（用户从控制台复制的地址经常带），
拼接时保证版本段只出现一次。
"""
from .base import AdapterError, get_json, normalize_base, post_json


def _api_url(base_url: str, suffix: str) -> str:
    base = normalize_base(base_url)
    if base.lower().endswith("/v1"):
        return base + suffix
    return base + "/v1" + suffix


async def fetch_models(base_url: str, key: str) -> list[str]:
    data = await get_json(_api_url(base_url, "/models"), key)
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
        elif isinstance(item, str):
            ids.append(item)
    return sorted(set(ids))


async def chat_test(base_url: str, key: str, model: str) -> str:
    url = _api_url(base_url, "/chat/completions")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        await post_json(url, payload, key)
    except AdapterError as exc:
        # 新推理模型不再接受 max_tokens，改用 max_completion_tokens 再试一次
        if exc.status != 400:
            raise
        payload.pop("max_tokens", None)
        payload["max_completion_tokens"] = 1
        await post_json(url, payload, key)
    return f"对话请求成功（model={model}）"

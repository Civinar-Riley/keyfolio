"""OpenAI 兼容：模型拉取与对话测试的通用实现，也是大多数渠道类型的默认。"""
from .base import get_json, normalize_base, post_json


async def fetch_models(base_url: str, key: str) -> list[str]:
    data = await get_json(normalize_base(base_url) + "/v1/models", key)
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
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    await post_json(normalize_base(base_url) + "/v1/chat/completions", payload, key)
    return f"对话请求成功（model={model}）"

"""Google Gemini：模型列表 /v1beta/models + generateContent 测试（余额手动填）。"""
from .base import get_json, normalize_base, post_json


def _headers(key: str) -> dict:
    return {"x-goog-api-key": key}


async def fetch_models(base_url: str, key: str) -> list[str]:
    data = await get_json(
        normalize_base(base_url) + "/v1beta/models", key, headers=_headers(key))
    items = data.get("models") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    ids = []
    for m in items:
        if isinstance(m, dict) and m.get("name"):
            name = str(m["name"])
            ids.append(name.split("models/", 1)[-1])
    return sorted(set(ids))


async def chat_test(base_url: str, key: str, model: str) -> str:
    url = normalize_base(base_url) + f"/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }
    await post_json(url, payload, headers=_headers(key))
    return f"generateContent 请求成功（model={model}）"

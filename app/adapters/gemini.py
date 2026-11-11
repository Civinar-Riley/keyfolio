"""Google Gemini：模型列表 /v1beta/models + generateContent 测试（余额手动填）。"""
from urllib.parse import urlencode

from .base import get_json, normalize_base, post_json


def _headers(key: str) -> dict:
    return {"x-goog-api-key": key}


def _beta_url(base_url: str, suffix: str) -> str:
    base = normalize_base(base_url)
    if base.lower().endswith("/v1beta"):
        return base + suffix
    return base + "/v1beta" + suffix


async def fetch_models(base_url: str, key: str) -> list[str]:
    url = _beta_url(base_url, "/models")
    ids: list[str] = []
    page_token = ""
    for _ in range(20):
        query = {"pageSize": 1000}
        if page_token:
            query["pageToken"] = page_token
        data = await get_json(f"{url}?{urlencode(query)}", key, headers=_headers(key))
        items = data.get("models") if isinstance(data, dict) else data
        if not isinstance(items, list):
            break
        for m in items:
            if isinstance(m, dict) and m.get("name"):
                ids.append(str(m["name"]).split("models/", 1)[-1])
        next_token = data.get("nextPageToken") if isinstance(data, dict) else ""
        if not next_token or next_token == page_token:
            break
        page_token = next_token
    return sorted(set(ids))


async def chat_test(base_url: str, key: str, model: str) -> str:
    url = _beta_url(base_url, f"/models/{model}:generateContent")
    payload = {
        "contents": [{"parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }
    await post_json(url, payload, headers=_headers(key))
    return f"generateContent 请求成功（model={model}）"

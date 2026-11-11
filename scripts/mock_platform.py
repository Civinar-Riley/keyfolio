"""本地假平台：OpenAI 兼容端点 + DeepSeek 形状余额 + 探测端点，供端到端测试。

独立运行：python scripts/mock_platform.py（端口 39001）
被测试脚本导入：e2e_native.py 里以线程方式起 uvicorn。
"""
import threading

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

MODELS = ["mock-chat-pro", "mock-chat-mini", "mock-embed-3", "mock-image-xl", "mock-tts-1"]
ANTHROPIC_MODELS = ["claude-mock-a", "claude-mock-b", "claude-mock-c"]
GEMINI_MODELS = ["gemini-mock-a", "gemini-mock-b", "gemini-mock-c"]

BALANCE = {"balance_infos": [{"total_balance": "42.50", "currency": "CNY"}]}


@app.get("/v1/models")
def models(request: Request, after_id: str = ""):
    # Anthropic 用 x-api-key，且模型列表分页；OpenAI 兼容路径不看这个头
    if request.headers.get("x-api-key"):
        page = ANTHROPIC_MODELS[:2] if not after_id else ANTHROPIC_MODELS[2:]
        return {
            "data": [{"id": m, "type": "model"} for m in page],
            "first_id": page[0] if page else None,
            "last_id": page[-1] if page else None,
            "has_more": not after_id,
        }
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]}


@app.get("/v1beta/models")
def gemini_models(pageToken: str = ""):
    if not pageToken:
        return {
            "models": [{"name": f"models/{m}"} for m in GEMINI_MODELS[:2]],
            "nextPageToken": "page-2",
        }
    return {"models": [{"name": f"models/{GEMINI_MODELS[2]}"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    if str(body.get("model", "")).startswith("reasoning") and "max_tokens" in body:
        return JSONResponse(
            {"error": {"message": "max_tokens is not supported; use max_completion_tokens"}},
            status_code=400,
        )
    return {
        "id": "mock-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
    }


@app.get("/user/balance")
def balance():
    return BALANCE


@app.get("/api/v1/credits")
def openrouter_credits():
    return {"data": {"total_credits": 100.5, "total_usage": 58.0}}


@app.get("/dashboard/billing/credit_grants")
def grants():
    return {"object": "credit_grants", "grants": {"available": 9.99}}


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    return {"id": "mock-msg", "content": [{"type": "text", "text": "pong"}]}


@app.get("/v1/users/me/balance-should-404")
def moonshot_shape():
    return {"data": {"available_balance": "100.00", "currency": "CNY"}}


def serve(host="127.0.0.1", port=39001):
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    serve()
    print("mock platform on http://127.0.0.1:39001")
    threading.Event().wait()

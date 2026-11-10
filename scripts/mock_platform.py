"""本地假平台：OpenAI 兼容端点 + DeepSeek 形状余额 + 探测端点，供端到端测试。

独立运行：python scripts/mock_platform.py（端口 39001）
被测试脚本导入：e2e_native.py 里以线程方式起 uvicorn。
"""
import threading

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

MODELS = ["mock-chat-pro", "mock-chat-mini", "mock-embed-3", "mock-image-xl", "mock-tts-1"]

BALANCE = {"balance_infos": [{"total_balance": "42.50", "currency": "CNY"}]}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    return {
        "id": "mock-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
    }


@app.get("/user/balance")
def balance():
    return BALANCE


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

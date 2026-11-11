"""渠道类型注册表：按类型分发模型拉取/余额查询/对话测试。

余额策略：有专属适配器的类型直接用，失败即最终结果；
没有的（openai/gateway/custom 及官方接口未确认的类型）走通用探测，
Moonshot/智谱/MiniMax 专属尝试失败后再回退探测。
"""
import re

from . import (
    anthropic,
    deepseek,
    gemini,
    generic_probe,
    moonshot,
    openai_compat,
    openrouter,
    siliconflow,
    zhipu,
)
from .base import AdapterError

CHANNEL_TYPES = [
    {"id": "openai", "label": "OpenAI 官方/兼容"},
    {"id": "gateway", "label": "中转站/网关（new-api 等）"},
    {"id": "deepseek", "label": "DeepSeek"},
    {"id": "siliconflow", "label": "SiliconFlow 硅基流动"},
    {"id": "openrouter", "label": "OpenRouter"},
    {"id": "zhipu", "label": "智谱 GLM"},
    {"id": "moonshot", "label": "Moonshot Kimi"},
    {"id": "minimax", "label": "MiniMax（余额手动填）"},
    {"id": "anthropic", "label": "Anthropic Claude（余额手动填）"},
    {"id": "gemini", "label": "Google Gemini（余额手动填）"},
    {"id": "custom", "label": "自定义"},
]

# 新建渠道时的预设：只填默认值，保存前仍可改
PROVIDERS = [
    {
        "name": "OpenAI",
        "type": "openai",
        "base_url": "https://api.openai.com/v1",
        "console_url": "https://platform.openai.com/api-keys",
    },
    {
        "name": "Anthropic Claude",
        "type": "anthropic",
        "base_url": "https://api.anthropic.com",
        "console_url": "https://console.anthropic.com/settings/keys",
    },
    {
        "name": "Google Gemini",
        "type": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "console_url": "https://aistudio.google.com/apikey",
    },
    {
        "name": "DeepSeek",
        "type": "deepseek",
        "base_url": "https://api.deepseek.com",
        "console_url": "https://platform.deepseek.com/api_keys",
    },
    {
        "name": "SiliconFlow 硅基流动",
        "type": "siliconflow",
        "base_url": "https://api.siliconflow.cn/v1",
        "console_url": "https://cloud.siliconflow.cn/account/ak",
    },
    {
        "name": "OpenRouter",
        "type": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "console_url": "https://openrouter.ai/settings/keys",
    },
    {
        "name": "Moonshot Kimi（国内）",
        "type": "moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "console_url": "https://platform.moonshot.cn/console/api-keys",
    },
    {
        "name": "Moonshot Kimi（国际）",
        "type": "moonshot",
        "base_url": "https://api.moonshot.ai/v1",
        "console_url": "https://platform.moonshot.ai/console/api-keys",
    },
    {
        "name": "智谱 GLM",
        "type": "zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "console_url": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    {
        "name": "Z.ai GLM（国际）",
        "type": "zhipu",
        "base_url": "https://api.z.ai/api/paas/v4",
        "console_url": "https://z.ai/manage-apikey/apikey-list",
    },
]

_DEDICATED = {
    "deepseek": deepseek,
    "siliconflow": siliconflow,
    "openrouter": openrouter,
    "moonshot": moonshot,
    "zhipu": zhipu,
}

# 专属适配器失败后允许回退通用探测的类型（401/403 之外——鉴权失败探测也没用）
_PROBE_FALLBACK = {"moonshot", "zhipu"}

# 官方不提供 Key 余额接口、直接提示手动填的类型
_MANUAL_ONLY = {"anthropic", "gemini", "minimax"}


def is_valid_type(channel_type: str) -> bool:
    return any(t["id"] == channel_type for t in CHANNEL_TYPES)


async def fetch_models(channel_type: str, base_url: str, key: str) -> list[str]:
    if channel_type == "anthropic":
        return await anthropic.fetch_models(base_url, key)
    if channel_type == "gemini":
        return await gemini.fetch_models(base_url, key)
    return await openai_compat.fetch_models(base_url, key)


async def fetch_balance(channel_type: str, base_url: str, key: str) -> dict:
    if channel_type in _MANUAL_ONLY:
        raise AdapterError("该平台不开放余额接口，请手动填写余额")
    module = _DEDICATED.get(channel_type)
    if module is None:
        return await generic_probe.probe_balance(base_url, key)
    try:
        return await module.fetch_balance(base_url, key)
    except AdapterError as exc:
        if channel_type in _PROBE_FALLBACK and exc.status not in (401, 403):
            return await generic_probe.probe_balance(base_url, key)
        raise


async def chat_test(channel_type: str, base_url: str, key: str, model: str) -> str:
    if channel_type == "anthropic":
        return await anthropic.chat_test(base_url, key, model)
    if channel_type == "gemini":
        return await gemini.chat_test(base_url, key, model)
    return await openai_compat.chat_test(base_url, key, model)


MODEL_TYPES = ["chat", "vision", "image", "video", "tts", "transcription", "embedding", "rerank", "music"]

_TYPE_HINTS = [
    ("embed", "embedding"),
    ("rerank", "rerank"),
    ("tts", "tts"),
    ("speech", "tts"),
    ("whisper", "transcription"),
    ("transcri", "transcription"),
    ("asr", "transcription"),
    ("dall-e", "image"),
    ("dalle", "image"),
    ("image", "image"),
    ("flux", "image"),
    ("stable-diffusion", "image"),
    ("sdxl", "image"),
    ("midjourney", "image"),
    ("mj_", "image"),
    ("seedream", "image"),
    ("cogview", "image"),
    ("sora", "video"),
    ("kling", "video"),
    ("runway", "video"),
    ("cogvideo", "video"),
    ("veo", "video"),
    ("video", "video"),
    ("music", "music"),
    ("udio", "music"),
    ("suno", "music"),
    ("vision", "vision"),
    ("-vl", "vision"),
]


def classify_model(model_id: str) -> str:
    s = model_id.lower()
    for hint, mtype in _TYPE_HINTS:
        if hint in s:
            return mtype
    return "chat"


def guess_channel_type(base_url: str) -> str:
    host = re.sub(r"^https?://", "", base_url.strip().lower()).split("/")[0]
    rules = [
        ("api.deepseek.com", "deepseek"),
        ("api.siliconflow", "siliconflow"),
        ("openrouter.ai", "openrouter"),
        ("api.moonshot", "moonshot"),
        ("open.bigmodel.cn", "zhipu"),
        ("minimax", "minimax"),
        ("api.anthropic.com", "anthropic"),
        ("generativelanguage.googleapis.com", "gemini"),
        ("api.openai.com", "openai"),
    ]
    for pattern, ctype in rules:
        if pattern in host:
            return ctype
    return "gateway"

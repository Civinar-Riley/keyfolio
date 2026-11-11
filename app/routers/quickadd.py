"""快速抓取：粘贴文本解析、临时验证、一键入库。"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import crypto, db, services
from ..adapters import registry
from ..adapters.base import AdapterError
from .channels import require_data_key

router = APIRouter(prefix="/api/quickadd", tags=["quickadd"])

URL_RE = re.compile(r"https?://[^\s\"'<>)\\]]+", re.I)
KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")
TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{30,}\b")


class TextIn(BaseModel):
    text: str


class VerifyIn(BaseModel):
    base_url: str
    key: str


class SaveIn(BaseModel):
    name: str = ""
    key_name: str = ""
    base_url: str
    key: str


def _looks_like_key(token: str) -> bool:
    if token.lower().startswith("sk-"):
        return True
    has_digit = any(c.isdigit() for c in token)
    has_letter = any(c.isalpha() for c in token)
    return has_digit and has_letter and len(token) >= 30


@router.post("/parse")
def parse(payload: TextIn, _=Depends(require_data_key)):
    urls = list(dict.fromkeys(m.group(0).rstrip(".,;，。；") for m in URL_RE.finditer(payload.text)))
    keys = list(dict.fromkeys(m.group(0) for m in KEY_RE.finditer(payload.text)))
    if not keys:
        keys = list(dict.fromkeys(
            m.group(0) for m in TOKEN_RE.finditer(payload.text) if _looks_like_key(m.group(0))
        ))
    guessed_type = registry.guess_channel_type(urls[0]) if urls else "gateway"
    return {
        "base_url": urls[0] if urls else "",
        "key": keys[0] if keys else "",
        "url_candidates": urls[:5],
        "key_candidates": keys[:5],
        "guessed_type": guessed_type,
    }


@router.post("/verify")
async def verify(payload: VerifyIn, _=Depends(require_data_key)):
    try:
        ids = await registry.fetch_models("openai", payload.base_url, payload.key.strip())
    except AdapterError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "models": ids}


@router.post("/save")
def save(payload: SaveIn, request: Request):
    data_key = require_data_key(request)
    base_url = payload.base_url.strip()
    key_value = payload.key.strip()
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "Base URL 必须以 http:// 或 https:// 开头")
    if not key_value:
        raise HTTPException(400, "Key 不能为空")
    channel_type = registry.guess_channel_type(base_url)
    from urllib.parse import urlparse

    host = urlparse(base_url).hostname or base_url
    name = payload.name.strip() or host
    key_name = payload.key_name.strip() or "Key 1"
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO channels(name, type, base_url, console_url, grp, notes, enabled, created_at) "
            "VALUES(?,?,?,?,?,?,1,?)",
            (name, channel_type, base_url, "", "", f"来自快速添加（{host}）", db.now()),
        )
        channel_id = cur.lastrowid
        conn.execute(
            "INSERT INTO keys(channel_id, name, value_enc, notes, enabled, created_at) VALUES(?,?,?,?,1,?)",
            (channel_id, key_name, crypto.field_encrypt(data_key, key_value), "", db.now()),
        )
    return {"ok": True, "channel_id": channel_id, "type": channel_type}

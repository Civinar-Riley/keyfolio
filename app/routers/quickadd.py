"""快速抓取：粘贴文本解析、临时验证、一键入库。"""
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import crypto, db
from ..adapters import registry
from ..adapters.base import AdapterError
from .channels import clean_base_url, require_data_key

router = APIRouter(prefix="/api/quickadd", tags=["quickadd"])

URL_RE = re.compile(r"https?://[^\s\"'<>)\]，。；、！？：（）【】《》\u4e00-\u9fff]+", re.I)
KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")
TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{30,}\b")


class TextIn(BaseModel):
    text: str


class VerifyIn(BaseModel):
    base_url: str
    key: str
    type: str = ""


class SaveIn(BaseModel):
    name: str = ""
    key_name: str = ""
    base_url: str
    key: str
    type: str = ""


def _looks_like_key(token: str) -> bool:
    if token.lower().startswith("sk-"):
        return True
    has_digit = any(c.isdigit() for c in token)
    has_letter = any(c.isalpha() for c in token)
    return has_digit and has_letter and len(token) >= 30


def _url_score(url: str) -> int:
    low = url.lower()
    score = 0
    if "/v1" in low:
        score += 2
    if "api." in low or "/api/" in low or low.endswith("/api"):
        score += 2
    if any(word in low for word in ("docs", "doc.", "console", "platform", "dashboard", "github")):
        score -= 4
    if low.endswith((".json", ".html", ".md")):
        score -= 3
    return score


def _channel_type(value: str, base_url: str) -> str:
    return value if registry.is_valid_type(value) else registry.guess_channel_type(base_url)


@router.post("/parse")
def parse(payload: TextIn, _=Depends(require_data_key)):
    urls = list(dict.fromkeys(m.group(0).rstrip(".,;，。；") for m in URL_RE.finditer(payload.text)))
    urls.sort(key=lambda url: -_url_score(url))
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
    base_url = clean_base_url(payload.base_url)
    channel_type = _channel_type(payload.type, base_url)
    try:
        ids = await registry.fetch_models(channel_type, base_url, payload.key.strip())
    except AdapterError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "models": ids, "type": channel_type}


@router.post("/save")
def save(payload: SaveIn, request: Request):
    data_key = require_data_key(request)
    base_url = clean_base_url(payload.base_url)
    key_value = payload.key.strip()
    if not key_value:
        raise HTTPException(400, "Key 不能为空")
    channel_type = _channel_type(payload.type, base_url)
    host = urlparse(base_url).hostname or base_url
    name = payload.name.strip() or host

    with db.get_conn() as conn:
        existing = conn.execute(
            "SELECT id, type FROM channels WHERE lower(rtrim(base_url, '/'))=lower(?)",
            (base_url,),
        ).fetchone()
        if existing is not None:
            channel_id = existing["id"]
            channel_type = existing["type"]
            key_count = conn.execute(
                "SELECT COUNT(*) FROM keys WHERE channel_id=?", (channel_id,)
            ).fetchone()[0]
            key_name = payload.key_name.strip() or f"Key {key_count + 1}"
            cur = conn.execute(
                "INSERT INTO keys(channel_id, name, value_enc, notes, enabled, created_at) "
                "VALUES(?,?,?,?,1,?)",
                (channel_id, key_name, crypto.field_encrypt(data_key, key_value), "", db.now()),
            )
            return {
                "ok": True,
                "channel_id": channel_id,
                "key_id": cur.lastrowid,
                "type": channel_type,
                "created": False,
            }

        cur = conn.execute(
            "INSERT INTO channels(name, type, base_url, console_url, grp, notes, enabled, created_at) "
            "VALUES(?,?,?,?,?,?,1,?)",
            (name, channel_type, base_url, "", "", f"来自快速添加（{host}）", db.now()),
        )
        channel_id = cur.lastrowid
        key_name = payload.key_name.strip() or "Key 1"
        cur = conn.execute(
            "INSERT INTO keys(channel_id, name, value_enc, notes, enabled, created_at) VALUES(?,?,?,?,1,?)",
            (channel_id, key_name, crypto.field_encrypt(data_key, key_value), "", db.now()),
        )
    return {
        "ok": True,
        "channel_id": channel_id,
        "key_id": cur.lastrowid,
        "type": channel_type,
        "created": True,
    }

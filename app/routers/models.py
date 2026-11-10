"""模型管理：拉取、diff、同步、手动添加、粘贴解析。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, services
from ..adapters import registry
from ..adapters.base import AdapterError
from .channels import require_data_key

router = APIRouter(prefix="/api", tags=["models"])


class KeyOptIn(BaseModel):
    key_id: int | None = None


class SyncIn(BaseModel):
    added: list[str] = []
    removed: list[str] = []
    removed_action: str = "disable"  # disable | delete


class ModelIn(BaseModel):
    model_id: str
    mtype: str = ""
    notes: str = ""


class BatchIn(BaseModel):
    ids: list[str]


class ParseIn(BaseModel):
    text: str


class ModelPatch(BaseModel):
    mtype: str | None = None
    notes: str | None = None
    enabled: bool | None = None


def _channel(channel_id: int):
    channel = services.get_channel(channel_id)
    if channel is None:
        raise HTTPException(404, "渠道不存在")
    return channel


def _pick_key(channel_id: int, key_id: int | None):
    if key_id:
        row = services.get_key(key_id)
        if row is None:
            raise HTTPException(404, "Key 不存在")
        return row
    row = services.first_enabled_key(channel_id)
    if row is None:
        raise HTTPException(400, "该渠道没有启用的 Key，请先添加")
    return row


@router.get("/channels/{channel_id}/models")
def list_models(channel_id: int, _=Depends(require_data_key)):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM models WHERE channel_id=? ORDER BY model_id", (channel_id,)
        ).fetchall()
    return {"models": [dict(r) for r in rows]}


@router.post("/channels/{channel_id}/models/fetch")
async def fetch_models(channel_id: int, payload: KeyOptIn, _=Depends(require_data_key)):
    channel = _channel(channel_id)
    key_row = _pick_key(channel_id, payload.key_id)
    try:
        ids = await services.pull_models_async(channel, key_row)
    except AdapterError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "models": ids}


@router.post("/channels/{channel_id}/models/diff")
async def diff_models(channel_id: int, payload: KeyOptIn, _=Depends(require_data_key)):
    channel = _channel(channel_id)
    key_row = _pick_key(channel_id, payload.key_id)
    try:
        ids = await services.pull_models_async(channel, key_row)
    except AdapterError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "remote_count": len(ids), **services.diff_models(channel_id, ids)}


@router.post("/channels/{channel_id}/models/sync")
def sync_models(channel_id: int, payload: SyncIn, _=Depends(require_data_key)):
    _channel(channel_id)
    if payload.removed_action not in ("disable", "delete"):
        raise HTTPException(400, "removed_action 只能是 disable 或 delete")
    result = services.apply_sync(channel_id, payload.added, payload.removed, payload.removed_action)
    return {"ok": True, **result}


@router.post("/channels/{channel_id}/models")
def add_model(channel_id: int, payload: ModelIn, _=Depends(require_data_key)):
    _channel(channel_id)
    model_id = payload.model_id.strip()
    if not model_id:
        raise HTTPException(400, "模型 ID 不能为空")
    mtype = payload.mtype or registry.classify_model(model_id)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO models(channel_id, model_id, mtype, notes, enabled, fetched_at) VALUES(?,?,?,?,1,?) "
            "ON CONFLICT(channel_id, model_id) DO UPDATE SET enabled=1, mtype=excluded.mtype, notes=excluded.notes",
            (channel_id, model_id, mtype, payload.notes, db.now()),
        )
    return {"ok": True}


@router.post("/channels/{channel_id}/models/batch")
def add_models_batch(channel_id: int, payload: BatchIn, _=Depends(require_data_key)):
    _channel(channel_id)
    now = db.now()
    added = 0
    with db.get_conn() as conn:
        for model_id in dict.fromkeys(i.strip() for i in payload.ids if i.strip()):
            conn.execute(
                "INSERT INTO models(channel_id, model_id, mtype, enabled, fetched_at) VALUES(?,?,?,1,?) "
                "ON CONFLICT(channel_id, model_id) DO UPDATE SET enabled=1, fetched_at=excluded.fetched_at",
                (channel_id, model_id, registry.classify_model(model_id), now),
            )
            added += 1
    return {"ok": True, "added": added}


@router.post("/channels/{channel_id}/models/parse")
def parse_models_text(channel_id: int, payload: ParseIn, _=Depends(require_data_key)):
    _channel(channel_id)
    return {"ok": True, "ids": parse_model_text(payload.text)}


def parse_model_text(text: str) -> list[str]:
    """支持：字符串数组 / {"data":[{"id":...}]} / {"models":[...]} / OpenAI 返回体 / 每行一个。"""
    import json

    text = text.strip()
    ids: list[str] = []
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    elif isinstance(data, dict):
        items = data.get("data") or data.get("models") or data.get("ids")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    ids.append(item)
                elif isinstance(item, dict):
                    name = item.get("id") or item.get("name") or item.get("model")
                    if name:
                        ids.append(str(name))
    if not ids:
        ids = [line.strip() for line in text.splitlines() if line.strip()]
    return list(dict.fromkeys(ids))


@router.put("/models/{model_id}")
def update_model(model_id: int, payload: ModelPatch, _=Depends(require_data_key)):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        return {"ok": True}
    sets = ", ".join(f"{name}=?" for name in fields)
    with db.get_conn() as conn:
        cur = conn.execute(f"UPDATE models SET {sets} WHERE id=?", (*fields.values(), model_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "模型不存在")
    return {"ok": True}


@router.delete("/models/{model_id}")
def delete_model(model_id: int, _=Depends(require_data_key)):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM models WHERE id=?", (model_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "模型不存在")
    return {"ok": True}

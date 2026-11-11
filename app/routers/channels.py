"""渠道与 Key 的 CRUD、验证、余额查询。"""
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import auth, crypto, db, services
from ..adapters import registry
from ..adapters.base import normalize_base

router = APIRouter(prefix="/api", tags=["channels"])


def mask_key(value: str) -> str:
    if len(value) <= 10:
        return "****"
    return value[:3] + "****" + value[-4:]


def require_data_key(request: Request) -> bytes:
    return auth.require_data_key(request)


def clean_base_url(value: str) -> str:
    base = normalize_base(value)
    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, "Base URL 必须以 http:// 或 https:// 开头")
    if not urlsplit(base).netloc:
        raise HTTPException(400, "Base URL 缺少主机名")
    return base


class ChannelIn(BaseModel):
    name: str
    type: str = "gateway"
    base_url: str
    console_url: str = ""
    grp: str = ""
    notes: str = ""


class ChannelPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    base_url: str | None = None
    console_url: str | None = None
    grp: str | None = None
    notes: str | None = None
    enabled: bool | None = None


class KeyIn(BaseModel):
    name: str
    value: str
    notes: str = ""
    expires_at: str = ""
    enabled: bool = True


class KeyPatch(BaseModel):
    name: str | None = None
    value: str | None = None
    notes: str | None = None
    expires_at: str | None = None
    enabled: bool | None = None


class VerifyIn(BaseModel):
    mode: str = "models"  # models | chat
    model: str = ""


class BalanceManualIn(BaseModel):
    balance: float
    currency: str = ""
    expires_at: str = ""


def _check_type(channel_type: str) -> None:
    if not registry.is_valid_type(channel_type):
        raise HTTPException(400, f"未知渠道类型：{channel_type}")


def channel_dict(row) -> dict:
    return dict(row)


def _key_dict(row) -> dict:
    data = dict(row)
    data.pop("value_enc", None)
    try:
        data["value_masked"] = mask_key(services.key_plaintext(row))
    except Exception:
        # 密文与当前 data key 不匹配（如导入了别的库的备份）时不拖垮整页
        data["value_masked"] = "****"
    return data


@router.get("/channels")
def list_channels(_=Depends(require_data_key)):
    with db.get_conn() as conn:
        channels = conn.execute("SELECT * FROM channels ORDER BY id").fetchall()
        keys = conn.execute("SELECT * FROM keys ORDER BY id").fetchall()
        counts = {
            r["channel_id"]: {"total": r["c"], "enabled": r["e"]}
            for r in conn.execute(
                "SELECT channel_id, COUNT(*) AS c, "
                "SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS e "
                "FROM models GROUP BY channel_id"
            ).fetchall()
        }
    keys_by_channel: dict[int, list] = {}
    for key in keys:
        keys_by_channel.setdefault(key["channel_id"], []).append(_key_dict(key))
    return {
        "channels": [
            {
                **channel_dict(channel),
                "keys": keys_by_channel.get(channel["id"], []),
                "models_count": counts.get(channel["id"], {}).get("total", 0),
                "models_enabled": counts.get(channel["id"], {}).get("enabled", 0),
            }
            for channel in channels
        ],
        "channel_types": registry.CHANNEL_TYPES,
        "providers": registry.PROVIDERS,
        "model_types": registry.MODEL_TYPES,
    }


@router.post("/channels")
def create_channel(payload: ChannelIn, request: Request, _=Depends(require_data_key)):
    _check_type(payload.type)
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "渠道名称不能为空")
    base_url = clean_base_url(payload.base_url)
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO channels(name, type, base_url, console_url, grp, notes, enabled, created_at) "
            "VALUES(?,?,?,?,?,?,1,?)",
            (name, payload.type, base_url,
             payload.console_url.strip(), payload.grp.strip(), payload.notes, db.now()),
        )
        channel_id = cur.lastrowid
    return {"ok": True, "id": channel_id}


@router.put("/channels/{channel_id}")
def update_channel(channel_id: int, payload: ChannelPatch, _=Depends(require_data_key)):
    if services.get_channel(channel_id) is None:
        raise HTTPException(404, "渠道不存在")
    if payload.type is not None:
        _check_type(payload.type)
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "name" in fields:
        fields["name"] = fields["name"].strip()
        if not fields["name"]:
            raise HTTPException(400, "渠道名称不能为空")
    if "base_url" in fields:
        fields["base_url"] = clean_base_url(fields["base_url"])
    if not fields:
        return {"ok": True}
    sets = ", ".join(f"{name}=?" for name in fields)
    with db.get_conn() as conn:
        conn.execute(f"UPDATE channels SET {sets} WHERE id=?", (*fields.values(), channel_id))
    return {"ok": True}


@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: int, _=Depends(require_data_key)):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "渠道不存在")
    return {"ok": True}


@router.post("/channels/{channel_id}/keys")
def create_key(channel_id: int, payload: KeyIn, request: Request):
    data_key = require_data_key(request)
    if services.get_channel(channel_id) is None:
        raise HTTPException(404, "渠道不存在")
    value = payload.value.strip()
    if not value:
        raise HTTPException(400, "Key 值不能为空")
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO keys(channel_id, name, value_enc, notes, expires_at, enabled, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (channel_id, payload.name.strip() or "Key",
             crypto.field_encrypt(data_key, value), payload.notes,
             payload.expires_at.strip(), 1 if payload.enabled else 0, db.now()),
        )
        key_id = cur.lastrowid
    return {"ok": True, "id": key_id}


@router.put("/keys/{key_id}")
def update_key(key_id: int, payload: KeyPatch, request: Request):
    data_key = require_data_key(request)
    if services.get_key(key_id) is None:
        raise HTTPException(404, "Key 不存在")
    with db.get_conn() as conn:
        if payload.value is not None and payload.value.strip():
            conn.execute(
                "UPDATE keys SET value_enc=? WHERE id=?",
                (crypto.field_encrypt(data_key, payload.value.strip()), key_id),
            )
        fields = {
            k: v for k, v in payload.model_dump().items()
            if v is not None and k != "value"
        }
        if "expires_at" in fields:
            fields["expires_at"] = str(fields["expires_at"]).strip()
        if fields:
            sets = ", ".join(f"{name}=?" for name in fields)
            conn.execute(f"UPDATE keys SET {sets} WHERE id=?", (*fields.values(), key_id))
    return {"ok": True}


@router.delete("/keys/{key_id}")
def delete_key(key_id: int, _=Depends(require_data_key)):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM keys WHERE id=?", (key_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Key 不存在")
    return {"ok": True}


@router.post("/keys/{key_id}/reveal")
def reveal_key(key_id: int, _=Depends(require_data_key)):
    row = services.get_key(key_id)
    if row is None:
        raise HTTPException(404, "Key 不存在")
    return {"ok": True, "value": services.key_plaintext(row)}


@router.post("/keys/{key_id}/verify")
async def verify_key(key_id: int, payload: VerifyIn, _=Depends(require_data_key)):
    channel = _channel_of_key(key_id)
    key_row = services.get_key(key_id)
    result = await services.verify_key(channel, key_row, payload.mode, payload.model)
    return result


@router.post("/keys/{key_id}/balance-check")
async def balance_check(key_id: int, _=Depends(require_data_key)):
    channel = _channel_of_key(key_id)
    key_row = services.get_key(key_id)
    result = await services.check_balance(channel, key_row)
    return result


@router.post("/keys/{key_id}/balance-manual")
def balance_manual(key_id: int, payload: BalanceManualIn, _=Depends(require_data_key)):
    key_row = services.get_key(key_id)
    if key_row is None:
        raise HTTPException(404, "Key 不存在")
    return services.set_balance_manual(key_row, payload.balance, payload.currency, payload.expires_at)


@router.get("/keys/{key_id}/balance-history")
def balance_history(key_id: int, _=Depends(require_data_key)):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT balance, currency, expires_at, recorded_at FROM balance_records "
            "WHERE key_id=? ORDER BY recorded_at ASC, id ASC",
            (key_id,),
        ).fetchall()
    return {"records": [dict(r) for r in rows]}


def _channel_of_key(key_id: int):
    key_row = services.get_key(key_id)
    if key_row is None:
        raise HTTPException(404, "Key 不存在")
    channel = services.get_channel(key_row["channel_id"])
    if channel is None:
        raise HTTPException(404, "渠道不存在")
    return channel

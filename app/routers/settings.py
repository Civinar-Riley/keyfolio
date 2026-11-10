"""应用设置：定时任务配置等。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db
from .channels import require_data_key

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SchedulerIn(BaseModel):
    enabled: bool = False
    balance_interval_hours: float = 12
    model_interval_hours: float = 24


@router.get("")
def get_settings(_=Depends(require_data_key)):
    return {
        "scheduler": {
            "enabled": bool(db.get_setting("sched_enabled", False)),
            "balance_interval_hours": float(db.get_setting("sched_balance_hours", 12)),
            "model_interval_hours": float(db.get_setting("sched_models_hours", 24)),
        },
        "totp_enabled": bool(db.get_setting(auth.K_TOTP_ENABLED, False)),
        "has_recovery": db.get_setting(auth.K_RC_HASH) is not None,
        "last_balance_run": db.get_setting("last_balance_run", 0),
        "last_models_run": db.get_setting("last_models_run", 0),
    }


@router.put("/scheduler")
def set_scheduler(payload: SchedulerIn, _=Depends(require_data_key)):
    if payload.balance_interval_hours < 0 or payload.model_interval_hours < 0:
        raise HTTPException(400, "间隔不能为负数")
    db.set_setting("sched_enabled", payload.enabled)
    db.set_setting("sched_balance_hours", payload.balance_interval_hours)
    db.set_setting("sched_models_hours", payload.model_interval_hours)
    return {"ok": True}

"""应用设置：定时任务配置等。"""
import math

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


def validate_scheduler(enabled, balance_hours, models_hours) -> None:
    if not isinstance(enabled, bool):
        raise HTTPException(400, "定时任务开关必须是布尔值")
    for hours in (balance_hours, models_hours):
        if isinstance(hours, bool) or not isinstance(hours, (int, float)):
            raise HTTPException(400, "间隔必须是有限的非负数")
        try:
            finite = math.isfinite(hours)
        except OverflowError:
            finite = False
        if not finite or hours < 0:
            raise HTTPException(400, "间隔必须是有限的非负数")


@router.put("/scheduler")
def set_scheduler(payload: SchedulerIn, _=Depends(require_data_key)):
    validate_scheduler(payload.enabled, payload.balance_interval_hours, payload.model_interval_hours)
    db.set_setting("sched_enabled", payload.enabled)
    db.set_setting("sched_balance_hours", payload.balance_interval_hours)
    db.set_setting("sched_models_hours", payload.model_interval_hours)
    return {"ok": True}

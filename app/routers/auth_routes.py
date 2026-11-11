"""认证路由：初始化/登录/登出/锁屏解锁/改密码/恢复码/TOTP。"""
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from .. import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupIn(BaseModel):
    password: str


class LoginIn(BaseModel):
    password: str
    totp_code: str = ""


class PasswordIn(BaseModel):
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


class RecoveryResetIn(BaseModel):
    recovery_code: str
    new_password: str


class TotpEnableIn(BaseModel):
    code: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE, token, httponly=True, samesite="lax", path="/"
    )


@router.get("/status")
def status(request: Request):
    return auth.status(request)


@router.post("/lock")
def lock(request: Request):
    auth.lock_session(auth.require_session(request))
    return {"ok": True}


@router.post("/setup")
def setup(payload: SetupIn, response: Response):
    result = auth.setup(payload.password)
    _set_session_cookie(response, auth.create_session())
    return {"ok": True, **result}


@router.post("/login")
def login(payload: LoginIn, response: Response):
    token = auth.login(payload.password, payload.totp_code)
    _set_session_cookie(response, token)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, token: str = Depends(auth.require_session)):
    auth.logout(token)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/unlock")
def unlock(payload: PasswordIn, request: Request):
    auth.unlock(request, payload.password)
    return {"ok": True}


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, request: Request):
    auth.change_password(auth.require_session(request), payload.old_password, payload.new_password)
    return {"ok": True}


@router.post("/recovery-reset")
def recovery_reset(payload: RecoveryResetIn, response: Response):
    new_code = auth.recovery_reset(payload.recovery_code, payload.new_password)
    # reset 会清空会话与内存密钥；用新密码重新登录，给出可用会话
    token = auth.login(payload.new_password)
    _set_session_cookie(response, token)
    return {"ok": True, "recovery_code": new_code}


@router.post("/totp/setup")
def totp_setup(request: Request):
    return auth.totp_setup(auth.require_session(request))


@router.post("/totp/enable")
def totp_enable(payload: TotpEnableIn, request: Request):
    return auth.totp_enable(auth.require_session(request), payload.code)


@router.post("/totp/disable")
def totp_disable(payload: PasswordIn, request: Request):
    auth.totp_disable(auth.require_session(request), payload.password)
    return {"ok": True}


@router.post("/totp/backup-codes")
def backup_codes(payload: PasswordIn, request: Request):
    codes = auth.backup_codes_regenerate(auth.require_session(request), payload.password)
    return {"ok": True, "backup_codes": codes}

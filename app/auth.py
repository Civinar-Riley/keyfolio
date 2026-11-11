"""单用户认证：主密码、恢复码、TOTP/备用码、会话与锁定。

会话与 data key 存在内存里；锁定状态持久化到 settings，重启不清零。
"""
import io
import secrets
import time
from typing import Any

import pyotp
import qrcode
import qrcode.image.svg
from fastapi import HTTPException, Request

from . import crypto, db

SESSION_COOKIE = "kf_session"
LOCK_THRESHOLD = 5
LOCK_SECONDS = 300
SESSION_TTL = 7 * 24 * 3600  # 闲置 7 天后会话失效

K_PW_HASH = "auth_pw_hash"
K_PW_KDF = "auth_pw_kdf"
K_WRAP_PW = "auth_wrap_pw"
K_WRAP_RC = "auth_wrap_rc"
K_RC_HASH = "auth_rc_hash"
K_TOTP_SECRET = "totp_secret"
K_TOTP_ENABLED = "totp_enabled"
K_TOTP_PENDING = "totp_pending"
K_BACKUP_CODES = "totp_backup_codes"
K_FAIL_COUNT = "fail_count"
K_LOCK_UNTIL = "lock_until"


class State:
    data_key: bytes | None = None
    sessions: dict[str, float] = {}
    locked: set[str] = set()  # 已锁屏的会话；data key 仍驻留内存


def _http(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def is_configured() -> bool:
    return db.get_setting(K_PW_HASH) is not None


def lock_until() -> int:
    return int(db.get_setting(K_LOCK_UNTIL, 0) or 0)


def is_locked() -> bool:
    return time.time() < lock_until()


def _locked_error() -> HTTPException:
    until = time.strftime("%H:%M:%S", time.localtime(lock_until()))
    return _http(423, f"失败次数过多，已锁定到 {until}")


def _prune_sessions() -> None:
    cutoff = time.time() - SESSION_TTL
    expired = [token for token, seen in State.sessions.items() if seen < cutoff]
    for token in expired:
        State.sessions.pop(token, None)
        State.locked.discard(token)
    if not State.sessions:
        State.data_key = None


def status(request: Request | None = None) -> dict[str, Any]:
    _prune_sessions()
    token = _token_of(request) if request is not None else None
    return {
        "configured": is_configured(),
        "locked": is_locked(),
        "lock_until": lock_until(),
        "totp_enabled": bool(db.get_setting(K_TOTP_ENABLED, False)),
        "authenticated": bool(token and token in State.sessions),
        "screen_locked": bool(token and token in State.locked),
    }


def _verify_password(password: str) -> bool:
    kdf = db.get_setting(K_PW_KDF)
    pw_hash = db.get_setting(K_PW_HASH)
    if not kdf or not pw_hash:
        return False
    return crypto.password_matches(password, kdf, pw_hash)


def _register_fail() -> None:
    count = int(db.get_setting(K_FAIL_COUNT, 0) or 0) + 1
    db.set_setting(K_FAIL_COUNT, count)
    if count >= LOCK_THRESHOLD:
        db.set_setting(K_LOCK_UNTIL, int(time.time()) + LOCK_SECONDS)
        db.set_setting(K_FAIL_COUNT, 0)


def _clear_fail() -> None:
    db.set_setting(K_FAIL_COUNT, 0)
    db.set_setting(K_LOCK_UNTIL, 0)


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    State.sessions[token] = time.time()
    _prune_sessions()
    return token


def _token_of(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def _drop_session(token: str | None) -> None:
    if token:
        State.sessions.pop(token, None)
        State.locked.discard(token)


def drop_all_sessions() -> None:
    State.sessions.clear()
    State.locked.clear()
    State.data_key = None


def require_session(request: Request) -> str:
    _prune_sessions()
    token = _token_of(request)
    if token is None or token not in State.sessions:
        raise _http(401, "未登录或会话已失效")
    State.sessions[token] = time.time()
    return token


def _require_token(token: str) -> str:
    """内部函数持有的 token 形态校验。"""
    _prune_sessions()
    if not token or token not in State.sessions:
        raise _http(401, "未登录或会话已失效")
    return token


def _require_unlocked(token: str) -> str:
    _require_token(token)
    if token in State.locked:
        raise _http(423, "已锁定，请先解锁")
    return token


def require_data_key(request: Request) -> bytes:
    token = require_session(request)
    if token in State.locked:
        raise _http(423, "已锁定，请先解锁")
    if State.data_key is None:
        raise _http(401, "需要重新登录")
    return State.data_key


def lock_session(token: str) -> None:
    _require_token(token)
    State.locked.add(token)


def setup(password: str) -> dict[str, str]:
    if is_configured():
        raise _http(409, "已初始化，不能重复设置")
    if len(password) < 8:
        raise _http(400, "主密码至少 8 位")

    from .seed import seed_templates

    kdf = crypto.make_kdf_params()
    data_key = secrets.token_bytes(32)
    recovery_code = crypto.generate_recovery_code()
    normalized = crypto.normalize_recovery(recovery_code)

    db.set_setting(K_PW_KDF, kdf)
    db.set_setting(K_PW_HASH, crypto.hash_password(password, kdf))
    db.set_setting(K_WRAP_PW, crypto.wrap_data_key(data_key, password, crypto.AAD_WRAP_PW))
    db.set_setting(K_WRAP_RC, crypto.wrap_data_key(data_key, normalized, crypto.AAD_WRAP_RC))
    db.set_setting(K_RC_HASH, crypto.hash_code(normalized))
    _clear_fail()

    State.data_key = data_key
    seed_templates()
    return {"recovery_code": recovery_code}


def login(password: str, totp_code: str = "") -> str:
    if is_locked():
        raise _http(423, f"失败次数过多，锁定到 {time.strftime('%H:%M:%S', time.localtime(lock_until()))}")
    if not _verify_password(password):
        _register_fail()
        if is_locked():
            raise _locked_error()
        left = LOCK_THRESHOLD - int(db.get_setting(K_FAIL_COUNT, 0) or 0)
        raise _http(401, f"主密码错误，再错 {max(left, 1)} 次将锁定")
    try:
        data_key = crypto.unwrap_data_key(
            db.get_setting(K_WRAP_PW), password, crypto.AAD_WRAP_PW)
    except Exception:
        _register_fail()
        if is_locked():
            raise _locked_error()
        raise _http(401, "主密码错误")

    if db.get_setting(K_TOTP_ENABLED):
        if not _check_second_factor(data_key, totp_code or ""):
            _register_fail()
            if is_locked():
                raise _locked_error()
            raise _http(401, "两步验证码错误")

    _clear_fail()
    State.data_key = data_key
    return create_session()


def _check_second_factor(data_key: bytes, code: str) -> bool:
    code = (code or "").strip().lower()
    secret_blob = db.get_setting(K_TOTP_SECRET)
    if secret_blob:
        try:
            secret = crypto.field_decrypt(data_key, secret_blob)
            if pyotp.TOTP(secret).verify(code, valid_window=1):
                return True
        except Exception:
            pass  # 密钥解不开时仍允许用备用码
    hashes = db.get_setting(K_BACKUP_CODES, [])
    for h in hashes:
        if crypto.code_matches(code, h):
            db.set_setting(K_BACKUP_CODES, [x for x in hashes if x != h])
            return True
    return False


def unlock(request: Request, password: str) -> None:
    token = require_session(request)
    if is_locked():
        raise _locked_error()
    if not _verify_password(password):
        _register_fail()
        if is_locked():
            raise _locked_error()
        raise _http(401, "主密码错误")
    _clear_fail()
    State.locked.discard(token)


def logout(token: str) -> None:
    _drop_session(token)
    if not State.sessions:
        State.data_key = None


def change_password(token: str, old: str, new: str) -> None:
    _require_unlocked(token)
    if not _verify_password(old):
        raise _http(401, "原密码错误")
    if len(new) < 8:
        raise _http(400, "新密码至少 8 位")
    if State.data_key is None:
        raise _http(401, "需要重新登录")
    db.set_setting(K_WRAP_PW, crypto.wrap_data_key(State.data_key, new, crypto.AAD_WRAP_PW))
    kdf = crypto.make_kdf_params()
    db.set_setting(K_PW_KDF, kdf)
    db.set_setting(K_PW_HASH, crypto.hash_password(new, kdf))
    # 改密码后其他设备的会话一并失效，只保留当前会话
    for other in list(State.sessions):
        if other != token:
            _drop_session(other)


def recovery_reset(recovery_code: str, new_password: str) -> str:
    """凭恢复码重设密码：解出 data key 重新包裹，并生成新的恢复码。"""
    if len(new_password) < 8:
        raise _http(400, "新密码至少 8 位")
    rc_hash = db.get_setting(K_RC_HASH)
    wrap_rc = db.get_setting(K_WRAP_RC)
    if not rc_hash or not wrap_rc:
        raise _http(400, "未设置恢复码")
    normalized = crypto.normalize_recovery(recovery_code)
    if not crypto.code_matches(normalized, rc_hash):
        raise _http(401, "恢复码错误")
    try:
        data_key = crypto.unwrap_data_key(wrap_rc, normalized, crypto.AAD_WRAP_RC)
    except Exception:
        raise _http(401, "恢复码错误")

    new_code = crypto.generate_recovery_code()
    new_normalized = crypto.normalize_recovery(new_code)
    db.set_setting(K_WRAP_PW, crypto.wrap_data_key(data_key, new_password, crypto.AAD_WRAP_PW))
    db.set_setting(K_WRAP_RC, crypto.wrap_data_key(data_key, new_normalized, crypto.AAD_WRAP_RC))
    db.set_setting(K_RC_HASH, crypto.hash_code(new_normalized))
    kdf = crypto.make_kdf_params()
    db.set_setting(K_PW_KDF, kdf)
    db.set_setting(K_PW_HASH, crypto.hash_password(new_password, kdf))
    # 恢复码是最后逃生通道：重置后清掉 TOTP，避免验证器丢了也进不来
    db.delete_setting(K_TOTP_SECRET)
    db.delete_setting(K_TOTP_ENABLED)
    db.delete_setting(K_BACKUP_CODES)
    db.delete_setting(K_TOTP_PENDING)
    _clear_fail()
    drop_all_sessions()
    return new_code


def totp_setup(token: str) -> dict[str, str]:
    _require_unlocked(token)
    if db.get_setting(K_TOTP_ENABLED):
        raise _http(409, "TOTP 已开启")
    secret = pyotp.random_base32()
    db.set_setting(K_TOTP_PENDING, secret)
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name="keyfolio@local", issuer_name="Keyfolio")
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": qr_svg(uri)}


def qr_svg(text: str) -> str:
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def totp_enable(token: str, code: str) -> dict[str, list[str]]:
    _require_unlocked(token)
    if State.data_key is None:
        raise _http(401, "需要重新登录")
    pending = db.get_setting(K_TOTP_PENDING)
    if not pending:
        raise _http(400, "请先获取二维码")
    if not pyotp.TOTP(pending).verify(code.strip(), valid_window=1):
        raise _http(401, "验证码错误，请重试")
    db.set_setting(K_TOTP_SECRET, crypto.field_encrypt(State.data_key, pending))
    db.set_setting(K_TOTP_ENABLED, True)
    db.delete_setting(K_TOTP_PENDING)
    codes = _gen_backup_codes()
    return {"backup_codes": codes}


def totp_disable(token: str, password: str) -> None:
    _require_unlocked(token)
    if not _verify_password(password):
        raise _http(401, "主密码错误")
    db.delete_setting(K_TOTP_SECRET)
    db.delete_setting(K_TOTP_ENABLED)
    db.delete_setting(K_BACKUP_CODES)


def backup_codes_regenerate(token: str, password: str) -> list[str]:
    _require_unlocked(token)
    if not _verify_password(password):
        raise _http(401, "主密码错误")
    return _gen_backup_codes()


def _gen_backup_codes() -> list[str]:
    codes = [crypto.generate_backup_code() for _ in range(10)]
    db.set_setting(K_BACKUP_CODES, [crypto.hash_code(c) for c in codes])
    return codes


def export_auth_state() -> dict[str, Any]:
    """备份用：认证相关 settings 原样带走（敏感字段仍是密文）。"""
    out = {}
    for key in (K_PW_HASH, K_PW_KDF, K_WRAP_PW, K_WRAP_RC, K_RC_HASH,
                K_TOTP_SECRET, K_TOTP_ENABLED, K_BACKUP_CODES):
        value = db.get_setting(key)
        if value is not None:
            out[key] = value
    return out


AUTH_KEYS = (
    K_PW_HASH, K_PW_KDF, K_WRAP_PW, K_WRAP_RC, K_RC_HASH,
    K_TOTP_SECRET, K_TOTP_ENABLED, K_TOTP_PENDING, K_BACKUP_CODES,
)


def restore_auth_state(block: dict[str, Any]) -> None:
    """整块替换认证状态：先清干净，避免备份没有的开关（如 TOTP）残留当前值。"""
    for key in AUTH_KEYS:
        db.delete_setting(key)
    for key, value in block.items():
        if key in AUTH_KEYS:
            db.set_setting(key, value)

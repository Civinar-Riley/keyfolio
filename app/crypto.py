"""加密原语：scrypt KDF、AES-GCM 字段加密、data key 双层包裹、恢复码/备用码。

模型：随机 32 字节 data key 加密所有敏感字段；data key 本身被
主密码派生的 KEK 和恢复码派生的 KEK 分别包裹（wrap）存储，
因此改密码/恢复密码只是重新包裹，不需要重加密任何数据。
"""
import base64
import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 128 * 1024 * 1024

AAD_FIELD = b"keyfolio-field-v1"
AAD_WRAP_PW = b"keyfolio-wrap-pw-v1"
AAD_WRAP_RC = b"keyfolio-wrap-rc-v1"
AAD_BACKUP = b"keyfolio-backup-v1"


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def b64d(text: str) -> bytes:
    return base64.b64decode(text)


def derive_kek(password: str, kdf: dict, aad: bytes) -> bytes:
    """从密码/恢复码派生 KEK。aad 仅用于区分用途，不参与 KDF 本身。"""
    salt = b64d(kdf["salt"])
    raw = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=kdf.get("n", SCRYPT_N),
        r=kdf.get("r", SCRYPT_R),
        p=kdf.get("p", SCRYPT_P),
        dklen=32,
        maxmem=SCRYPT_MAXMEM,
    )
    # 把用途绑进 KEK，避免同一派生被挪用到别的包裹上
    return hashlib.sha256(raw + aad).digest()


def make_kdf_params() -> dict:
    return {"salt": b64e(secrets.token_bytes(16)), "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P}


def hash_password(password: str, kdf: dict) -> str:
    return b64e(hashlib.scrypt(
        password.encode(), salt=b64d(kdf["salt"]),
        n=kdf["n"], r=kdf["r"], p=kdf["p"], dklen=32, maxmem=SCRYPT_MAXMEM,
    ))


def password_matches(password: str, kdf: dict, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password, kdf), expected_hash)


def wrap_data_key(data_key: bytes, secret: str, aad: bytes) -> dict:
    """用密码或恢复码派生的 KEK 包裹 data key。"""
    kdf = make_kdf_params()
    kek = derive_kek(secret, kdf, aad)
    nonce = secrets.token_bytes(12)
    ct = AESGCM(kek).encrypt(nonce, data_key, aad)
    return {"kdf": kdf, "nonce": b64e(nonce), "ct": b64e(ct)}


def unwrap_data_key(wrap: dict, secret: str, aad: bytes) -> bytes:
    kek = derive_kek(secret, wrap["kdf"], aad)
    return AESGCM(kek).decrypt(b64d(wrap["nonce"]), b64d(wrap["ct"]), aad)


def field_encrypt(data_key: bytes, plaintext: str) -> str:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(data_key).encrypt(nonce, plaintext.encode(), AAD_FIELD)
    return b64e(nonce + ct)


def field_decrypt(data_key: bytes, blob: str) -> str:
    raw = b64d(blob)
    return AESGCM(data_key).decrypt(raw[:12], raw[12:], AAD_FIELD).decode()


def encrypt_payload(data_key: bytes, payload: bytes, aad: bytes = AAD_BACKUP) -> dict:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(data_key).encrypt(nonce, payload, aad)
    return {"nonce": b64e(nonce), "ct": b64e(ct)}


def decrypt_payload(wrapped: dict, data_key: bytes, aad: bytes = AAD_BACKUP) -> bytes:
    return AESGCM(data_key).decrypt(b64d(wrapped["nonce"]), b64d(wrapped["ct"]), aad)


def generate_recovery_code() -> str:
    raw = secrets.token_hex(8)  # 16 个十六进制字符，64 bit
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def generate_backup_code() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def normalize_recovery(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def hash_code(normalized: str) -> str:
    return hashlib.sha256(normalized.encode()).hexdigest()


def code_matches(code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_code(normalize_recovery(code)), expected_hash)

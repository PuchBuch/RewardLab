"""Одноразовые коды для входа в админку (RFC 6238, совместимо с Google Authenticator)."""

import re
import hmac
import time
import base64
import struct
import hashlib
import secrets


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def provisioning_uri(secret: str, username: str) -> str:
    return f"otpauth://totp/RewardLab:{username}?secret={secret}&issuer=RewardLab"


def code_at(secret: str, step: int) -> str:
    h = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def check(secret: str, code: str, last_step: int) -> int | None:
    """Проверка кода с окном ±30 с. Возвращает шаг или None.
    Уже использованный код повторно не принимается."""
    if not re.fullmatch(r"\d{6}", code or ""):
        return None
    now = int(time.time()) // 30
    for step in (now - 1, now, now + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None

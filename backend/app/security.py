import hashlib
import hmac
import json
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone

from app.config import settings


def random_numeric_code(length: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def random_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_with_secret(value: str) -> str:
    digest = hmac.new(settings.session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return digest


def _urlsafe_encode(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode().rstrip("=")


def _urlsafe_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return urlsafe_b64decode(raw + padding)


def sign_ebill_token(order_id: str, ttl_hours: int | None = None) -> str:
    effective_ttl = ttl_hours or settings.ebill_token_ttl_hours
    exp = int((datetime.now(timezone.utc) + timedelta(hours=effective_ttl)).timestamp())
    payload = {"order_id": order_id, "exp": exp}
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    payload_part = _urlsafe_encode(payload_raw)
    secret = (settings.ebill_link_secret or settings.session_secret).encode()
    signature = hmac.new(secret, payload_part.encode(), hashlib.sha256).digest()
    sig_part = _urlsafe_encode(signature)
    return f"{payload_part}.{sig_part}"


def verify_ebill_token(token: str) -> dict | None:
    if "." not in token:
        return None
    payload_part, sig_part = token.split(".", 1)
    secret = (settings.ebill_link_secret or settings.session_secret).encode()
    expected_sig = _urlsafe_encode(hmac.new(secret, payload_part.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected_sig, sig_part):
        return None
    try:
        payload = json.loads(_urlsafe_decode(payload_part).decode())
    except (ValueError, json.JSONDecodeError):
        return None
    exp = int(payload.get("exp", 0))
    if exp <= int(datetime.now(timezone.utc).timestamp()):
        return None
    if not payload.get("order_id"):
        return None
    return payload

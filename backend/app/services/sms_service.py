import asyncio
import json
from urllib import error, parse, request

from app.config import settings


class SmsDeliveryError(Exception):
    pass


def _normalize_mobile(mobile: str) -> str:
    digits = "".join(ch for ch in mobile if ch.isdigit())
    if len(digits) == 10:
        return f"{settings.msg91_country_code}{digits}"
    if digits.startswith(settings.msg91_country_code) and len(digits) == len(settings.msg91_country_code) + 10:
        return digits
    raise SmsDeliveryError("Invalid mobile number. Use a valid 10-digit Indian mobile number.")


def _send_msg91_sync(to_mobile: str, message: str) -> dict:
    if not settings.msg91_auth_key or not settings.msg91_sender_id:
        raise SmsDeliveryError("MSG91 configuration missing. Set MSG91_AUTH_KEY and MSG91_SENDER_ID.")
    payload = {
        "route": settings.msg91_route,
        "sender": settings.msg91_sender_id,
        "mobiles": to_mobile,
        "message": message,
    }
    body = parse.urlencode(payload).encode()
    req = request.Request(
        "https://api.msg91.com/api/sendhttp.php",
        data=body,
        headers={"authkey": settings.msg91_auth_key, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode().strip()
            return {"status_code": resp.status, "raw": raw}
    except error.HTTPError as exc:
        detail = exc.read().decode().strip()
        raise SmsDeliveryError(f"MSG91 HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise SmsDeliveryError(f"MSG91 request failed: {exc.reason}") from exc


async def send_ebill_sms(mobile: str, ebill_url: str) -> dict:
    to_mobile = _normalize_mobile(mobile)
    message = f"Aromaz Cafe e-bill: {ebill_url}"
    attempts = max(1, int(settings.msg91_retry_attempts))
    delay = max(0, int(settings.msg91_retry_delay_ms)) / 1000
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            result = await asyncio.to_thread(_send_msg91_sync, to_mobile, message)
            return {"to_mobile": to_mobile, "provider": "msg91", "provider_response": result}
        except SmsDeliveryError as exc:
            last_error = exc
            if delay > 0:
                await asyncio.sleep(delay)
    raise SmsDeliveryError(str(last_error or "SMS send failed"))


def mask_mobile(mobile: str) -> str:
    digits = "".join(ch for ch in mobile if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"

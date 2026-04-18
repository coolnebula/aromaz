from datetime import datetime, timedelta
import base64
from io import BytesIO
import re

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_db
from app.security import hash_with_secret, random_session_token
from app.services.order_service import add_audit


router = APIRouter(prefix="/access", tags=["access"])


class TotpSetupPayload(BaseModel):
    device_label: str = "browser"
    setup_key: str = ""
    user_id: str = "owner"


class VerifyTotpPayload(BaseModel):
    code: str = Field(min_length=4, max_length=12)
    device_label: str = "browser"
    user_id: str = "owner"


def _qr_data_url(uri: str) -> str:
    image = qrcode.make(uri)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


def _normalize_user_id(raw: str) -> str:
    user_id = (raw or "").strip().lower()
    if not user_id:
        return "owner"
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,31}", user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id. Use 2-32 chars: a-z, 0-9, ., _, -")
    return user_id


@router.get("/session")
async def session_check(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    token = request.cookies.get(settings.session_cookie_name)
    configured_count = await db.access_totp.count_documents({"confirmed": True})
    configured = configured_count > 0

    if not token:
        return {"authenticated": False, "totp_configured": configured}
    token_hash = hash_with_secret(token)
    now = datetime.utcnow()
    session = await db.sessions.find_one({"token_hash": token_hash, "expires_at": {"$gt": now}})
    if not session:
        return {"authenticated": False, "totp_configured": configured}
    return {
        "authenticated": True,
        "totp_configured": configured,
        "expires_at": session["expires_at"].isoformat(),
        "user_id": session.get("user_id", "owner"),
    }


@router.post("/totp/setup")
async def totp_setup(payload: TotpSetupPayload, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    user_id = _normalize_user_id(payload.user_id)
    existing = await db.access_totp.find_one({"_id": user_id})
    if not existing and user_id == "owner":
        legacy = await db.access_totp.find_one({"_id": "primary"})
        if legacy and legacy.get("confirmed", False):
            return {"ok": True, "configured": True, "message": "TOTP already configured", "user_id": user_id}
    if existing and existing.get("confirmed", False):
        return {"ok": True, "configured": True, "message": "TOTP already configured", "user_id": user_id}

    if settings.totp_setup_key and payload.setup_key != settings.totp_setup_key:
        raise HTTPException(status_code=403, detail="Invalid setup key")

    # Reuse existing unconfirmed secret so repeated setup clicks do not invalidate scanned QR.
    secret = existing.get("secret") if existing and existing.get("secret") else pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=f"{user_id}:{settings.totp_account_name}",
        issuer_name=settings.totp_issuer,
    )
    qr_data_url = _qr_data_url(uri)
    now = datetime.utcnow()
    await db.access_totp.update_one(
        {"_id": user_id},
        {
            "$set": {
                "secret": secret,
                "confirmed": False,
                "failed_attempts": 0,
                "lock_until": None,
                "device_label": payload.device_label,
                "user_id": user_id,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    await add_audit(db, "TOTP_SETUP_GENERATED", "system", {"device_label": payload.device_label, "user_id": user_id})

    response = {"ok": True, "configured": False, "provisioning_uri": uri, "qr_data_url": qr_data_url, "user_id": user_id}
    if settings.environment == "development":
        response["secret"] = secret
    return response


@router.post("/totp/verify")
async def verify_totp(
    payload: VerifyTotpPayload, response: Response, db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    now = datetime.utcnow()
    user_id = _normalize_user_id(payload.user_id)
    key = user_id
    config = await db.access_totp.find_one({"_id": key})
    if not config and user_id == "owner":
        key = "primary"
        config = await db.access_totp.find_one({"_id": key})
    if not config or not config.get("secret"):
        raise HTTPException(status_code=400, detail=f"TOTP is not configured for user '{user_id}'")

    lock_until = config.get("lock_until")
    if lock_until and lock_until > now:
        remaining = int((lock_until - now).total_seconds() // 60) + 1
        raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in ~{remaining} minute(s).")

    verified = pyotp.TOTP(config["secret"]).verify(payload.code, valid_window=1)
    if not verified:
        failed_attempts = int(config.get("failed_attempts", 0)) + 1
        update_doc = {"$set": {"failed_attempts": failed_attempts, "updated_at": now}}
        if failed_attempts >= settings.otp_max_attempts:
            update_doc["$set"]["lock_until"] = now + timedelta(minutes=settings.otp_lockout_minutes)
            update_doc["$set"]["failed_attempts"] = 0
            await add_audit(db, "TOTP_LOCKED", "system", {"device_label": payload.device_label, "user_id": user_id})
        else:
            await add_audit(db, "TOTP_FAILED", "system", {"device_label": payload.device_label, "user_id": user_id})
        await db.access_totp.update_one({"_id": key}, update_doc)
        raise HTTPException(status_code=400, detail="Invalid authenticator code")

    await db.access_totp.update_one(
        {"_id": key},
        {
            "$set": {
                "confirmed": True,
                "confirmed_at": now,
                "failed_attempts": 0,
                "lock_until": None,
                "updated_at": now,
                "user_id": user_id,
            }
        },
    )

    token = random_session_token()
    token_hash = hash_with_secret(token)
    expires_at = now + timedelta(hours=settings.session_ttl_hours)
    await db.sessions.insert_one(
        {
            "token_hash": token_hash,
            "created_at": now,
            "expires_at": expires_at,
            "device_label": payload.device_label,
            "user_id": user_id,
        }
    )
    await add_audit(
        db,
        "SESSION_ISSUED",
        "system",
        {"device_label": payload.device_label, "expires_at": expires_at.isoformat(), "user_id": user_id},
    )

    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=False if settings.environment == "development" else True,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    return {"ok": True, "expires_in_hours": settings.session_ttl_hours, "user_id": user_id}


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await db.sessions.delete_one({"token_hash": hash_with_secret(token)})
    response.delete_cookie(settings.session_cookie_name, path="/")
    await add_audit(db, "SESSION_CLEARED", "system", {})
    return {"ok": True}

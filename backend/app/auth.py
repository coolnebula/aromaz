from datetime import datetime

from fastapi import Cookie, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.database import get_db
from app.security import hash_with_secret


async def require_session(
    db: AsyncIOMotorDatabase = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> dict:
    if not session_token:
        raise HTTPException(status_code=401, detail="Session required")
    token_hash = hash_with_secret(session_token)
    session = await db.sessions.find_one({"token_hash": token_hash, "expires_at": {"$gt": datetime.utcnow()}})
    if not session:
        raise HTTPException(status_code=401, detail="Session invalid or expired")
    return session

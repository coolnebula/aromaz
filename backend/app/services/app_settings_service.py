from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings

_SETTINGS_ID = "global"

# Process-local cache so hot paths don't hit Mongo on every line-item edit.
_TAX_RATE_CACHE: float | None = None


def _clamp_rate(raw: float) -> float:
    # Safety bounds: allow 0% tax and cap absurd misconfiguration.
    return max(0.0, min(float(raw), 100.0))


async def get_tax_rate_percent(db: AsyncIOMotorDatabase) -> float:
    global _TAX_RATE_CACHE
    if _TAX_RATE_CACHE is not None:
        return _TAX_RATE_CACHE

    doc = await db.app_settings.find_one({"_id": _SETTINGS_ID})
    if doc and doc.get("tax_rate_percent") is not None:
        try:
            _TAX_RATE_CACHE = _clamp_rate(float(doc["tax_rate_percent"]))
            return _TAX_RATE_CACHE
        except (TypeError, ValueError):
            pass

    _TAX_RATE_CACHE = _clamp_rate(float(settings.tax_rate_percent))
    return _TAX_RATE_CACHE


async def set_tax_rate_percent(db: AsyncIOMotorDatabase, rate_percent: float, actor_id: str) -> float:
    global _TAX_RATE_CACHE
    cleaned = _clamp_rate(rate_percent)
    now = datetime.utcnow()
    await db.app_settings.update_one(
        {"_id": _SETTINGS_ID},
        {
            "$set": {
                "tax_rate_percent": cleaned,
                "updated_at": now,
                "updated_by": actor_id,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    _TAX_RATE_CACHE = cleaned
    return cleaned


def invalidate_tax_rate_cache() -> None:
    global _TAX_RATE_CACHE
    _TAX_RATE_CACHE = None

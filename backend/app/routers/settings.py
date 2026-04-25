from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.auth import require_session
from app.database import get_db
from app.services.app_settings_service import get_tax_rate_percent, invalidate_tax_rate_cache, set_tax_rate_percent
from app.services.order_service import add_audit, recompute_open_order_totals_for_tax_rate_change


router = APIRouter(prefix="/settings", tags=["settings"])


class TaxRateUpdate(BaseModel):
    tax_rate_percent: float = Field(ge=0, le=100)
    actor_id: str = "owner"


@router.get("/tax")
async def get_tax_rate(db: AsyncIOMotorDatabase = Depends(get_db), _: dict = Depends(require_session)) -> dict:
    rate = await get_tax_rate_percent(db)
    return {"tax_rate_percent": rate}


@router.put("/tax")
async def put_tax_rate(
    payload: TaxRateUpdate, db: AsyncIOMotorDatabase = Depends(get_db), _: dict = Depends(require_session)
) -> dict:
    try:
        invalidate_tax_rate_cache()
        rate = await set_tax_rate_percent(db, payload.tax_rate_percent, payload.actor_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid tax rate") from exc
    await add_audit(
        db,
        "TAX_RATE_UPDATED",
        payload.actor_id,
        {"tax_rate_percent": rate},
    )
    updated_orders = await recompute_open_order_totals_for_tax_rate_change(db)
    return {"ok": True, "tax_rate_percent": rate, "recomputed_open_orders": updated_orders}

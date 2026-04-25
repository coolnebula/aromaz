from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.schemas import (
    DiscountPayload,
    OrderCreate,
    OrderItemCreate,
    OrderItemUpdate,
    ServePendingPayload,
    StatusUpdate,
    VoidItemPayload,
)
from app.services.order_service import (
    add_item,
    apply_discount,
    create_order,
    delete_order,
    get_order_or_none,
    normalize_order_response,
    serve_pending_items,
    update_item,
    update_order_status,
    void_item,
)


router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("")
async def create_order_route(payload: OrderCreate, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    created = await create_order(db, payload.table_id, payload.actor_id)
    return await normalize_order_response(db, created)


@router.get("/{order_id}")
async def get_order_route(order_id: str, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return await normalize_order_response(db, order)


@router.post("/{order_id}/items")
async def add_item_route(order_id: str, payload: OrderItemCreate, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    try:
        updated = await add_item(db, order_id, payload, actor_id="cashier-demo")
        return await normalize_order_response(db, updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{order_id}/items/{item_index}")
async def update_item_route(
    order_id: str, item_index: int, payload: OrderItemUpdate, db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    try:
        updated = await update_item(db, order_id, item_index, payload, actor_id="cashier-demo")
        return await normalize_order_response(db, updated)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/{order_id}/items/{item_index}/void")
async def void_item_route(
    order_id: str, item_index: int, payload: VoidItemPayload, db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    try:
        updated = await void_item(db, order_id, item_index, payload.reason, payload.actor_id)
        return await normalize_order_response(db, updated)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/{order_id}/status")
async def update_status_route(order_id: str, payload: StatusUpdate, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    try:
        updated = await update_order_status(db, order_id, payload.status, payload.actor_id, payload.reason)
        return await normalize_order_response(db, updated)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/{order_id}/serve-pending")
async def serve_pending_route(
    order_id: str, payload: ServePendingPayload = ServePendingPayload(), db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    try:
        updated = await serve_pending_items(db, order_id, payload.actor_id)
        return await normalize_order_response(db, updated)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/{order_id}/discount")
async def apply_discount_route(
    order_id: str, payload: DiscountPayload, db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    try:
        updated = await apply_discount(db, order_id, payload.amount, payload.manager_id, payload.reason)
        return await normalize_order_response(db, updated)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.delete("/{order_id}")
async def delete_order_route(order_id: str, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    try:
        await delete_order(db, order_id, actor_id="cashier-demo", reason="Deleted from day-wise order history")
        return {"ok": True, "id": order_id}
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc

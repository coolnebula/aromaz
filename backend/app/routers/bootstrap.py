from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.services.menu_service import ensure_menu_seeded, load_menu_grouped
from app.services.order_service import ensure_tables_seeded, normalize_order_response


router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])


@router.get("")
async def bootstrap(db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    await ensure_tables_seeded(db)
    await ensure_menu_seeded(db)
    tables = []
    async for table in db.tables.find({}, {"_id": 0}):
        tables.append(table)
    menu = await load_menu_grouped(db)
    active_orders: dict[str, dict] = {}
    cursor = db.orders.find(
        {"status": {"$nin": ["Paid", "Cancelled"]}},
        {"_id": 1, "table_id": 1, "status": 1, "items": 1, "discount": 1, "totals": 1, "updated_at": 1},
    ).sort([("updated_at", -1)])
    async for order in cursor:
        table_id = order["table_id"]
        if table_id in active_orders:
            continue
        active_orders[table_id] = normalize_order_response(order)
    return {"tables": tables, "menu": menu, "active_orders": active_orders}

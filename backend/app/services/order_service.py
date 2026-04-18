from datetime import datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas import ModifierPayload, OrderItemCreate, OrderItemUpdate, OrderStatus


PIPELINE = ["Open", "Served", "Billed", "Paid"]
TABLES = ["T1", "T2", "T3", "T4"]


def _totals(items: list[dict[str, Any]], discount: float = 0) -> dict[str, float]:
    subtotal = sum((i["price"] * i["qty"]) for i in items if not i.get("voided"))
    discount = min(discount, subtotal)
    tax = round((subtotal - discount) * 0.05, 2)
    total = round(subtotal - discount + tax, 2)
    return {"subtotal": subtotal, "discount": discount, "tax": tax, "total": total}


def _is_served_or_later(status: str) -> bool:
    normalized = "Open" if status == "SentToKitchen" else status
    return normalized in {"Served", "Billed", "Paid"}


def _safe_qty(value: Any) -> int:
    try:
        qty = int(value)
    except (TypeError, ValueError):
        return 1
    return max(qty, 1)


def _normalize_item_service_state(item: dict[str, Any], status: str) -> dict[str, Any]:
    next_item = {**item}
    qty = _safe_qty(next_item.get("qty", 1))
    next_item["qty"] = qty
    is_voided = bool(next_item.get("voided"))
    served_by_status = _is_served_or_later(status) and not is_voided
    has_served_qty = "served_qty" in next_item
    if has_served_qty:
        try:
            served_qty = int(next_item.get("served_qty") or 0)
        except (TypeError, ValueError):
            served_qty = 0
    elif "served" in next_item:
        served_qty = qty if bool(next_item.get("served")) and not is_voided else 0
    else:
        served_qty = qty if served_by_status else 0
    served_qty = max(0, min(served_qty, qty))
    next_item["served_qty"] = served_qty
    next_item["served"] = bool(not is_voided and served_qty >= qty)
    next_item["served_at"] = next_item.get("served_at") or None
    return next_item


def _normalize_items_service_state(items: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    return [_normalize_item_service_state(item, status) for item in items]


def _pending_service_qty(order: dict[str, Any]) -> int:
    pending = 0
    for item in order.get("items", []):
        if item.get("voided"):
            continue
        qty = _safe_qty(item.get("qty", 1))
        try:
            raw_served_qty = int(item.get("served_qty") or 0)
        except (TypeError, ValueError):
            raw_served_qty = 0
        served_qty = max(0, min(raw_served_qty, qty))
        pending += max(qty - served_qty, 0)
    return pending


async def ensure_tables_seeded(db: AsyncIOMotorDatabase) -> None:
    count = await db.tables.count_documents({})
    if count:
        return
    await db.tables.insert_many(
        [{"table_id": table_id, "active_order_id": None, "updated_at": datetime.utcnow()} for table_id in TABLES]
    )


async def add_audit(db: AsyncIOMotorDatabase, action: str, actor_id: str, payload: dict[str, Any]) -> None:
    await db.audit_logs.insert_one(
        {"action": action, "actor_id": actor_id, "payload": payload, "created_at": datetime.utcnow()}
    )


async def create_order(db: AsyncIOMotorDatabase, table_id: str, actor_id: str) -> dict[str, Any]:
    active = await get_active_order_for_table(db, table_id)
    if active:
        return active

    now = datetime.utcnow()
    doc = {
        "table_id": table_id,
        "status": "Open",
        "items": [],
        "discount": 0.0,
        "totals": _totals([], 0),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.orders.insert_one(doc)
    await db.tables.update_one({"table_id": table_id}, {"$set": {"active_order_id": str(result.inserted_id), "updated_at": now}})
    await add_audit(db, "ORDER_CREATED", actor_id, {"table_id": table_id, "order_id": str(result.inserted_id)})
    doc["id"] = str(result.inserted_id)
    return doc


async def get_order_or_none(db: AsyncIOMotorDatabase, order_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(order_id):
        return None
    doc = await db.orders.find_one({"_id": ObjectId(order_id)})
    if not doc:
        return None
    doc["items"] = _normalize_items_service_state(doc.get("items", []), doc.get("status", "Open"))
    doc["id"] = str(doc["_id"])
    return doc


async def add_item(db: AsyncIOMotorDatabase, order_id: str, payload: OrderItemCreate, actor_id: str) -> dict[str, Any]:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise ValueError("Order not found")
    if order["status"] in {"Billed", "Paid", "Cancelled"}:
        raise ValueError("Cannot modify billed/paid/cancelled order")

    item = payload.model_dump()
    item["voided"] = False
    item["void_reason"] = ""
    item["voided_at"] = None
    item["voided_by"] = ""
    item["served"] = False
    item["served_qty"] = 0
    item["served_at"] = None
    order["items"].append(item)
    order["totals"] = _totals(order["items"], order.get("discount", 0))
    order["updated_at"] = datetime.utcnow()

    await db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"items": order["items"], "totals": order["totals"], "updated_at": order["updated_at"]}},
    )
    await add_audit(db, "ITEM_ADDED", actor_id, {"order_id": order_id, "item": item})
    return order


async def update_item(
    db: AsyncIOMotorDatabase, order_id: str, item_index: int, payload: OrderItemUpdate, actor_id: str
) -> dict[str, Any]:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise ValueError("Order not found")
    if order["status"] in {"Billed", "Paid", "Cancelled"}:
        raise ValueError("Cannot modify billed/paid/cancelled order")
    if item_index < 0 or item_index >= len(order["items"]):
        raise ValueError("Invalid item index")
    if order["items"][item_index].get("voided"):
        raise ValueError("Cannot edit voided item")

    before = order["items"][item_index].copy()
    prev_item = _normalize_item_service_state(order["items"][item_index], order.get("status", "Open"))
    next_item = {**prev_item}
    next_item["qty"] = payload.qty
    next_item["modifiers"] = payload.modifiers.model_dump()
    next_item = _normalize_item_service_state(next_item, order.get("status", "Open"))
    order["items"][item_index] = next_item
    order["updated_at"] = datetime.utcnow()
    order["totals"] = _totals(order["items"], order.get("discount", 0))

    await db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"items": order["items"], "totals": order["totals"], "updated_at": order["updated_at"]}},
    )
    await add_audit(
        db,
        "ITEM_UPDATED",
        actor_id,
        {"order_id": order_id, "item_index": item_index, "before": before, "after": order["items"][item_index]},
    )
    return order


async def void_item(
    db: AsyncIOMotorDatabase, order_id: str, item_index: int, reason: str, actor_id: str
) -> dict[str, Any]:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise ValueError("Order not found")
    if order["status"] in {"Billed", "Paid", "Cancelled"}:
        raise ValueError("Cannot modify billed/paid/cancelled order")
    if item_index < 0 or item_index >= len(order["items"]):
        raise ValueError("Invalid item index")
    if not reason.strip():
        raise ValueError("Void reason is required")
    if order["items"][item_index].get("voided"):
        return order

    now = datetime.utcnow()
    order["items"][item_index]["voided"] = True
    order["items"][item_index]["void_reason"] = reason.strip()
    order["items"][item_index]["voided_at"] = now
    order["items"][item_index]["voided_by"] = actor_id
    order["updated_at"] = now
    order["totals"] = _totals(order["items"], order.get("discount", 0))
    await db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"items": order["items"], "totals": order["totals"], "updated_at": order["updated_at"]}},
    )
    await add_audit(
        db,
        "ITEM_VOIDED",
        actor_id,
        {"order_id": order_id, "item_index": item_index, "reason": reason.strip()},
    )
    return order


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    # Backward-compatible handling for historical orders.
    if current == "SentToKitchen":
        current = "Open"
    if target == "Cancelled":
        return current not in {"Paid", "Cancelled"}
    if current == target:
        return True
    if current in {"Paid", "Cancelled"}:
        return False
    ci = PIPELINE.index(current)
    ti = PIPELINE.index(target)
    return ti == ci + 1


async def get_active_order_for_table(db: AsyncIOMotorDatabase, table_id: str) -> dict[str, Any] | None:
    doc = await db.orders.find_one(
        {"table_id": table_id, "status": {"$nin": ["Paid", "Cancelled"]}},
        sort=[("updated_at", -1)],
    )
    if not doc:
        return None
    doc["items"] = _normalize_items_service_state(doc.get("items", []), doc.get("status", "Open"))
    doc["id"] = str(doc["_id"])
    return doc


def normalize_order_response(order: dict[str, Any]) -> dict[str, Any]:
    normalized_items = _normalize_items_service_state(order.get("items", []), order.get("status", "Open"))
    return {
        "id": order.get("id") or str(order["_id"]),
        "table_id": order["table_id"],
        "status": order["status"],
        "items": normalized_items,
        "discount": order.get("discount", 0),
        "totals": order.get("totals", _totals(normalized_items, order.get("discount", 0))),
        "updated_at": order.get("updated_at"),
    }


async def update_order_status(
    db: AsyncIOMotorDatabase, order_id: str, status: OrderStatus, actor_id: str, reason: str = ""
) -> dict[str, Any]:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise ValueError("Order not found")
    if status == "Cancelled" and not reason.strip():
        raise ValueError("Cancel reason is required")
    if not can_transition(order["status"], status):
        raise ValueError("Invalid status transition")
    if status == "Billed" and _pending_service_qty(order) > 0:
        raise ValueError("Cannot move to billed while some items are pending service")

    now = datetime.utcnow()
    if status == "Served":
        items = []
        for item in order.get("items", []):
            next_item = _normalize_item_service_state(item, order.get("status", "Open"))
            if not next_item.get("voided") and next_item.get("served_qty", 0) < next_item.get("qty", 1):
                next_item["served_qty"] = next_item.get("qty", 1)
                next_item["served"] = True
                next_item["served_at"] = now
            items.append(next_item)
        order["items"] = items
    await db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"status": status, "items": order.get("items", []), "updated_at": now}},
    )
    if status in {"Paid", "Cancelled"}:
        await db.tables.update_one({"table_id": order["table_id"]}, {"$set": {"active_order_id": None, "updated_at": now}})

    await add_audit(
        db,
        "STATUS_UPDATED",
        actor_id,
        {"order_id": order_id, "from": order["status"], "to": status, "reason": reason},
    )
    order["status"] = status
    order["updated_at"] = now
    return order


async def serve_pending_items(db: AsyncIOMotorDatabase, order_id: str, actor_id: str) -> dict[str, Any]:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise ValueError("Order not found")
    if order["status"] != "Served":
        raise ValueError("Serve pending items is only allowed when order status is Served")

    now = datetime.utcnow()
    pending_count = 0
    items: list[dict[str, Any]] = []
    for item in order.get("items", []):
        next_item = _normalize_item_service_state(item, order.get("status", "Open"))
        if not next_item.get("voided") and next_item.get("served_qty", 0) < next_item.get("qty", 1):
            next_item["served_qty"] = next_item.get("qty", 1)
            next_item["served"] = True
            next_item["served_at"] = now
            pending_count += 1
        items.append(next_item)

    if pending_count == 0:
        return order

    await db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"items": items, "updated_at": now}},
    )
    await add_audit(
        db,
        "PENDING_ITEMS_SERVED",
        actor_id,
        {"order_id": order_id, "served_items": pending_count},
    )
    order["items"] = items
    order["updated_at"] = now
    return order


async def apply_discount(
    db: AsyncIOMotorDatabase, order_id: str, amount: float, manager_id: str, reason: str
) -> dict[str, Any]:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise ValueError("Order not found")
    if order["status"] in {"Paid", "Cancelled"}:
        raise ValueError("Cannot discount paid/cancelled order")
    if not manager_id.startswith("manager-"):
        raise PermissionError("Manager authorization required")
    if not reason.strip():
        raise ValueError("Discount reason is required")

    subtotal = sum((i["price"] * i["qty"]) for i in order["items"])
    discount = min(amount, subtotal)
    totals = _totals(order["items"], discount)

    now = datetime.utcnow()
    await db.orders.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"discount": discount, "totals": totals, "updated_at": now}},
    )
    await add_audit(
        db,
        "DISCOUNT_APPLIED",
        manager_id,
        {"order_id": order_id, "amount": discount, "reason": reason},
    )
    order["discount"] = discount
    order["totals"] = totals
    order["updated_at"] = now
    return order


async def delete_order(db: AsyncIOMotorDatabase, order_id: str, actor_id: str, reason: str = "") -> None:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise ValueError("Order not found")

    now = datetime.utcnow()
    await db.orders.delete_one({"_id": ObjectId(order_id)})
    await db.tables.update_one(
        {"table_id": order["table_id"], "active_order_id": order_id},
        {"$set": {"active_order_id": None, "updated_at": now}},
    )
    await add_audit(
        db,
        "ORDER_DELETED",
        actor_id,
        {
            "order_id": order_id,
            "table_id": order.get("table_id"),
            "status": order.get("status"),
            "reason": reason,
        },
    )


async def execute_sync_mutation(
    db: AsyncIOMotorDatabase, action: str, payload: dict[str, Any], actor_id: str
) -> dict[str, Any]:
    if action == "CREATE_ORDER":
        table_id = payload.get("tableId")
        if not table_id:
            raise ValueError("CREATE_ORDER missing tableId")
        created = await create_order(db, table_id, actor_id)
        return {"order_id": created["id"], "status": created["status"]}

    if action == "ADD_ITEM":
        table_id = payload.get("tableId")
        if not table_id:
            raise ValueError("ADD_ITEM missing tableId")
        order_id = payload.get("orderId")
        order = await get_order_or_none(db, order_id) if order_id else None
        if not order:
            order = await get_active_order_for_table(db, table_id)
        if not order:
            order = await create_order(db, table_id, actor_id)
        item = OrderItemCreate(
            name=payload["name"],
            price=payload["price"],
            qty=payload.get("qty", 1),
            modifiers=ModifierPayload(**payload.get("modifiers", {})),
        )
        updated = await add_item(db, order["id"], item, actor_id)
        return {"order_id": updated["id"], "status": updated["status"]}

    if action == "STATUS_UPDATE":
        order_id = payload.get("orderId")
        table_id = payload.get("tableId")
        status = payload.get("status")
        if not status:
            raise ValueError("STATUS_UPDATE missing status")
        order = await get_order_or_none(db, order_id) if order_id else None
        if not order and table_id:
            order = await get_active_order_for_table(db, table_id)
        if not order:
            raise ValueError("No active order found for status update")
        updated = await update_order_status(db, order["id"], status, actor_id, payload.get("reason", ""))
        return {"order_id": updated["id"], "status": updated["status"]}

    if action == "SERVE_PENDING_ITEMS":
        order_id = payload.get("orderId")
        table_id = payload.get("tableId")
        order = await get_order_or_none(db, order_id) if order_id else None
        if not order and table_id:
            order = await get_active_order_for_table(db, table_id)
        if not order:
            raise ValueError("No active order found to serve pending items")
        updated = await serve_pending_items(db, order["id"], actor_id)
        return {"order_id": updated["id"], "status": updated["status"]}

    if action == "VOID_ITEM":
        order_id = payload.get("orderId")
        table_id = payload.get("tableId")
        item_index = payload.get("itemIndex")
        reason = payload.get("reason", "")
        if item_index is None:
            raise ValueError("VOID_ITEM missing itemIndex")
        order = await get_order_or_none(db, order_id) if order_id else None
        if not order and table_id:
            order = await get_active_order_for_table(db, table_id)
        if not order:
            raise ValueError("No active order found for void item")
        updated = await void_item(db, order["id"], int(item_index), reason, actor_id)
        return {"order_id": updated["id"], "status": updated["status"]}

    if action == "UPDATE_ITEM":
        order_id = payload.get("orderId")
        table_id = payload.get("tableId")
        item_index = payload.get("itemIndex")
        if item_index is None:
            raise ValueError("UPDATE_ITEM missing itemIndex")
        order = await get_order_or_none(db, order_id) if order_id else None
        if not order and table_id:
            order = await get_active_order_for_table(db, table_id)
        if not order:
            raise ValueError("No active order found for update item")
        update_payload = OrderItemUpdate(
            qty=payload.get("qty", 1),
            modifiers=ModifierPayload(**payload.get("modifiers", {})),
        )
        updated = await update_item(db, order["id"], int(item_index), update_payload, actor_id)
        return {"order_id": updated["id"], "status": updated["status"]}

    if action == "APPLY_DISCOUNT":
        order_id = payload.get("orderId")
        table_id = payload.get("tableId")
        amount = payload.get("amount")
        manager_id = payload.get("managerId", "")
        reason = payload.get("reason", "")
        if amount is None:
            raise ValueError("APPLY_DISCOUNT missing amount")
        order = await get_order_or_none(db, order_id) if order_id else None
        if not order and table_id:
            order = await get_active_order_for_table(db, table_id)
        if not order:
            raise ValueError("No active order found for discount")
        updated = await apply_discount(db, order["id"], float(amount), manager_id, reason)
        return {"order_id": updated["id"], "status": updated["status"]}

    raise ValueError(f"Unsupported sync action: {action}")


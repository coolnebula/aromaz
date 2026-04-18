from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.database import get_db


router = APIRouter(prefix="/menu", tags=["menu"])


class MenuItemPayload(BaseModel):
    category: str | None = None
    category_id: str | None = None
    name: str
    price: float = Field(gt=0)
    position: int = 0


class MenuItemUpdatePayload(BaseModel):
    category: str | None = None
    category_id: str | None = None
    name: str | None = None
    price: float | None = Field(default=None, gt=0)
    position: int | None = None
    is_active: bool | None = None


class CategoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    position: int = 0
    is_active: bool = True


class CategoryUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    position: int | None = None
    is_active: bool | None = None


async def _resolve_category_name(
    db: AsyncIOMotorDatabase, category: str | None, category_id: str | None, *, required: bool = True
) -> str | None:
    if category and category.strip():
        return category.strip()
    if category_id:
        if not ObjectId.is_valid(category_id):
            raise HTTPException(status_code=400, detail="Invalid category id")
        category_doc = await db.menu_categories.find_one({"_id": ObjectId(category_id)})
        if not category_doc:
            raise HTTPException(status_code=404, detail="Category not found")
        return str(category_doc["name"]).strip()
    if required:
        raise HTTPException(status_code=400, detail="Category is required")
    return None


@router.get("")
async def list_menu_items(db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    items = []
    async for item in db.menu_items.find({}).sort([("category", 1), ("position", 1), ("name", 1)]):
        item["id"] = str(item["_id"])
        item.pop("_id", None)
        items.append(item)
    return {"items": items}


@router.get("/categories")
async def list_categories(db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    categories = []
    async for category in db.menu_categories.find({}).sort([("position", 1), ("name", 1)]):
        name = category["name"]
        item_count = await db.menu_items.count_documents({"category": name})
        active_item_count = await db.menu_items.count_documents({"category": name, "is_active": True})
        categories.append(
            {
                "id": str(category["_id"]),
                "name": name,
                "position": category.get("position", 0),
                "is_active": bool(category.get("is_active", True)),
                "item_count": item_count,
                "active_item_count": active_item_count,
            }
        )
    return {"categories": categories}


@router.post("/categories")
async def create_category(payload: CategoryPayload, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    now = datetime.utcnow()
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    exists = await db.menu_categories.find_one({"name": name})
    if exists:
        raise HTTPException(status_code=400, detail="Category already exists")
    doc = {
        "name": name,
        "position": payload.position,
        "is_active": payload.is_active,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.menu_categories.insert_one(doc)
    doc.pop("_id", None)
    return {"id": str(result.inserted_id), **doc}


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: str, payload: CategoryUpdatePayload, db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    if not ObjectId.is_valid(category_id):
        raise HTTPException(status_code=400, detail="Invalid category id")
    current = await db.menu_categories.find_one({"_id": ObjectId(category_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Category not found")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if not updates["name"]:
            raise HTTPException(status_code=400, detail="Category name is required")
        dupe = await db.menu_categories.find_one({"name": updates["name"], "_id": {"$ne": ObjectId(category_id)}})
        if dupe:
            raise HTTPException(status_code=400, detail="Category already exists")

    updates["updated_at"] = datetime.utcnow()
    await db.menu_categories.update_one({"_id": ObjectId(category_id)}, {"$set": updates})

    if "name" in updates and updates["name"] != current["name"]:
        await db.menu_items.update_many({"category": current["name"]}, {"$set": {"category": updates["name"], "updated_at": datetime.utcnow()}})

    category = await db.menu_categories.find_one({"_id": ObjectId(category_id)})
    return {
        "id": str(category["_id"]),
        "name": category["name"],
        "position": category.get("position", 0),
        "is_active": bool(category.get("is_active", True)),
    }


@router.delete("/categories/{category_id}")
async def delete_category(category_id: str, move_to_category_id: str | None = None, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    if not ObjectId.is_valid(category_id):
        raise HTTPException(status_code=400, detail="Invalid category id")
    category = await db.menu_categories.find_one({"_id": ObjectId(category_id)})
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    move_target_name = None
    if move_to_category_id:
        if not ObjectId.is_valid(move_to_category_id):
            raise HTTPException(status_code=400, detail="Invalid target category id")
        if move_to_category_id == category_id:
            raise HTTPException(status_code=400, detail="Target category must be different")
        target = await db.menu_categories.find_one({"_id": ObjectId(move_to_category_id)})
        if not target:
            raise HTTPException(status_code=404, detail="Target category not found")
        move_target_name = target["name"]

    item_count = await db.menu_items.count_documents({"category": category["name"]})
    if item_count > 0 and not move_target_name:
        raise HTTPException(status_code=400, detail="Category contains items. Provide move_to_category_id.")
    if move_target_name:
        await db.menu_items.update_many(
            {"category": category["name"]},
            {"$set": {"category": move_target_name, "updated_at": datetime.utcnow()}},
        )
    await db.menu_categories.delete_one({"_id": ObjectId(category_id)})
    return {"ok": True}


@router.get("/items")
async def list_menu_items_v2(
    include_inactive: bool = True,
    query: str = "",
    category: str = "",
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    filters: dict = {}
    if not include_inactive:
        filters["is_active"] = True
    if query.strip():
        filters["name"] = {"$regex": query.strip(), "$options": "i"}
    if category.strip():
        filters["category"] = category.strip()

    items = []
    async for item in db.menu_items.find(filters).sort([("category", 1), ("position", 1), ("name", 1)]):
        item["id"] = str(item["_id"])
        item.pop("_id", None)
        items.append(item)
    return {"items": items}


@router.post("/items")
async def create_menu_item(payload: MenuItemPayload, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    now = datetime.utcnow()
    category_name = await _resolve_category_name(db, payload.category, payload.category_id, required=True)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Item name is required")
    doc = {
        "category": category_name,
        "name": name,
        "price": payload.price,
        "position": payload.position,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await db.menu_items.insert_one(doc)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Unable to create menu item: {exc}") from exc
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.patch("/items/{item_id}")
async def update_menu_item(
    item_id: str, payload: MenuItemUpdatePayload, db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid item id")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "category" in updates or "category_id" in updates:
        resolved = await _resolve_category_name(
            db, updates.get("category"), updates.get("category_id"), required=False
        )
        if resolved:
            updates["category"] = resolved
        updates.pop("category_id", None)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if not updates["name"]:
            raise HTTPException(status_code=400, detail="Item name is required")
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    updates["updated_at"] = datetime.utcnow()
    await db.menu_items.update_one({"_id": ObjectId(item_id)}, {"$set": updates})
    item = await db.menu_items.find_one({"_id": ObjectId(item_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    item["id"] = str(item["_id"])
    item.pop("_id", None)
    return item


@router.delete("/items/{item_id}")
async def delete_menu_item(item_id: str, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid item id")
    result = await db.menu_items.delete_one({"_id": ObjectId(item_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return {"ok": True}

from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase


DEFAULT_MENU = {
    "Coffee & Chocolates": [
        {"name": "Espresso", "price": 75},
        {"name": "Iced Coffee", "price": 125},
        {"name": "Cappuccino", "price": 125},
        {"name": "Americano/Black Coffee", "price": 80},
        {"name": "Affogato", "price": 155},
        {"name": "Vietnamese Ice Coffee", "price": 155},
        {"name": "Hot Chocolate", "price": 120},
    ],
    "Tea & Infusions": [
        {"name": "Darjeeling Tea", "price": 80},
        {"name": "Earl Grey Tea", "price": 70},
        {"name": "Mint Peppermint Infusion", "price": 70},
        {"name": "Calming Chamomile Infusion", "price": 70},
        {"name": "Cranberry Apple Infusion", "price": 70},
        {"name": "Lemongrass Ginger Infusion", "price": 70},
        {"name": "Raspberry Mint Infusion", "price": 70},
        {"name": "Wild Berry Iced Infusion", "price": 70},
    ],
    "Small Bites": [
        {"name": "Veggies Finger", "price": 99},
        {"name": "Crispy Potato", "price": 99},
        {"name": "Chicken Sausage", "price": 120},
        {"name": "Fish Fry", "price": 100},
        {"name": "Chilly Cheese", "price": 100},
        {"name": "Garlic Toast", "price": 100},
    ],
    "Sandwiches": [
        {"name": "Veg Cheese Sandwich", "price": 110},
        {"name": "Chicken Ham Cheese Sandwich", "price": 150},
        {"name": "Pork Ham Cheese Sandwich", "price": 200},
        {"name": "Bacon Cheese Sandwich", "price": 200},
    ],
    "Chilled Cans": [
        {"name": "Diet Coke", "price": 60},
        {"name": "Thums Up", "price": 60},
        {"name": "Red Bull", "price": 140},
    ],
}


async def ensure_menu_seeded(db: AsyncIOMotorDatabase) -> None:
    await db.menu_items.create_index([("category", 1), ("name", 1)], unique=True)
    await db.menu_categories.create_index([("name", 1)], unique=True)
    count = await db.menu_items.count_documents({})
    now = datetime.utcnow()
    if count == 0:
        docs: list[dict[str, Any]] = []
        for category, items in DEFAULT_MENU.items():
            for position, item in enumerate(items):
                docs.append(
                    {
                        "category": category,
                        "name": item["name"],
                        "price": float(item["price"]),
                        "position": position,
                        "is_active": True,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
        if docs:
            await db.menu_items.insert_many(docs)

    category_count = await db.menu_categories.count_documents({})
    if category_count == 0:
        category_docs = []
        for position, category_name in enumerate(DEFAULT_MENU.keys()):
            category_docs.append(
                {
                    "name": category_name,
                    "position": position,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if category_docs:
            await db.menu_categories.insert_many(category_docs)

    existing_names = {
        doc["name"]
        async for doc in db.menu_categories.find({}, {"_id": 0, "name": 1})
    }
    item_categories = {
        doc["category"]
        async for doc in db.menu_items.find({}, {"_id": 0, "category": 1})
    }
    missing = sorted(name for name in item_categories if name and name not in existing_names)
    for name in missing:
        await db.menu_categories.insert_one(
            {
                "name": name,
                "position": 9999,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )


async def load_menu_grouped(db: AsyncIOMotorDatabase) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    active_categories: list[str] = []
    async for category in db.menu_categories.find(
        {"is_active": True},
        {"_id": 0, "name": 1, "position": 1},
    ).sort([("position", 1), ("name", 1)]):
        active_categories.append(category["name"])
        grouped.setdefault(category["name"], [])

    cursor = db.menu_items.find(
        {"is_active": True},
        {"_id": 0, "category": 1, "name": 1, "price": 1, "position": 1},
    ).sort([("category", 1), ("position", 1), ("name", 1)])
    async for item in cursor:
        category = item["category"]
        if active_categories and category not in active_categories:
            continue
        grouped.setdefault(category, []).append({"name": item["name"], "price": item["price"]})
    return {category: items for category, items in grouped.items() if items}

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings


client = AsyncIOMotorClient(settings.mongo_uri)
db: AsyncIOMotorDatabase = client[settings.mongo_db_name]


def get_db() -> AsyncIOMotorDatabase:
    return db

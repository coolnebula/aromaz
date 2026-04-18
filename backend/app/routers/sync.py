from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.schemas import SyncBatchRequest
from app.services.order_service import add_audit, execute_sync_mutation


router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/batch")
async def sync_batch(payload: SyncBatchRequest, db: AsyncIOMotorDatabase = Depends(get_db)) -> dict:
    await db.sync_mutations.create_index("mutation_id", unique=True)
    accepted = 0
    duplicates = 0
    failed = 0
    accepted_ids: list[str] = []
    duplicate_ids: list[str] = []
    failed_items: list[dict] = []
    for mutation in payload.mutations:
        existing = await db.sync_mutations.find_one({"mutation_id": mutation.mutation_id})
        if existing:
            duplicates += 1
            duplicate_ids.append(mutation.mutation_id)
            continue
        try:
            result = await execute_sync_mutation(db, mutation.action, mutation.payload, mutation.actor_id)
            await db.sync_mutations.insert_one({**mutation.model_dump(), "result": result, "status": "applied"})
            await add_audit(
                db,
                "SYNC_MUTATION_ACCEPTED",
                mutation.actor_id,
                {"mutation_id": mutation.mutation_id, "action": mutation.action, "result": result},
            )
            accepted += 1
            accepted_ids.append(mutation.mutation_id)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            failed_items.append({"mutation_id": mutation.mutation_id, "error": str(exc)})
            await add_audit(
                db,
                "SYNC_MUTATION_REJECTED",
                mutation.actor_id,
                {"mutation_id": mutation.mutation_id, "action": mutation.action, "error": str(exc)},
            )
    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "failed": failed,
        "accepted_ids": accepted_ids,
        "duplicate_ids": duplicate_ids,
        "failed_items": failed_items,
    }

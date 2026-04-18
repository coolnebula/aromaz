from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.services.report_dashboard_service import (
    build_report_analytics,
    generate_dashboard_payload,
    generate_dashboard_stream_events,
)


router = APIRouter(prefix="/reports", tags=["reports"])


def _to_utc_iso(value: datetime | None) -> str | None:
    if not value:
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_range(date: str | None, from_date: str | None, to_date: str | None) -> tuple[str, datetime, datetime]:
    if date:
        start_date = end_date = date
    else:
        today = datetime.utcnow().date().isoformat()
        start_date = from_date or today
        end_date = to_date or start_date
    start = datetime.fromisoformat(f"{start_date}T00:00:00")
    end = datetime.fromisoformat(f"{end_date}T23:59:59")
    return f"{start_date}..{end_date}" if start_date != end_date else start_date, start, end


@router.get("/end-of-day")
async def end_of_day(
    date: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    label, start, end = _resolve_range(date, from_date, to_date)

    pipeline = [
        {"$match": {"updated_at": {"$gte": start, "$lte": end}}},
        {
            "$group": {
                "_id": "$status",
                "count": {"$sum": 1},
                "total_amount": {"$sum": "$totals.total"},
            }
        },
    ]

    summary = {}
    async for row in db.orders.aggregate(pipeline):
        summary[row["_id"]] = {"count": row["count"], "total_amount": row["total_amount"]}
    return {"date": label, "from_date": start.date().isoformat(), "to_date": end.date().isoformat(), "summary": summary}


@router.get("/history")
async def day_history(
    date: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    label, start, end = _resolve_range(date, from_date, to_date)
    rows = []
    cursor = db.orders.find(
        {"created_at": {"$gte": start, "$lte": end}},
        {"_id": 1, "table_id": 1, "status": 1, "totals": 1, "updated_at": 1, "created_at": 1, "items": 1},
    ).sort([("created_at", -1)])
    async for order in cursor:
        order_time = order.get("created_at") or order.get("updated_at")
        rows.append(
            {
                "id": str(order["_id"]),
                "table_id": order.get("table_id"),
                "status": order.get("status"),
                "created_at": _to_utc_iso(order_time),
                "item_count": len(order.get("items", [])),
                "total": (order.get("totals") or {}).get("total", 0),
            }
        )
    return {"date": label, "from_date": start.date().isoformat(), "to_date": end.date().isoformat(), "orders": rows}


@router.get("/dashboard-html")
async def dashboard_html(
    date: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    mode: str = Query(default="deterministic"),
    hour_scope: str = Query(default="all"),
    llm_model: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    selected_mode = mode if mode in {"deterministic", "llm"} else "deterministic"
    selected_hour_scope = "operating" if hour_scope == "operating" else "all"
    if selected_mode != "llm":
        selected_hour_scope = "all"
    label, analytics, start_date, end_date = await _load_dashboard_analytics(date, from_date, to_date, db)
    dashboard = await generate_dashboard_payload(
        analytics, mode=selected_mode, hour_scope=selected_hour_scope, llm_model=llm_model
    )
    response = {
        "date": label,
        "from_date": start_date,
        "to_date": end_date,
        "analytics_summary": analytics.get("meta", {}),
        "analytics_diagnostics": analytics.get("diagnostics", {}),
        "analytics_operating_context": analytics.get("operating_context", {}),
        "analytics_monthly": analytics.get("monthly_summary", []),
        **dashboard,
    }
    if selected_mode == "deterministic":
        response["deterministic_metrics"] = analytics.get("deterministic_metrics", {})
    else:
        response["deterministic_metrics"] = {}
    if selected_mode != "llm":
        response["key_insights"] = []
    return response


@router.get("/dashboard-stream")
async def dashboard_stream(
    date: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    mode: str = Query(default="llm"),
    hour_scope: str = Query(default="operating"),
    llm_model: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    selected_mode = "llm" if mode == "llm" else "deterministic"
    selected_hour_scope = "operating" if hour_scope == "operating" else "all"
    if selected_mode != "llm":
        selected_hour_scope = "all"
    label, analytics, start_date, end_date = await _load_dashboard_analytics(date, from_date, to_date, db)

    async def event_stream():
        extra_meta = {
            "date": label,
            "from_date": start_date,
            "to_date": end_date,
            "analytics_summary": analytics.get("meta", {}),
            "analytics_diagnostics": analytics.get("diagnostics", {}),
            "analytics_operating_context": analytics.get("operating_context", {}),
            "analytics_monthly": analytics.get("monthly_summary", []),
        }
        async for packet in generate_dashboard_stream_events(
            analytics,
            mode=selected_mode,
            extra_meta=extra_meta,
            hour_scope=selected_hour_scope,
            llm_model=llm_model,
        ):
            yield _sse_pack(packet["event"], packet["data"])

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse_pack(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _load_dashboard_analytics(
    date: str | None,
    from_date: str | None,
    to_date: str | None,
    db: AsyncIOMotorDatabase,
) -> tuple[str, dict, str, str]:
    label, start, end = _resolve_range(date, from_date, to_date)
    query = {
        "$or": [
            {"created_at": {"$gte": start, "$lte": end}},
            {"created_at": {"$exists": False}, "updated_at": {"$gte": start, "$lte": end}},
        ]
    }
    projection = {"status": 1, "totals": 1, "items": 1, "created_at": 1, "updated_at": 1, "paid_at": 1}
    orders = [doc async for doc in db.orders.find(query, projection)]
    analytics = build_report_analytics(orders, start.date().isoformat(), end.date().isoformat())
    return label, analytics, start.date().isoformat(), end.date().isoformat()

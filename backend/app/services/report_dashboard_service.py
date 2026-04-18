import asyncio
import json
import socket
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
import re
import time
from typing import Any, AsyncIterator
from urllib import error, request

from app.config import settings


TERMINAL_STATUSES = {"Paid", "Cancelled"}
ACTION_HINT_WORDS = {"focus", "reduce", "increase", "optimize", "promote", "improve", "watch", "review"}
IMPACT_LEVELS = {"low", "medium", "high"}
EFFORT_LEVELS = {"low", "medium", "high"}
TIME_HORIZONS = {"immediate", "this_week", "this_month"}
RISK_LEVELS = {"low", "medium", "high"}
OPERATING_START_HOUR = 15
OPERATING_END_HOUR = 21
OFF_WEEKDAY = 0  # Monday
OBSERVABILITY = {
    "requests_total": 0,
    "llm_requests_total": 0,
    "llm_success_total": 0,
    "fallback_total": 0,
    "schema_fallback_total": 0,
    "api_error_total": 0,
    "latency_total_ms": 0.0,
    "daily": {},
}


def _to_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_daily_bucket(day_key: str) -> dict[str, float]:
    daily = OBSERVABILITY["daily"]
    if day_key not in daily:
        daily[day_key] = {
            "llm_requests": 0,
            "llm_success": 0,
            "fallbacks": 0,
            "schema_fallbacks": 0,
            "api_errors": 0,
            "latency_ms": 0.0,
        }
    return daily[day_key]


def _observability_snapshot() -> dict[str, Any]:
    day_key = _today_key()
    _ensure_daily_bucket(day_key)
    return {
        "global": {
            "requests_total": int(OBSERVABILITY["requests_total"]),
            "llm_requests_total": int(OBSERVABILITY["llm_requests_total"]),
            "llm_success_total": int(OBSERVABILITY["llm_success_total"]),
            "fallback_total": int(OBSERVABILITY["fallback_total"]),
            "schema_fallback_total": int(OBSERVABILITY["schema_fallback_total"]),
            "api_error_total": int(OBSERVABILITY["api_error_total"]),
            "avg_latency_ms": round(
                (OBSERVABILITY["latency_total_ms"] / OBSERVABILITY["llm_requests_total"])
                if OBSERVABILITY["llm_requests_total"]
                else 0.0,
                2,
            ),
        },
        "today": {**OBSERVABILITY["daily"][day_key], "date": day_key},
    }


def _record_observability(
    *,
    latency_ms: float,
    fallback: bool,
    schema_fallback: bool,
    api_error: bool,
    llm_success: bool,
) -> None:
    day_key = _today_key()
    day_bucket = _ensure_daily_bucket(day_key)
    OBSERVABILITY["requests_total"] += 1
    OBSERVABILITY["llm_requests_total"] += 1
    OBSERVABILITY["latency_total_ms"] += latency_ms
    day_bucket["llm_requests"] += 1
    day_bucket["latency_ms"] += latency_ms
    if fallback:
        OBSERVABILITY["fallback_total"] += 1
        day_bucket["fallbacks"] += 1
    if schema_fallback:
        OBSERVABILITY["schema_fallback_total"] += 1
        day_bucket["schema_fallbacks"] += 1
    if api_error:
        OBSERVABILITY["api_error_total"] += 1
        day_bucket["api_errors"] += 1
    if llm_success:
        OBSERVABILITY["llm_success_total"] += 1
        day_bucket["llm_success"] += 1


def _pick_duration_end(order: dict[str, Any], status: str) -> datetime | None:
    paid_at = _to_utc_datetime(order.get("paid_at"))
    if paid_at:
        return paid_at
    if status in TERMINAL_STATUSES:
        return _to_utc_datetime(order.get("updated_at"))
    return None


def _is_within_operating_window(ts: datetime) -> bool:
    if ts.weekday() == OFF_WEEKDAY:
        return False
    return OPERATING_START_HOUR <= ts.hour < OPERATING_END_HOUR


def build_report_analytics(orders: list[dict[str, Any]], from_date: str, to_date: str) -> dict[str, Any]:
    status_counts: dict[str, int] = defaultdict(int)
    status_revenue: dict[str, float] = defaultdict(float)
    daily_orders: dict[str, int] = defaultdict(int)
    daily_revenue: dict[str, float] = defaultdict(float)
    monthly_orders: dict[str, int] = defaultdict(int)
    monthly_revenue: dict[str, float] = defaultdict(float)
    hourly_orders: dict[str, int] = defaultdict(int)
    operating_hourly_orders: dict[str, int] = defaultdict(int)
    item_demand: dict[str, int] = defaultdict(int)
    dwell_minutes: list[float] = []

    total_revenue = 0.0
    invalid_dwell = 0
    records_with_missing_created = 0
    orders_outside_operating_hours = 0
    orders_on_closed_day = 0

    for order in orders:
        status = str(order.get("status") or "Unknown")
        totals = order.get("totals") or {}
        order_total = _safe_float(totals.get("total"))
        total_revenue += order_total
        status_counts[status] += 1
        status_revenue[status] += order_total

        created_at = _to_utc_datetime(order.get("created_at"))
        updated_at = _to_utc_datetime(order.get("updated_at"))
        ts = created_at or updated_at
        if created_at is None:
            records_with_missing_created += 1
        if ts:
            day_key = ts.date().isoformat()
            month_key = ts.strftime("%Y-%m")
            daily_orders[day_key] += 1
            daily_revenue[day_key] += order_total
            monthly_orders[month_key] += 1
            monthly_revenue[month_key] += order_total
            hourly_orders[f"{ts.hour:02d}:00"] += 1
            if ts.weekday() == OFF_WEEKDAY:
                orders_on_closed_day += 1
            if _is_within_operating_window(ts):
                operating_hourly_orders[f"{ts.hour:02d}:00"] += 1
            else:
                orders_outside_operating_hours += 1

        for item in order.get("items") or []:
            if item.get("voided"):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            qty = int(_safe_float(item.get("qty"), default=1))
            item_demand[name] += max(qty, 1)

        start = created_at
        end = _pick_duration_end(order, status)
        if start and end:
            minutes = (end - start).total_seconds() / 60.0
            if minutes >= 0:
                dwell_minutes.append(round(minutes, 2))
            else:
                invalid_dwell += 1
        elif status in TERMINAL_STATUSES:
            invalid_dwell += 1

    sorted_item_demand = sorted(item_demand.items(), key=lambda row: (-row[1], row[0].lower()))
    lowest_item_demand = sorted(item_demand.items(), key=lambda row: (row[1], row[0].lower()))
    avg_order_value = round(total_revenue / len(orders), 2) if orders else 0.0
    avg_dwell = round(statistics.fmean(dwell_minutes), 2) if dwell_minutes else 0.0
    median_dwell = round(statistics.median(dwell_minutes), 2) if dwell_minutes else 0.0
    p90_dwell = round(statistics.quantiles(dwell_minutes, n=10)[-1], 2) if len(dwell_minutes) >= 10 else avg_dwell

    daily_orders_rows = [{"label": day, "value": count} for day, count in sorted(daily_orders.items())]
    daily_revenue_rows = [{"label": day, "value": round(amount, 2)} for day, amount in sorted(daily_revenue.items())]
    monthly_summary_rows = [
        {
            "month": month,
            "orders": count,
            "revenue": round(monthly_revenue[month], 2),
            "avg_order_value": round((monthly_revenue[month] / count), 2) if count else 0.0,
        }
        for month, count in sorted(monthly_orders.items())
    ]
    status_rows = [
        {"label": key, "count": value, "revenue": round(status_revenue[key], 2)}
        for key, value in sorted(status_counts.items(), key=lambda row: (-row[1], row[0]))
    ]
    deterministic_metrics = _build_deterministic_metrics(
        daily_orders_rows=daily_orders_rows,
        daily_revenue_rows=daily_revenue_rows,
        monthly_summary_rows=monthly_summary_rows,
        status_rows=status_rows,
        total_orders=len(orders),
        total_revenue=round(total_revenue, 2),
        dwell_minutes=dwell_minutes,
    )

    return {
        "meta": {
            "from_date": from_date,
            "to_date": to_date,
            "total_orders": len(orders),
            "total_revenue": round(total_revenue, 2),
            "avg_order_value": avg_order_value,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "status_breakdown": status_rows,
        "daily_orders": daily_orders_rows,
        "daily_revenue": daily_revenue_rows,
        "monthly_summary": monthly_summary_rows,
        "hourly_orders": [{"label": hour, "value": count} for hour, count in sorted(hourly_orders.items())],
        "hourly_orders_operating": [
            {"label": hour, "value": count} for hour, count in sorted(operating_hourly_orders.items())
        ],
        "top_items": [{"label": name, "value": count} for name, count in sorted_item_demand[:8]],
        "low_items": [{"label": name, "value": count} for name, count in lowest_item_demand[:8]],
        "dwell_time": {
            "count": len(dwell_minutes),
            "avg_minutes": avg_dwell,
            "median_minutes": median_dwell,
            "p90_minutes": p90_dwell,
            "distribution": _bucketize_dwell(dwell_minutes),
        },
        "diagnostics": {
            "missing_created_at": records_with_missing_created,
            "invalid_dwell_records": invalid_dwell,
            "items_tracked": len(item_demand),
            "orders_outside_operating_hours": orders_outside_operating_hours,
            "orders_on_closed_day": orders_on_closed_day,
        },
        "operating_context": {
            "open_days": ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "off_day": "Monday",
            "open_hours_local": "15:00-21:00",
        },
        "deterministic_metrics": deterministic_metrics,
    }


def _build_deterministic_metrics(
    daily_orders_rows: list[dict[str, Any]],
    daily_revenue_rows: list[dict[str, Any]],
    monthly_summary_rows: list[dict[str, Any]],
    status_rows: list[dict[str, Any]],
    total_orders: int,
    total_revenue: float,
    dwell_minutes: list[float],
) -> dict[str, Any]:
    prev_orders = sum(int(row.get("value") or 0) for row in daily_orders_rows[-14:-7]) if len(daily_orders_rows) >= 14 else 0
    curr_orders = sum(int(row.get("value") or 0) for row in daily_orders_rows[-7:])
    prev_revenue = (
        sum(float(row.get("value") or 0) for row in daily_revenue_rows[-14:-7]) if len(daily_revenue_rows) >= 14 else 0.0
    )
    curr_revenue = sum(float(row.get("value") or 0) for row in daily_revenue_rows[-7:])

    prev_aov = round(prev_revenue / prev_orders, 2) if prev_orders else 0.0
    curr_aov = round(curr_revenue / curr_orders, 2) if curr_orders else 0.0

    cancelled = next((int(row.get("count") or 0) for row in status_rows if row.get("label") == "Cancelled"), 0)
    paid = next((int(row.get("count") or 0) for row in status_rows if row.get("label") == "Paid"), 0)
    billed = next((int(row.get("count") or 0) for row in status_rows if row.get("label") == "Billed"), 0)

    cancellation_rate = round((cancelled / total_orders) * 100, 2) if total_orders else 0.0
    billed_or_paid = billed + paid
    billing_completion_rate = round((paid / billed_or_paid) * 100, 2) if billed_or_paid else 0.0
    long_stay_count = sum(1 for minute in dwell_minutes if minute > 60)
    high_dwell_share = round((long_stay_count / len(dwell_minutes)) * 100, 2) if dwell_minutes else 0.0

    recent_days = daily_revenue_rows[-7:]
    revenue_forecast_next_day = (
        round(sum(float(day.get("value") or 0) for day in recent_days) / len(recent_days), 2) if recent_days else 0.0
    )
    orders_recent = daily_orders_rows[-7:]
    orders_forecast_next_day = (
        round(sum(float(day.get("value") or 0) for day in orders_recent) / len(orders_recent), 2)
        if orders_recent
        else 0.0
    )

    latest_month = monthly_summary_rows[-1] if monthly_summary_rows else {"orders": 0, "revenue": 0}
    prev_month = monthly_summary_rows[-2] if len(monthly_summary_rows) >= 2 else {"orders": 0, "revenue": 0}

    return {
        "kpi_deltas": {
            "orders": {"current": curr_orders, "previous": prev_orders, "delta": curr_orders - prev_orders},
            "revenue": {
                "current": round(curr_revenue, 2),
                "previous": round(prev_revenue, 2),
                "delta": round(curr_revenue - prev_revenue, 2),
            },
            "avg_order_value": {
                "current": curr_aov,
                "previous": prev_aov,
                "delta": round(curr_aov - prev_aov, 2),
            },
            "cancellation_rate": {"current": cancellation_rate, "target_max": 8.0},
        },
        "trend_decomposition": {
            "daily": daily_revenue_rows[-7:],
            "weekly": [
                {"label": "Prev 7d", "value": round(prev_revenue, 2)},
                {"label": "Last 7d", "value": round(curr_revenue, 2)},
            ],
            "monthly": [
                {"label": str(prev_month.get("month") or "Prev"), "value": float(prev_month.get("revenue") or 0)},
                {"label": str(latest_month.get("month") or "Latest"), "value": float(latest_month.get("revenue") or 0)},
            ],
        },
        "sla_panel": {
            "high_dwell_share_pct": high_dwell_share,
            "billing_completion_rate_pct": billing_completion_rate,
            "cancellation_rate_pct": cancellation_rate,
            "alerts": {
                "high_dwell": high_dwell_share > 35,
                "billing_completion_low": billing_completion_rate < 80,
                "cancellation_high": cancellation_rate > 8,
            },
        },
        "forecast": {
            "next_day_revenue": revenue_forecast_next_day,
            "next_day_orders": orders_forecast_next_day,
            "next_week_revenue": round(revenue_forecast_next_day * 7, 2),
            "next_week_orders": round(orders_forecast_next_day * 7, 2),
            "method": "7-day moving average",
        },
        "summary": {"total_orders": total_orders, "total_revenue": total_revenue},
    }


def _bucketize_dwell(minutes: list[float]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {"0-15m": 0, "16-30m": 0, "31-45m": 0, "46-60m": 0, "60m+": 0}
    for minute in minutes:
        if minute <= 15:
            counts["0-15m"] += 1
        elif minute <= 30:
            counts["16-30m"] += 1
        elif minute <= 45:
            counts["31-45m"] += 1
        elif minute <= 60:
            counts["46-60m"] += 1
        else:
            counts["60m+"] += 1
    return [{"label": label, "value": counts[label]} for label in ["0-15m", "16-30m", "31-45m", "46-60m", "60m+"]]


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _analytics_for_llm_hour_scope(analytics: dict[str, Any], hour_scope: str) -> dict[str, Any]:
    scoped = dict(analytics)
    use_operating = hour_scope == "operating"
    all_hours = analytics.get("hourly_orders") or []
    operating_hours = analytics.get("hourly_orders_operating") or []
    scoped["hourly_orders_all"] = all_hours
    scoped["hourly_orders"] = operating_hours if use_operating else all_hours
    scoped["selected_hour_scope"] = "operating" if use_operating else "all"
    return scoped


def _resolve_llm_model(llm_model: str | None) -> str:
    raw = str(llm_model or "").strip()
    if not raw:
        return settings.gemini_model
    if re.fullmatch(r"[A-Za-z0-9._-]{3,80}", raw):
        return raw
    return settings.gemini_model


def _candidate_models(primary_model: str) -> list[str]:
    fallbacks = [
        row.strip()
        for row in str(settings.gemini_fallback_models or "").split(",")
        if row.strip() and re.fullmatch(r"[A-Za-z0-9._-]{3,80}", row.strip())
    ]
    chain = [primary_model, *fallbacks]
    deduped: list[str] = []
    seen: set[str] = set()
    for model in chain:
        if model in seen:
            continue
        deduped.append(model)
        seen.add(model)
    return deduped


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, error.URLError):
        reason = str(getattr(exc, "reason", "")).lower()
        return "timed out" in reason or "timeout" in reason
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def _is_retryable_http(code: int) -> bool:
    return code in {408, 429, 500, 502, 503, 504}


def _llm_prompt(analytics: dict[str, Any]) -> str:
    return (
        "You are a business analyst and data visualization planner for a cafe POS.\n"
        "Given the analytics JSON for the selected date range, reason step-by-step: summarize, diagnose, prioritize actions, then chart.\n"
        "First produce an analyst brief with grounded evidence, then chart blocks.\n"
        "Return STRICT JSON only with shape:\n"
        "{\n"
        '  "executive_summary":"string",\n'
        '  "root_cause_hypotheses":[\n'
        '    {\n'
        '      "title":"string",\n'
        '      "rationale":"string",\n'
        '      "risk_level":"low|medium|high",\n'
        '      "confidence":0.0,\n'
        '      "citations":[{"metric":"string","value":"string|number","source":"analytics.path"}]\n'
        "    }\n"
        "  ],\n"
        '  "prioritized_actions":[\n'
        '    {\n'
        '      "action":"string",\n'
        '      "impact":"low|medium|high",\n'
        '      "effort":"low|medium|high",\n'
        '      "time_horizon":"immediate|this_week|this_month",\n'
        '      "owner_hint":"string",\n'
        '      "success_metric":"string"\n'
        "    }\n"
        "  ],\n"
        '  "watchouts":["string"],\n'
        '  "key_insights":[\n'
        '    {\n'
        '      "text":"string with numbers and actionable recommendation",\n'
        '      "confidence":0.0,\n'
        '      "citations":[{"metric":"string","value":"string|number","source":"analytics.path"}]\n'
        "    }\n"
        "  ],\n"
        '  "drilldown_suggestion":{"dimension":"string","reason":"string","next_step":"string"},\n'
        '  "recommendations":[{"action":"string","assumption":"string","expected_impact_pct":0.0}],\n'
        '  "blocks":[\n'
        "    {\n"
        '      "id":"string",\n'
        '      "title":"string",\n'
        '      "insight_priority":1,\n'
        '      "chart_type":"kpi|bar|line|table|distribution|text",\n'
        '      "why_this_chart":"string",\n'
        '      "summary":"string",\n'
        '      "data":[{"label":"string","value":number}],\n'
        '      "anomaly":{"anomalyLabel":"string","anomalyIndex":0}\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- executive_summary must be 1 to 3 sentences in plain business language.\n"
        "- root_cause_hypotheses must contain 2 to 4 items with confidence and citations.\n"
        "- prioritized_actions must contain 2 to 5 items and should be sorted by value.\n"
        "- watchouts must contain 1 to 4 caveats about risk, uncertainty, or missing data.\n"
        "- Business context: cafe operates Tuesday-Sunday, 15:00 to 21:00; Monday is off.\n"
        "- If orders appear on Monday or outside 15:00-21:00, call this out explicitly in watchouts or hypotheses.\n"
        "- key_insights must contain 3 to 5 bullets.\n"
        "- Each key insight must reference concrete numbers from data.\n"
        "- Each key insight must be actionable, not purely descriptive.\n"
        "- confidence must be 0 to 1.\n"
        "- each key insight must include at least one citation object.\n"
        "- expected_impact_pct must be between -100 and 100.\n"
        "- Choose 4 to 6 blocks only.\n"
        "- Focus on actionable insights and demand/dwell patterns when available.\n"
        "- Keep labels short and clear.\n"
        "- Add anomaly object when a chart point is >2x mean of that chart values.\n"
        "- Omit anomaly field for charts without anomalies.\n"
        "- No markdown and no prose outside JSON.\n"
        f"Analytics JSON:\n{json.dumps(analytics, separators=(',', ':'))}"
    )


def _validate_key_insights(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("key_insights")
    if not isinstance(rows, list):
        return []
    insights: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        confidence = _safe_float(row.get("confidence"), default=-1)
        citations_raw = row.get("citations")
        citations: list[dict[str, Any]] = []
        if isinstance(citations_raw, list):
            for item in citations_raw[:5]:
                if not isinstance(item, dict):
                    continue
                metric = str(item.get("metric") or "").strip()
                value = item.get("value")
                source = str(item.get("source") or "").strip()
                if metric and source:
                    citations.append({"metric": metric, "value": value, "source": source})
        if text and 0 <= confidence <= 1 and citations:
            insights.append({"text": text, "confidence": round(confidence, 2), "citations": citations})
    return insights[:5]


def _enforce_key_insights(insights: list[dict[str, Any]], analytics: dict[str, Any]) -> list[dict[str, Any]]:
    checked: list[dict[str, Any]] = []
    for row in insights:
        text = str(row.get("text") or "")
        has_number = bool(re.search(r"\d", text))
        has_action_hint = any(word in text.lower() for word in ACTION_HINT_WORDS)
        if has_number and has_action_hint:
            checked.append(row)
    if len(checked) >= 3:
        return checked[:5]
    return _fallback_key_insights(analytics)


def _fallback_key_insights(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    meta = analytics.get("meta") or {}
    top_items = analytics.get("top_items") or []
    low_items = analytics.get("low_items") or []
    dwell = analytics.get("dwell_time") or {}
    status_rows = analytics.get("status_breakdown") or []
    top_status = status_rows[0] if status_rows else {"label": "Unknown", "count": 0}

    first_top_item = top_items[0] if top_items else {"label": "N/A", "value": 0}
    first_low_item = low_items[0] if low_items else {"label": "N/A", "value": 0}
    return [
        {
            "text": (
                f"Total revenue is {meta.get('total_revenue', 0)} across {meta.get('total_orders', 0)} orders; "
                "focus on improving average order value with combo suggestions."
            ),
            "confidence": 0.84,
            "citations": [
                {"metric": "total_revenue", "value": meta.get("total_revenue", 0), "source": "meta.total_revenue"},
                {"metric": "total_orders", "value": meta.get("total_orders", 0), "source": "meta.total_orders"},
            ],
        },
        {
            "text": (
                f"Top demand item is {first_top_item.get('label')} with {first_top_item.get('value')} orders; "
                "increase prep readiness and stock for peak periods."
            ),
            "confidence": 0.82,
            "citations": [
                {"metric": "top_item", "value": first_top_item.get("label"), "source": "top_items[0].label"},
                {"metric": "top_item_qty", "value": first_top_item.get("value"), "source": "top_items[0].value"},
            ],
        },
        {
            "text": (
                f"Lowest demand item is {first_low_item.get('label')} at {first_low_item.get('value')} orders; "
                "review menu placement or bundle strategy to improve movement."
            ),
            "confidence": 0.81,
            "citations": [
                {"metric": "low_item", "value": first_low_item.get("label"), "source": "low_items[0].label"},
                {"metric": "low_item_qty", "value": first_low_item.get("value"), "source": "low_items[0].value"},
            ],
        },
        {
            "text": (
                f"Most frequent status is {top_status.get('label')} with {top_status.get('count')} orders; "
                "optimize transition bottlenecks to improve throughput."
            ),
            "confidence": 0.79,
            "citations": [
                {"metric": "top_status", "value": top_status.get("label"), "source": "status_breakdown[0].label"},
                {"metric": "top_status_count", "value": top_status.get("count"), "source": "status_breakdown[0].count"},
            ],
        },
        {
            "text": (
                f"Median dwell time is {dwell.get('median_minutes', 0)} minutes (P90: {dwell.get('p90_minutes', 0)}); "
                "adjust seating turnover policies for long-stay periods."
            ),
            "confidence": 0.78,
            "citations": [
                {"metric": "dwell_median", "value": dwell.get("median_minutes", 0), "source": "dwell_time.median_minutes"},
                {"metric": "dwell_p90", "value": dwell.get("p90_minutes", 0), "source": "dwell_time.p90_minutes"},
            ],
        },
    ]


def _validate_drilldown_suggestion(payload: dict[str, Any]) -> dict[str, str] | None:
    row = payload.get("drilldown_suggestion")
    if not isinstance(row, dict):
        return None
    dimension = str(row.get("dimension") or "").strip()
    reason = str(row.get("reason") or "").strip()
    next_step = str(row.get("next_step") or "").strip()
    if dimension and reason and next_step:
        return {"dimension": dimension, "reason": reason, "next_step": next_step}
    return None


def _fallback_drilldown(analytics: dict[str, Any]) -> dict[str, str]:
    top_items = analytics.get("top_items") or []
    item = top_items[0].get("label") if top_items else "top-demand item"
    return {
        "dimension": "hourly_orders",
        "reason": f"{item} demand and dwell patterns need peak-hour confirmation.",
        "next_step": "Drill into hourly buckets and compare top demand items against cancellation spikes.",
    }


def _validate_recommendations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("recommendations")
    if not isinstance(rows, list):
        return []
    parsed: list[dict[str, Any]] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "").strip()
        assumption = str(row.get("assumption") or "").strip()
        impact = _safe_float(row.get("expected_impact_pct"), default=10.0)
        if action and assumption and -100 <= impact <= 100:
            parsed.append({"action": action, "assumption": assumption, "expected_impact_pct": round(impact, 2)})
    return parsed


def _fallback_recommendations(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    top_item = ((analytics.get("top_items") or [{"label": "top item"}])[0]).get("label", "top item")
    return [
        {
            "action": f"Prioritize {top_item} prep for peak windows.",
            "assumption": "Demand concentration remains similar next week.",
            "expected_impact_pct": 8.0,
        },
        {
            "action": "Bundle low-demand items with top sellers.",
            "assumption": "Bundle placement is applied at ordering touchpoints.",
            "expected_impact_pct": 5.0,
        },
    ]


def _validate_executive_summary(payload: dict[str, Any]) -> str | None:
    text = str(payload.get("executive_summary") or "").strip()
    if not text:
        return None
    sentences = [row.strip() for row in re.split(r"[.!?]+", text) if row.strip()]
    if 1 <= len(sentences) <= 3:
        return text
    return None


def _fallback_executive_summary(analytics: dict[str, Any]) -> str:
    meta = analytics.get("meta") or {}
    top_item = ((analytics.get("top_items") or [{"label": "N/A"}])[0]).get("label", "N/A")
    dwell = analytics.get("dwell_time") or {}
    return (
        f"In this range, the cafe processed {meta.get('total_orders', 0)} orders for {meta.get('total_revenue', 0)} revenue. "
        f"Demand is led by {top_item}, while dwell median is {dwell.get('median_minutes', 0)} minutes. "
        "Focus first on peak-hour readiness and bottleneck reduction."
    )


def _validate_root_cause_hypotheses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("root_cause_hypotheses")
    if not isinstance(rows, list):
        return []
    parsed: list[dict[str, Any]] = []
    for row in rows[:4]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        rationale = str(row.get("rationale") or "").strip()
        risk_level = str(row.get("risk_level") or "").strip().lower()
        confidence = _safe_float(row.get("confidence"), default=-1)
        citations_raw = row.get("citations")
        citations: list[dict[str, Any]] = []
        if isinstance(citations_raw, list):
            for item in citations_raw[:5]:
                if not isinstance(item, dict):
                    continue
                metric = str(item.get("metric") or "").strip()
                source = str(item.get("source") or "").strip()
                if metric and source:
                    citations.append({"metric": metric, "value": item.get("value"), "source": source})
        if title and rationale and risk_level in RISK_LEVELS and 0 <= confidence <= 1 and citations:
            parsed.append(
                {
                    "title": title,
                    "rationale": rationale,
                    "risk_level": risk_level,
                    "confidence": round(confidence, 2),
                    "citations": citations,
                }
            )
    return parsed


def _fallback_root_cause_hypotheses(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    status_rows = analytics.get("status_breakdown") or []
    top_status = status_rows[0] if status_rows else {"label": "Unknown", "count": 0}
    dwell = analytics.get("dwell_time") or {}
    top_item = ((analytics.get("top_items") or [{"label": "N/A", "value": 0}])[0])
    return [
        {
            "title": "Demand concentration may be driving service pressure",
            "rationale": (
                f"{top_item.get('label')} accounts for {top_item.get('value')} orders, which can create queue spikes "
                "if prep allocation is flat across menu items."
            ),
            "risk_level": "medium",
            "confidence": 0.8,
            "citations": [
                {"metric": "top_item", "value": top_item.get("label"), "source": "top_items[0].label"},
                {"metric": "top_item_qty", "value": top_item.get("value"), "source": "top_items[0].value"},
            ],
        },
        {
            "title": "Long dwell windows may reduce table turnover",
            "rationale": (
                f"Median dwell is {dwell.get('median_minutes', 0)} minutes and P90 is {dwell.get('p90_minutes', 0)}, "
                "which may constrain seat availability at peaks."
            ),
            "risk_level": "high",
            "confidence": 0.78,
            "citations": [
                {"metric": "dwell_median", "value": dwell.get("median_minutes", 0), "source": "dwell_time.median_minutes"},
                {"metric": "dwell_p90", "value": dwell.get("p90_minutes", 0), "source": "dwell_time.p90_minutes"},
            ],
        },
        {
            "title": "Status mix suggests transition friction",
            "rationale": (
                f"Most common status is {top_status.get('label')} ({top_status.get('count')} orders), "
                "indicating downstream stage throughput should be checked."
            ),
            "risk_level": "medium",
            "confidence": 0.74,
            "citations": [
                {"metric": "top_status", "value": top_status.get("label"), "source": "status_breakdown[0].label"},
                {"metric": "top_status_count", "value": top_status.get("count"), "source": "status_breakdown[0].count"},
            ],
        },
    ]


def _validate_prioritized_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("prioritized_actions")
    if not isinstance(rows, list):
        return []
    parsed: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "").strip()
        impact = str(row.get("impact") or "").strip().lower()
        effort = str(row.get("effort") or "").strip().lower()
        time_horizon = str(row.get("time_horizon") or "").strip().lower()
        owner_hint = str(row.get("owner_hint") or "").strip()
        success_metric = str(row.get("success_metric") or "").strip()
        if (
            action
            and impact in IMPACT_LEVELS
            and effort in EFFORT_LEVELS
            and time_horizon in TIME_HORIZONS
            and owner_hint
            and success_metric
        ):
            parsed.append(
                {
                    "action": action,
                    "impact": impact,
                    "effort": effort,
                    "time_horizon": time_horizon,
                    "owner_hint": owner_hint,
                    "success_metric": success_metric,
                }
            )
    score = {"high": 3, "medium": 2, "low": 1}
    parsed.sort(key=lambda row: (-(score.get(row["impact"], 1) - score.get(row["effort"], 1)), row["time_horizon"]))
    return parsed


def _fallback_prioritized_actions(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    top_item = ((analytics.get("top_items") or [{"label": "top item"}])[0]).get("label", "top item")
    return [
        {
            "action": f"Pre-batch mise-en-place for {top_item} in peak hours.",
            "impact": "high",
            "effort": "medium",
            "time_horizon": "immediate",
            "owner_hint": "Shift supervisor",
            "success_metric": "Reduce average prep delay by 10% during top 2 hours.",
        },
        {
            "action": "Bundle one low-demand item with top sellers at checkout.",
            "impact": "medium",
            "effort": "low",
            "time_horizon": "this_week",
            "owner_hint": "Menu manager",
            "success_metric": "Increase low-demand item sales by 8% week-over-week.",
        },
        {
            "action": "Review long-stay windows and introduce subtle turnover nudges.",
            "impact": "medium",
            "effort": "medium",
            "time_horizon": "this_month",
            "owner_hint": "Floor operations lead",
            "success_metric": "Reduce P90 dwell by 5 minutes without lowering satisfaction.",
        },
    ]


def _validate_watchouts(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("watchouts")
    if not isinstance(rows, list):
        return []
    parsed: list[str] = []
    for row in rows[:4]:
        text = str(row or "").strip()
        if text:
            parsed.append(text)
    return parsed


def _fallback_watchouts(analytics: dict[str, Any]) -> list[str]:
    diagnostics = analytics.get("diagnostics") or {}
    watchouts = []
    if diagnostics.get("missing_created_at"):
        watchouts.append("Some records have missing created time; trend precision may be slightly reduced.")
    if diagnostics.get("invalid_dwell_records"):
        watchouts.append("Some dwell samples are invalid; long-stay interpretation may be conservative.")
    if diagnostics.get("orders_on_closed_day"):
        watchouts.append("Orders were recorded on Monday (configured off day); verify staffing/schedule exceptions.")
    if diagnostics.get("orders_outside_operating_hours"):
        watchouts.append("Some orders were outside 15:00-21:00 operating hours; confirm special openings or data timing.")
    watchouts.append("Range-level analysis does not capture external events (weather, promotions, holidays).")
    return watchouts[:4]


def _validate_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("blocks")
    if not isinstance(rows, list):
        return []
    valid: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        chart_type = str(row.get("chart_type") or "table")
        title = str(row.get("title") or f"Insight {idx + 1}").strip()
        summary = str(row.get("summary") or "").strip()
        why = str(row.get("why_this_chart") or "").strip()
        priority = int(_safe_float(row.get("insight_priority"), default=idx + 1))
        raw_data = row.get("data") if isinstance(row.get("data"), list) else []
        parsed_data = []
        for point in raw_data:
            if not isinstance(point, dict):
                continue
            label = str(point.get("label") or "").strip()
            if not label:
                continue
            parsed_data.append({"label": label, "value": round(_safe_float(point.get("value")), 2)})
        anomaly_raw = row.get("anomaly")
        anomaly = None
        if isinstance(anomaly_raw, dict):
            anomaly_label = str(anomaly_raw.get("anomalyLabel") or "").strip()
            anomaly_index = int(_safe_float(anomaly_raw.get("anomalyIndex"), default=-1))
            if anomaly_label and 0 <= anomaly_index < len(parsed_data):
                anomaly = {"anomalyLabel": anomaly_label, "anomalyIndex": anomaly_index}
        block = {
            "id": str(row.get("id") or f"insight-{idx + 1}"),
            "title": title,
            "insight_priority": priority,
            "chart_type": chart_type,
            "why_this_chart": why,
            "summary": summary,
            "data": parsed_data,
        }
        if anomaly:
            block["anomaly"] = anomaly
        valid.append(block)
    valid.sort(key=lambda block: block.get("insight_priority", 99))
    return valid[:8]


def _default_blocks(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    meta = analytics.get("meta") or {}
    dwell = analytics.get("dwell_time") or {}
    return [
        {
            "id": "kpi-orders-revenue",
            "title": "Orders and Revenue",
            "insight_priority": 1,
            "chart_type": "kpi",
            "why_this_chart": "Fast snapshot of business volume and value.",
            "summary": f"Orders: {meta.get('total_orders', 0)} | Revenue: {meta.get('total_revenue', 0)}",
            "data": [
                {"label": "Orders", "value": _safe_float(meta.get("total_orders"))},
                {"label": "Revenue", "value": _safe_float(meta.get("total_revenue"))},
                {"label": "Avg Order Value", "value": _safe_float(meta.get("avg_order_value"))},
            ],
        },
        {
            "id": "status-breakdown",
            "title": "Order Status Mix",
            "insight_priority": 2,
            "chart_type": "bar",
            "why_this_chart": "Compares operational throughput by status.",
            "summary": "Status counts across selected range.",
            "data": [{"label": row["label"], "value": row["count"]} for row in (analytics.get("status_breakdown") or [])],
        },
        {
            "id": "top-demand-items",
            "title": "Most Demanded Items",
            "insight_priority": 3,
            "chart_type": "bar",
            "why_this_chart": "Ranks item demand for inventory and menu decisions.",
            "summary": "Top selling non-voided items by quantity.",
            "data": analytics.get("top_items") or [],
        },
        {
            "id": "least-demand-items",
            "title": "Least Demanded Items",
            "insight_priority": 4,
            "chart_type": "table",
            "why_this_chart": "Highlights candidates for menu rethink.",
            "summary": "Low movement items by quantity.",
            "data": analytics.get("low_items") or [],
        },
        {
            "id": "dwell-distribution",
            "title": "Customer Time Spent",
            "insight_priority": 5,
            "chart_type": "distribution",
            "why_this_chart": "Shows dwell-time spread to optimize seating turnover.",
            "summary": (
                f"Avg: {dwell.get('avg_minutes', 0)} mins | "
                f"Median: {dwell.get('median_minutes', 0)} mins | "
                f"P90: {dwell.get('p90_minutes', 0)} mins"
            ),
            "data": dwell.get("distribution") or [],
        },
    ]


def _render_data_table(data: list[dict[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td>{escape(str(point['label']))}</td><td>{escape(str(point['value']))}</td></tr>" for point in data[:20]
    )
    return (
        "<div class='ai-block-table-wrap'><table class='ai-block-table'>"
        "<thead><tr><th>Label</th><th>Value</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _render_bar(data: list[dict[str, Any]], anomaly: dict[str, Any] | None = None) -> str:
    if not data:
        return "<div class='ai-block-empty'>No chart data.</div>"
    peak = max(point.get("value", 0) for point in data) or 1
    anomaly_index = int(_safe_float((anomaly or {}).get("anomalyIndex"), default=-1))
    anomaly_label = str((anomaly or {}).get("anomalyLabel") or "").strip()
    bars = []
    for idx, point in enumerate(data[:12]):
        ratio = max(min((_safe_float(point.get("value")) / peak) * 100.0, 100.0), 0.0)
        anomaly_badge = (
            f"<span class='ai-anomaly-badge'>{escape(anomaly_label)}</span>" if anomaly_label and anomaly_index == idx else ""
        )
        bars.append(
            "<div class='ai-bar-row'>"
            f"<span class='ai-bar-label'>{escape(str(point['label']))}</span>"
            f"<div class='ai-bar-track'><div class='ai-bar-fill' style='width:{ratio:.1f}%'></div></div>"
            f"<span class='ai-bar-value'>{escape(str(point['value']))}</span>"
            f"{anomaly_badge}"
            "</div>"
        )
    return "".join(bars)


def _render_block_content(chart_type: str, data: list[dict[str, Any]], anomaly: dict[str, Any] | None = None) -> str:
    if chart_type in {"bar", "line", "distribution"}:
        return f"<div class='ai-bars'>{_render_bar(data, anomaly=anomaly)}</div>"
    if chart_type == "kpi":
        chips = "".join(
            (
                "<div class='ai-kpi-card'>"
                f"<span>{escape(str(point['label']))}</span>"
                f"<strong>{escape(str(point['value']))}</strong>"
                "</div>"
            )
            for point in data[:4]
        )
        return f"<div class='ai-kpi-grid'>{chips}</div>"
    return _render_data_table(data)


def _render_html(
    blocks: list[dict[str, Any]], generated_at: str, key_insights: list[dict[str, Any]] | None = None
) -> tuple[str, list[dict[str, Any]]]:
    rendered_blocks: list[dict[str, Any]] = []
    html_parts = [f"<div class='ai-report-root'><div class='ai-report-meta'>Generated: {escape(generated_at)}</div>"]
    if key_insights:
        insight_items = "".join(
            f"<li>{escape(str(item.get('text') or ''))}</li>" for item in key_insights if item.get("text")
        )
        html_parts.append(
            "<section class='ai-report-block ai-key-insights'>"
            "<h4>Key Insights</h4>"
            f"<ul>{insight_items}</ul>"
            "</section>"
        )
    for block in blocks:
        content = _render_block_content(
            block.get("chart_type", "table"),
            block.get("data", []),
            anomaly=block.get("anomaly") if isinstance(block.get("anomaly"), dict) else None,
        )
        why = block.get("why_this_chart") or ""
        section_html = (
            "<section class='ai-report-block'>"
            f"<h4>{escape(block.get('title', 'Insight'))}</h4>"
            f"<p class='ai-block-summary'>{escape(block.get('summary', ''))}</p>"
            f"{content}"
            f"<p class='ai-block-why'>Why this chart: {escape(why)}</p>"
            "</section>"
        )
        next_block = {**block, "html": section_html}
        rendered_blocks.append(next_block)
        html_parts.append(section_html)
    html_parts.append("</div>")
    return "".join(html_parts), rendered_blocks


async def _call_gemini_for_blocks(
    analytics: dict[str, Any], mode: str, hour_scope: str = "all", llm_model: str | None = None
) -> tuple[
    list[dict[str, Any]],
    list[str],
    dict[str, int],
    dict[str, Any],
    str,
    list[dict[str, Any]],
    dict[str, str] | None,
    list[dict[str, Any]],
    str,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    dict[str, Any],
    dict[str, Any],
]:
    selected_model = _resolve_llm_model(llm_model)
    if mode == "deterministic":
        return (
            _default_blocks(analytics),
            ["Deterministic mode selected."],
            {},
            {},
            "deterministic",
            [],
            None,
            [],
            "",
            [],
            [],
            [],
            {
                "used_fallback": False,
                "schema_fallback": False,
                "api_error": False,
                "grounded_insights": True,
                "attempted_models": [],
                "failover_used": False,
            },
            _observability_snapshot(),
        )

    if not settings.gemini_api_key:
        _record_observability(
            latency_ms=0.0,
            fallback=True,
            schema_fallback=True,
            api_error=False,
            llm_success=False,
        )
        return (
            _default_blocks(analytics),
            ["Gemini API key missing. Used deterministic dashboard fallback."],
            {},
            {},
            selected_model,
            _fallback_key_insights(analytics),
            _fallback_drilldown(analytics),
            _fallback_recommendations(analytics),
            _fallback_executive_summary(analytics),
            _fallback_root_cause_hypotheses(analytics),
            _fallback_prioritized_actions(analytics),
            _fallback_watchouts(analytics),
            {
                "used_fallback": True,
                "schema_fallback": True,
                "api_error": False,
                "grounded_insights": False,
                "has_executive_summary": True,
                "has_root_causes": True,
                "has_prioritized_actions": True,
                "attempted_models": [selected_model],
                "failover_used": False,
            },
            _observability_snapshot(),
        )

    scoped_analytics = _analytics_for_llm_hour_scope(analytics, hour_scope)
    base_payload = {
        "contents": [{"parts": [{"text": _llm_prompt(scoped_analytics)}]}],
        "generationConfig": {"temperature": 0.25},
    }
    headers = {"Content-Type": "application/json", "X-goog-api-key": settings.gemini_api_key}

    def _run(model_name: str) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent"
        )
        body = json.dumps(base_payload).encode("utf-8")
        req = request.Request(url, data=body, headers=headers, method="POST")
        with request.urlopen(req, timeout=settings.gemini_timeout_seconds) as response:
            return response.read().decode("utf-8")

    diagnostics: list[str] = []
    usage: dict[str, int] = {}
    cost_estimate: dict[str, Any] = {}
    key_insights: list[dict[str, Any]] = []
    drilldown_suggestion: dict[str, str] | None = None
    recommendations: list[dict[str, Any]] = []
    executive_summary = ""
    root_cause_hypotheses: list[dict[str, Any]] = []
    prioritized_actions: list[dict[str, Any]] = []
    watchouts: list[str] = []
    start = time.perf_counter()
    used_fallback = False
    schema_fallback = False
    api_error = False
    llm_success = False
    retry_attempts = max(int(settings.gemini_retry_attempts), 0)
    backoff_seconds = max(int(settings.gemini_retry_backoff_ms), 0) / 1000.0
    attempted_models = _candidate_models(selected_model)
    attempted_history: list[str] = []
    resolved_model = selected_model
    for model_name in attempted_models:
        resolved_model = model_name
        attempted_history.append(model_name)
        for attempt in range(retry_attempts + 1):
            try:
                raw_response = await asyncio.to_thread(_run, model_name)
                parsed = json.loads(raw_response)
                usage = _extract_usage(parsed)
                cost_estimate = _estimate_cost(usage)
                parts = (((parsed.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
                text = "".join(str(part.get("text") or "") for part in parts)
                structured = _extract_json_payload(text)
                fallback_key_insights = _fallback_key_insights(analytics)
                validated_key_insights = _validate_key_insights(structured)
                key_insights = _enforce_key_insights(validated_key_insights, analytics)
                validated_drilldown = _validate_drilldown_suggestion(structured)
                drilldown_suggestion = validated_drilldown or _fallback_drilldown(analytics)
                validated_recommendations = _validate_recommendations(structured)
                recommendations = validated_recommendations or _fallback_recommendations(analytics)
                validated_executive_summary = _validate_executive_summary(structured)
                executive_summary = validated_executive_summary or _fallback_executive_summary(analytics)
                validated_root_causes = _validate_root_cause_hypotheses(structured)
                root_cause_hypotheses = validated_root_causes or _fallback_root_cause_hypotheses(analytics)
                validated_prioritized_actions = _validate_prioritized_actions(structured)
                prioritized_actions = validated_prioritized_actions or _fallback_prioritized_actions(analytics)
                validated_watchouts = _validate_watchouts(structured)
                watchouts = validated_watchouts or _fallback_watchouts(analytics)
                blocks = _validate_blocks(structured)
                insights_schema_fallback = key_insights == fallback_key_insights
                drilldown_schema_fallback = validated_drilldown is None
                recommendations_schema_fallback = not bool(validated_recommendations)
                executive_summary_schema_fallback = validated_executive_summary is None
                root_causes_schema_fallback = not bool(validated_root_causes)
                actions_schema_fallback = not bool(validated_prioritized_actions)
                watchouts_schema_fallback = not bool(validated_watchouts)
                schema_fallback = (
                    insights_schema_fallback
                    or drilldown_schema_fallback
                    or recommendations_schema_fallback
                    or executive_summary_schema_fallback
                    or root_causes_schema_fallback
                    or actions_schema_fallback
                    or watchouts_schema_fallback
                )
                if not blocks:
                    schema_fallback = True
                    used_fallback = True
                    diagnostics.append("Gemini output failed schema validation. Used fallback blocks.")
                    blocks = _default_blocks(analytics)
                llm_success = True
                quality_flags = {
                    "used_fallback": used_fallback,
                    "schema_fallback": schema_fallback,
                    "api_error": False,
                    "grounded_insights": not insights_schema_fallback,
                    "has_executive_summary": bool(executive_summary),
                    "has_root_causes": bool(root_cause_hypotheses),
                    "has_prioritized_actions": bool(prioritized_actions),
                    "attempted_models": attempted_history,
                    "failover_used": len(attempted_history) > 1,
                }
                latency_ms = (time.perf_counter() - start) * 1000
                _record_observability(
                    latency_ms=latency_ms,
                    fallback=used_fallback,
                    schema_fallback=schema_fallback,
                    api_error=False,
                    llm_success=llm_success,
                )
                return (
                    blocks,
                    diagnostics,
                    usage,
                    cost_estimate,
                    model_name,
                    key_insights,
                    drilldown_suggestion,
                    recommendations,
                    executive_summary,
                    root_cause_hypotheses,
                    prioritized_actions,
                    watchouts,
                    quality_flags,
                    _observability_snapshot(),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                diagnostics.append(
                    f"Gemini parse error on {model_name} attempt {attempt + 1}/{retry_attempts + 1}: {exc}."
                )
                if attempt < retry_attempts:
                    await asyncio.sleep(backoff_seconds)
                    continue
                schema_fallback = True
                used_fallback = True
                break
            except error.HTTPError as exc:
                diagnostics.append(
                    f"Gemini API HTTP error {exc.code} on {model_name} attempt {attempt + 1}/{retry_attempts + 1}."
                )
                api_error = True
                if _is_retryable_http(exc.code) and attempt < retry_attempts:
                    await asyncio.sleep(backoff_seconds)
                    continue
                used_fallback = True
                break
            except Exception as exc:  # noqa: BLE001
                diagnostics.append(
                    f"Gemini request error on {model_name} attempt {attempt + 1}/{retry_attempts + 1}: {exc}."
                )
                api_error = True
                if _is_timeout_error(exc) and attempt < retry_attempts:
                    await asyncio.sleep(backoff_seconds)
                    continue
                used_fallback = True
                break
    diagnostics.append("All configured models failed; used deterministic fallback blocks.")
    latency_ms = (time.perf_counter() - start) * 1000
    _record_observability(
        latency_ms=latency_ms,
        fallback=used_fallback,
        schema_fallback=schema_fallback,
        api_error=api_error,
        llm_success=False,
    )
    return (
        _default_blocks(analytics),
        diagnostics,
        usage,
        cost_estimate,
        resolved_model,
        _fallback_key_insights(analytics),
        _fallback_drilldown(analytics),
        _fallback_recommendations(analytics),
        _fallback_executive_summary(analytics),
        _fallback_root_cause_hypotheses(analytics),
        _fallback_prioritized_actions(analytics),
        _fallback_watchouts(analytics),
        {
            "used_fallback": True,
            "schema_fallback": True,
            "api_error": api_error,
            "grounded_insights": False,
            "has_executive_summary": True,
            "has_root_causes": True,
            "has_prioritized_actions": True,
            "attempted_models": attempted_history or [resolved_model],
            "failover_used": len(attempted_history) > 1,
        },
        _observability_snapshot(),
    )


def _extract_usage(parsed: dict[str, Any]) -> dict[str, int]:
    usage = parsed.get("usageMetadata") or {}
    return {
        "prompt_tokens": int(usage.get("promptTokenCount") or 0),
        "candidate_tokens": int(usage.get("candidatesTokenCount") or 0),
        "thought_tokens": int(usage.get("thoughtsTokenCount") or 0),
        "total_tokens": int(usage.get("totalTokenCount") or 0),
    }


def _estimate_cost(usage: dict[str, int]) -> dict[str, Any]:
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    candidate_tokens = int(usage.get("candidate_tokens") or 0)
    thought_tokens = int(usage.get("thought_tokens") or 0)
    billable_output_tokens = candidate_tokens + thought_tokens if settings.gemini_bill_thoughts_tokens else candidate_tokens

    input_cost = (prompt_tokens / 1_000_000) * settings.gemini_input_cost_per_million_usd
    output_cost = (billable_output_tokens / 1_000_000) * settings.gemini_output_cost_per_million_usd
    total_cost = input_cost + output_cost
    return {
        "currency": "USD",
        "input_cost": round(input_cost, 8),
        "output_cost": round(output_cost, 8),
        "total_cost": round(total_cost, 8),
        "billable_output_tokens": billable_output_tokens,
        "cost_model": {
            "input_per_million": settings.gemini_input_cost_per_million_usd,
            "output_per_million": settings.gemini_output_cost_per_million_usd,
            "bill_thoughts_tokens": settings.gemini_bill_thoughts_tokens,
        },
    }


async def generate_dashboard_payload(
    analytics: dict[str, Any], mode: str = "deterministic", hour_scope: str = "all", llm_model: str | None = None
) -> dict[str, Any]:
    (
        blocks,
        diagnostics,
        usage,
        cost_estimate,
        resolved_model,
        key_insights,
        drilldown_suggestion,
        recommendations,
        executive_summary,
        root_cause_hypotheses,
        prioritized_actions,
        watchouts,
        quality_flags,
        observability,
    ) = await _call_gemini_for_blocks(analytics, mode, hour_scope=hour_scope, llm_model=llm_model)
    generated_at = (analytics.get("meta") or {}).get("generated_at") or datetime.now(timezone.utc).isoformat()
    html, rendered_blocks = _render_html(blocks, generated_at, key_insights=key_insights if mode == "llm" else [])
    return {
        "generated_at": generated_at,
        "key_insights": key_insights if mode == "llm" else [],
        "drilldown_suggestion": drilldown_suggestion if mode == "llm" else None,
        "recommendations": recommendations if mode == "llm" else [],
        "executive_summary": executive_summary if mode == "llm" else "",
        "root_cause_hypotheses": root_cause_hypotheses if mode == "llm" else [],
        "prioritized_actions": prioritized_actions if mode == "llm" else [],
        "watchouts": watchouts if mode == "llm" else [],
        "blocks": rendered_blocks,
        "html": html,
        "diagnostics": diagnostics,
        "token_usage": usage,
        "estimated_cost": cost_estimate,
        "quality_flags": quality_flags if mode == "llm" else {},
        "observability": observability if mode == "llm" else {},
        "mode": mode,
        "model": resolved_model,
        "selected_llm_model": _resolve_llm_model(llm_model) if mode == "llm" else "",
        "hour_scope": hour_scope if mode == "llm" else "all",
    }


async def generate_dashboard_stream_events(
    analytics: dict[str, Any],
    mode: str = "llm",
    extra_meta: dict[str, Any] | None = None,
    hour_scope: str = "all",
    llm_model: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    (
        blocks,
        diagnostics,
        usage,
        cost_estimate,
        resolved_model,
        key_insights,
        drilldown_suggestion,
        recommendations,
        executive_summary,
        root_cause_hypotheses,
        prioritized_actions,
        watchouts,
        quality_flags,
        observability,
    ) = await _call_gemini_for_blocks(analytics, mode, hour_scope=hour_scope, llm_model=llm_model)
    generated_at = (analytics.get("meta") or {}).get("generated_at") or datetime.now(timezone.utc).isoformat()

    meta_payload = {
        **(extra_meta or {}),
        "generated_at": generated_at,
        "mode": mode,
        "model": resolved_model,
        "selected_llm_model": _resolve_llm_model(llm_model) if mode == "llm" else "",
        "hour_scope": hour_scope if mode == "llm" else "all",
        "expected_charts": len(blocks),
        "diagnostics": diagnostics,
        "token_usage": usage,
        "estimated_cost": cost_estimate,
        "quality_flags": quality_flags,
        "observability": observability,
    }
    yield {
        "event": "meta",
        "data": meta_payload,
    }

    if mode == "llm":
        yield {
            "event": "key_insights",
            "data": {
                "items": key_insights,
                "drilldown_suggestion": drilldown_suggestion,
                "recommendations": recommendations,
                "executive_summary": executive_summary,
                "root_cause_hypotheses": root_cause_hypotheses,
                "prioritized_actions": prioritized_actions,
                "watchouts": watchouts,
            },
        }

    for block in blocks:
        content = _render_block_content(
            block.get("chart_type", "table"),
            block.get("data", []),
            anomaly=block.get("anomaly") if isinstance(block.get("anomaly"), dict) else None,
        )
        section_html = (
            "<section class='ai-report-block'>"
            f"<h4>{escape(block.get('title', 'Insight'))}</h4>"
            f"<p class='ai-block-summary'>{escape(block.get('summary', ''))}</p>"
            f"{content}"
            f"<p class='ai-block-why'>Why this chart: {escape(str(block.get('why_this_chart') or ''))}</p>"
            "</section>"
        )
        yield {"event": "chart", "data": {"block": {**block, "html": section_html}}}

    yield {"event": "complete", "data": {"ok": True}}

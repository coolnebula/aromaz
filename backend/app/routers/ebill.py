from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.schemas import EBillEmailRequest, EBillSmsRequest
from app.security import sign_ebill_token, verify_ebill_token
from app.services.order_service import add_audit, bill_amounts_for_ebill, get_order_or_none
from app.services.email_service import EmailDeliveryError, mask_email, send_ebill_email
from app.services.sms_service import SmsDeliveryError, mask_mobile, send_ebill_sms
from app.config import settings


router = APIRouter(prefix="/ebill", tags=["ebill"])
public_router = APIRouter(prefix="/ebill", tags=["ebill-public"])


def _active_bill_items(order: dict) -> list[dict]:
    return [item for item in order.get("items", []) if not item.get("voided")]


def _render_bill_html(order: dict) -> str:
    items = _active_bill_items(order)
    totals = bill_amounts_for_ebill(order)
    created = order.get("created_at")
    if isinstance(created, datetime):
        created_utc = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        created_label = created_utc.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")
    else:
        created_label = "-"
    item_rows = ""
    for item in items:
        qty = int(item.get("qty") or 1)
        price = float(item.get("price") or 0)
        line_total = qty * price
        note = escape((item.get("modifiers") or {}).get("note", "") or "")
        name = escape(item.get("name", "Item"))
        note_line = f"<div class='muted'>Note: {note}</div>" if note else ""
        item_rows += (
            f"<div class='item'><div><strong>{name}</strong><div class='muted'>{qty} x ₹{price:.2f}</div>{note_line}</div>"
            f"<strong>₹{line_total:.2f}</strong></div>"
        )

    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Aromaz e-bill</title>
    <style>
      body {{ font-family: "Segoe UI", sans-serif; margin: 0; background: #f5f0ea; color: #2e251e; }}
      .sheet {{ max-width: 460px; margin: 20px auto; background: #fff; border: 1px solid #e9dfd3; border-radius: 10px; padding: 14px; }}
      .head {{ text-align: center; border-bottom: 1px dashed #d9cbbb; padding-bottom: 8px; margin-bottom: 8px; }}
      .muted {{ color: #6d6055; font-size: 0.86rem; }}
      .item {{ display: flex; justify-content: space-between; gap: 8px; border-bottom: 1px dotted #ddcfbe; padding: 8px 0; }}
      .totals {{ margin-top: 10px; border-top: 1px dashed #d9cbbb; padding-top: 8px; }}
      .row {{ display: flex; justify-content: space-between; margin: 3px 0; }}
    </style>
  </head>
  <body>
    <section class="sheet">
      <div class="head">
        <h2 style="margin:0;">Aromaz Cafe</h2>
        <div class="muted">Itemized e-bill</div>
        <div class="muted">Table {escape(order.get("table_id", "-"))}</div>
        <div class="muted">Order {escape(str(order.get("id", "-")))}</div>
        <div class="muted">Created {escape(created_label)}</div>
      </div>
      {item_rows if item_rows else "<div class='muted'>No billable items.</div>"}
      <div class="totals">
        <div class="row"><span>Subtotal</span><strong>₹{totals['subtotal']:.2f}</strong></div>
        {f"<div class='row'><span>Discount</span><strong>-₹{totals['discount']:.2f}</strong></div>" if totals.get('discount', 0) > 0 else ""}
        {f"<div class='row'><span>Tax</span><strong>₹{totals['tax']:.2f}</strong></div>" if totals.get('tax', 0) > 0 else ""}
        <div class="row"><span>Total</span><strong>₹{totals['total']:.2f}</strong></div>
      </div>
      <div class="muted" style="text-align:center;margin-top:10px;">Contact: 9051584252</div>
    </section>
  </body>
</html>"""


@router.post("/sms/{order_id}")
async def send_ebill_sms_route(
    order_id: str,
    payload: EBillSmsRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") not in {"Served", "Billed", "Paid"}:
        raise HTTPException(status_code=400, detail="E-bill can be sent only for Served/Billed/Paid orders")

    token = sign_ebill_token(order_id)
    base = settings.ebill_public_base_url.strip() or str(request.base_url).rstrip("/")
    ebill_url = f"{base.rstrip('/')}/ebill/{token}"
    try:
        result = await send_ebill_sms(payload.mobile, ebill_url)
    except SmsDeliveryError as exc:
        await add_audit(
            db,
            "EBILL_SMS_FAILED",
            payload.actor_id,
            {"order_id": order_id, "mobile_masked": mask_mobile(payload.mobile), "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await add_audit(
        db,
        "EBILL_SMS_SENT",
        payload.actor_id,
        {"order_id": order_id, "mobile_masked": mask_mobile(payload.mobile), "provider": result["provider"]},
    )
    return {"ok": True, "ebill_url": ebill_url, "mobile_masked": mask_mobile(result["to_mobile"]), "provider": result["provider"]}


@router.post("/email/{order_id}")
async def send_ebill_email_route(
    order_id: str,
    payload: EBillEmailRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    order = await get_order_or_none(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") not in {"Served", "Billed", "Paid"}:
        raise HTTPException(status_code=400, detail="E-bill can be sent only for Served/Billed/Paid orders")

    token = sign_ebill_token(order_id)
    base = settings.ebill_public_base_url.strip() or str(request.base_url).rstrip("/")
    ebill_url = f"{base.rstrip('/')}/ebill/{token}"
    try:
        result = await send_ebill_email(payload.email, ebill_url, order)
    except EmailDeliveryError as exc:
        await add_audit(
            db,
            "EBILL_EMAIL_FAILED",
            payload.actor_id,
            {"order_id": order_id, "email_masked": mask_email(payload.email), "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await add_audit(
        db,
        "EBILL_EMAIL_SENT",
        payload.actor_id,
        {"order_id": order_id, "email_masked": mask_email(result["to_email"]), "provider": result["provider"]},
    )
    return {"ok": True, "ebill_url": ebill_url, "email_masked": mask_email(result["to_email"]), "provider": result["provider"]}


@public_router.get("/{token}")
async def get_public_ebill(token: str, db: AsyncIOMotorDatabase = Depends(get_db)) -> HTMLResponse:
    payload = verify_ebill_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired e-bill link")
    order = await get_order_or_none(db, payload["order_id"])
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    html = _render_bill_html(order)
    return HTMLResponse(content=html)

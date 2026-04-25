import asyncio
from datetime import datetime, timezone
from html import escape
import smtplib
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.order_service import bill_amounts_for_ebill


class EmailDeliveryError(Exception):
    pass


def _normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not value or "@" not in value:
        raise EmailDeliveryError("Invalid email address.")
    local, _, domain = value.partition("@")
    if not local or "." not in domain:
        raise EmailDeliveryError("Invalid email address.")
    return value


def _send_smtp_sync(to_email: str, subject: str, html: str) -> dict:
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password or not settings.smtp_from_email:
        raise EmailDeliveryError(
            "SMTP configuration missing. Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL."
        )
    msg = EmailMessage()
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content("Your e-bill is ready. Open HTML-enabled view to see full bill.")
    msg.add_alternative(html, subtype="html")

    port = int(settings.smtp_port)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, port, timeout=10) as server:
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
    except smtplib.SMTPException as exc:
        raise EmailDeliveryError(f"SMTP send failed: {exc}") from exc
    return {"status_code": 202, "provider": "smtp"}


def _build_bill_email_html(order: dict, ebill_url: str) -> str:
    items = [item for item in order.get("items", []) if not item.get("voided")]
    created_at = order.get("created_at")
    if isinstance(created_at, datetime):
        created_utc = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        created_label = created_utc.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")
    else:
        created_label = "-"

    item_rows = []
    for item in items:
        qty = int(item.get("qty") or 1)
        price = float(item.get("price") or 0)
        line_total = qty * price
        note = escape(((item.get("modifiers") or {}).get("note") or "").strip())
        note_line = f"<div style='color:#7a6a5d;font-size:12px;margin-top:2px'>Note: {note}</div>" if note else ""
        item_rows.append(
            "<tr>"
            "<td style='padding:10px 0;border-bottom:1px solid #eee4d8'>"
            f"<div style='font-weight:700;color:#2f241c'>{escape(item.get('name', 'Item'))}</div>"
            f"<div style='color:#6e6055;font-size:13px'>{qty} x ₹{price:.2f}</div>{note_line}"
            "</td>"
            f"<td style='padding:10px 0;border-bottom:1px solid #eee4d8;text-align:right;font-weight:700;color:#2f241c'>₹{line_total:.2f}</td>"
            "</tr>"
        )
    rows_html = "".join(item_rows) if item_rows else (
        "<tr><td colspan='2' style='padding:12px 0;color:#7a6a5d'>No billable items.</td></tr>"
    )

    amounts = bill_amounts_for_ebill(order)
    subtotal = float(amounts.get("subtotal", 0) or 0)
    discount = float(amounts.get("discount", 0) or 0)
    tax = float(amounts.get("tax", 0) or 0)
    total = float(amounts.get("total", 0) or 0)
    discount_row = (
        f"<tr><td style='padding:2px 0;color:#44362c'>Discount</td><td align='right' style='padding:2px 0;font-weight:700'>-₹{discount:.2f}</td></tr>"
        if discount > 0
        else ""
    )
    tax_row = (
        f"<tr><td style='padding:2px 0;color:#44362c'>Tax</td><td align='right' style='padding:2px 0;font-weight:700'>₹{tax:.2f}</td></tr>"
        if tax > 0
        else ""
    )

    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;background:#f5efe8;padding:20px;color:#2f241c'>"
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "style='max-width:620px;margin:0 auto;background:#fff;border:1px solid #eadfce;border-radius:12px'>"
        "<tr><td style='padding:18px'>"
        "<div style='text-align:center;border-bottom:1px dashed #decfbc;padding-bottom:10px'>"
        "<div style='font-size:28px;font-weight:800;color:#3a2a20;letter-spacing:0.02em'>Aromaz Cafe</div>"
        "<div style='font-size:18px;font-weight:700;margin-top:4px'>Itemized e-Bill</div>"
        "<div style='font-size:14px;color:#6e6055;margin-top:6px'>Contact: 9051584252</div>"
        f"<div style='font-size:14px;color:#6e6055;margin-top:3px'>Table {escape(order.get('table_id', '-'))}</div>"
        f"<div style='font-size:14px;color:#6e6055;margin-top:3px'>Order {escape(order.get('id', '-'))}</div>"
        f"<div style='font-size:14px;color:#6e6055;margin-top:3px'>Generated: {escape(created_label)}</div>"
        "</div>"
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='margin-top:10px'>"
        "<tr>"
        "<th align='left' style='font-size:12px;color:#7a6a5d;padding-bottom:6px;letter-spacing:0.06em'>ITEM</th>"
        "<th align='right' style='font-size:12px;color:#7a6a5d;padding-bottom:6px;letter-spacing:0.06em'>AMOUNT</th>"
        "</tr>"
        f"{rows_html}"
        "</table>"
        "<div style='border-top:1px dashed #decfbc;margin-top:10px;padding-top:10px'>"
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0'>"
        f"<tr><td style='padding:2px 0;color:#44362c'>Items</td><td align='right' style='padding:2px 0;font-weight:700'>{sum(int(i.get('qty') or 1) for i in items)}</td></tr>"
        f"<tr><td style='padding:2px 0;color:#44362c'>Subtotal</td><td align='right' style='padding:2px 0;font-weight:700'>₹{subtotal:.2f}</td></tr>"
        f"{discount_row}"
        f"{tax_row}"
        f"<tr><td style='padding:4px 0;color:#2f241c;font-size:18px;font-weight:800'>Total</td><td align='right' style='padding:4px 0;color:#2f241c;font-size:18px;font-weight:800'>₹{total:.2f}</td></tr>"
        "</table>"
        "</div>"
        "<div style='margin-top:14px;padding:12px;background:#f8f3ed;border:1px solid #eadfce;border-radius:10px;text-align:center'>"
        f"<a href='{escape(ebill_url)}' style='display:inline-block;background:#6f4a34;color:#fff;text-decoration:none;font-weight:700;padding:10px 16px;border-radius:8px'>Open Bill Online</a>"
        "<div style='font-size:12px;color:#7a6a5d;margin-top:8px'>Use this if your email app blocks rich formatting.</div>"
        "</div>"
        "<div style='text-align:center;color:#7a6a5d;margin-top:14px;font-size:13px'>Thank you. Please visit again.</div>"
        "</td></tr></table></div>"
    )


async def send_ebill_email(to_email: str, ebill_url: str, order: dict) -> dict:
    normalized = _normalize_email(to_email)
    subject = f"Aromaz Cafe e-bill ({order.get('id', '-')})"
    html = _build_bill_email_html(order, ebill_url)
    attempts = max(1, int(settings.resend_retry_attempts))
    delay = max(0, int(settings.resend_retry_delay_ms)) / 1000
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            result = await asyncio.to_thread(_send_smtp_sync, normalized, subject, html)
            return {"to_email": normalized, "provider": "smtp", "provider_response": result}
        except EmailDeliveryError as exc:
            last_error = exc
            if delay > 0:
                await asyncio.sleep(delay)
    raise EmailDeliveryError(str(last_error or "Email send failed"))


def mask_email(email: str) -> str:
    value = (email or "").strip()
    if "@" not in value:
        return "***"
    local, _, domain = value.partition("@")
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + ("*" * (len(local) - 2)) + local[-1]
    return f"{masked_local}@{domain}"
import asyncio
import smtplib
from email.message import EmailMessage

from app.config import settings


def owner_email_list() -> list[str]:
    return [item.strip() for item in settings.owner_emails.split(",") if item.strip()]


def email_is_configured() -> bool:
    return all(
        [
            settings.smtp_host.strip(),
            settings.smtp_from_email.strip(),
            len(owner_email_list()) > 0,
        ]
    )


def _send_email_blocking(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from_email
    msg["To"] = ", ".join(owner_email_list())
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


async def send_otp_email(code: str) -> bool:
    if not email_is_configured():
        return False
    subject = "Aromaz POS access code"
    body = f"Your one-time access code is: {code}\n\nThis code expires in {settings.otp_ttl_minutes} minutes."
    await asyncio.to_thread(_send_email_blocking, subject, body)
    return True

"""Public QR page: `GET /qr/{token}` — the link a resend request puts in the chat ("QR in chat").

Unauthenticated by design (a customer opens it from WhatsApp/Messenger/the widget), so the safety is in the token
(app/services/qr_link_service.py: signed, expiring, names only the appointment) and in what the page reveals: the QR for
a CONFIRMED/ARRIVED appointment (the exact same QR the confirmation email embeds — Phase 46), the business name, the
service and the time. No customer name/email/phone, no appointment id. EVERY failure (malformed, forged, expired,
unknown appointment, cancelled/completed) returns the same generic 404 page, so the endpoint is never an oracle."""
import base64
import html
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import qr_view_ip_rate_limiter
from app.db.database import get_db
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.service import Service
from app.services import qr_link_service
from app.services.notifications.qr import generate_qr_png

router = APIRouter()

_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'",
}
_STYLE = (
    "body{font-family:system-ui,sans-serif;margin:0;padding:24px;text-align:center;background:#f6f7f9;color:#111}"
    ".card{max-width:340px;margin:0 auto;background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 12px #0002}"
    "img{width:100%;max-width:280px;image-rendering:pixelated}h1{font-size:18px;margin:0 0 4px}"
    "p{margin:6px 0;color:#444}.small{font-size:13px;color:#777}"
)


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    doc = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body><div class=\"card\">{body}</div></body></html>"
    )
    return HTMLResponse(doc, status_code=status_code, headers=_HEADERS)


def _invalid() -> HTMLResponse:
    return _page(
        "Link not valid",
        "<h1>This link isn't valid any more</h1><p>It may have expired, or the appointment was changed. "
        "Ask the business to send you a new one.</p>",
        status_code=404,
    )


@router.get("/qr/{token}", response_class=HTMLResponse, include_in_schema=False)
def view_qr(token: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    client_ip = request.client.host if request.client else "unknown"
    if qr_view_ip_rate_limiter.is_blocked(client_ip):
        return _page("Slow down", "<h1>Too many requests</h1><p>Please wait a minute and try again.</p>", 429)
    qr_view_ip_rate_limiter.record_attempt(client_ip)

    appointment_id = qr_link_service.verify_token(token)
    appointment = db.get(Appointment, appointment_id) if appointment_id else None
    if appointment is None or appointment.status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.ARRIVED):
        return _invalid()
    business = db.get(Business, appointment.business_id)
    service = db.get(Service, appointment.service_id)
    if business is None or service is None:
        return _invalid()

    when = appointment.scheduled_at.astimezone(ZoneInfo(business.timezone)).strftime("%A, %B %-d at %-I:%M %p")
    png = base64.b64encode(generate_qr_png(str(appointment.checkin_token))).decode()
    body = (
        f"<h1>{html.escape(business.name)}</h1><p>{html.escape(service.name)}</p><p><b>{html.escape(when)}</b></p>"
        f'<img alt="Your check-in QR code" src="data:image/png;base64,{png}">'
        '<p class="small">Show this QR code at the front desk when you arrive.</p>'
    )
    return _page("Your check-in QR", body)


@router.get("/pay-qr/{payment_id}", response_class=HTMLResponse, include_in_schema=False)
def view_payment_qr(payment_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """The payment link as a scannable QR — what chat carries alongside the plain link (same "QR in chat" delivery as
    `/qr/{token}` above, and the same generator). The QR encodes exactly `Payment.payment_url`, the real eSewa/Khalti
    checkout link; nothing new is issued. The unguessable payment id is already the only credential the plain link
    carries (`/payments/esewa/redirect/{payment_id}`), so it is no less private here. Only shown while the payment is
    still PENDING — a paid, failed or unknown one gets the same generic 404 page."""
    client_ip = request.client.host if request.client else "unknown"
    if qr_view_ip_rate_limiter.is_blocked(client_ip):
        return _page("Slow down", "<h1>Too many requests</h1><p>Please wait a minute and try again.</p>", 429)
    qr_view_ip_rate_limiter.record_attempt(client_ip)

    payment = db.get(Payment, payment_id)
    if payment is None or payment.status != PaymentStatus.PENDING or not payment.payment_url:
        return _invalid()
    business = db.get(Business, payment.business_id)
    provider_label = {"esewa": "eSewa", "khalti": "Khalti"}.get(payment.provider, payment.provider)
    png = base64.b64encode(generate_qr_png(payment.payment_url)).decode()
    body = (
        f"<h1>{html.escape(business.name if business else 'Deposit payment')}</h1>"
        f"<p><b>{html.escape(payment.currency)} {payment.amount}</b> deposit via {html.escape(provider_label)}</p>"
        f'<img alt="Payment QR code" src="data:image/png;base64,{png}">'
        '<p class="small">Scan with your phone camera to open the payment page.</p>'
    )
    return _page("Your payment QR", body)

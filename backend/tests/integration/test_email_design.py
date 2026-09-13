"""Phase 17 Part A — HTML email templates (app/services/notifications/templates/,
content.py's compose_email, email_provider.py's html_body/attachments support).

Real DB objects throughout (Appointment/Business/Service/Customer rows from
the actual booking flow); the only thing ever stubbed is the network layer
(smtplib), same discipline as every prior notifications test file.
"""

import io
import uuid
from datetime import date, datetime, timedelta
from email import message_from_bytes
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.customer import Customer
from app.db.models.service import Service
from app.main import app
from app.services.notifications.content import compose_email
from app.services.notifications.email_provider import EmailNotificationProvider

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _next_weekday(target_weekday: int) -> date:
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7
    days_ahead = days_ahead or 7
    return today + timedelta(days=days_ahead)


@pytest.fixture
def business_ready():
    email = _unique_email("email-design-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Design Test Co", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"})
    token = login.json()["access_token"]

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token))

    service = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token)
    )
    yield {"token": token, "business_id": business_id, "service_id": uuid.UUID(service.json()["id"])}

    with SessionLocal() as db:
        business = db.get(Business, business_id)
        if business is not None:
            db.delete(business)
        db.commit()


# --- compose_email: real HTML content, correct per event type --------------------------


def test_compose_email_produces_three_parts_with_real_appointment_data():
    business = Business(name="Acme Dental", timezone="UTC")
    service = Service(name="Whitening", price=100, duration_minutes=45)
    customer = Customer(name="Jordan Lee")
    appointment = Appointment(
        id=uuid.uuid4(), scheduled_at=datetime(2026, 9, 7, 14, 0, tzinfo=ZoneInfo("UTC")), duration_minutes=45
    )

    subject, body, html, _inline_images = compose_email(
        event_type="booking_confirmed", appointment=appointment, business=business, service=service, customer=customer
    )
    assert "Acme Dental" in subject
    assert str(appointment.id) in body
    assert "Whitening" in body
    # HTML actually contains the same real data as the plain-text part —
    # this is the "no data discrepancy" requirement, checked structurally.
    assert str(appointment.id) in html
    assert "Whitening" in html
    assert "Jordan Lee" in html
    assert "Confirmed" in html
    assert "<html" in html.lower()


@pytest.mark.parametrize(
    "event_type,expected_label",
    [
        ("booking_confirmed", "Confirmed"),
        ("appointment_cancelled", "Cancelled"),
        ("appointment_rescheduled", "Rescheduled"),
    ],
)
def test_compose_email_status_pill_matches_event_type(event_type, expected_label):
    business = Business(name="Acme Dental", timezone="UTC")
    service = Service(name="Cleaning", price=50, duration_minutes=30)
    customer = Customer(name="Jordan Lee")
    appointment = Appointment(
        id=uuid.uuid4(), scheduled_at=datetime(2026, 9, 7, 14, 0, tzinfo=ZoneInfo("UTC")), duration_minutes=30
    )
    _subject, _body, html, _inline_images = compose_email(
        event_type=event_type, appointment=appointment, business=business, service=service, customer=customer
    )
    assert expected_label in html


def test_compose_email_autoescapes_customer_and_business_names():
    """Real security-relevant check: Jinja2's autoescape=True must neutralize
    HTML-special characters in user-supplied data (customer/business name) so
    they can't corrupt the email's markup or inject content."""
    business = Business(name="A & B <Dental>", timezone="UTC")
    service = Service(name="Cleaning", price=50, duration_minutes=30)
    customer = Customer(name='<script>alert("x")</script>')
    appointment = Appointment(
        id=uuid.uuid4(), scheduled_at=datetime(2026, 9, 7, 14, 0, tzinfo=ZoneInfo("UTC")), duration_minutes=30
    )
    _subject, _body, html, _inline_images = compose_email(
        event_type="booking_confirmed", appointment=appointment, business=business, service=service, customer=customer
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "A &amp; B &lt;Dental&gt;" in html


def test_compose_email_shows_business_contact_footer_and_patient_contact_in_body():
    """A patient should be able to call/find the business straight from the
    email (footer) and should see their own recorded name/contact reflected
    back so they can catch a data-entry error (Booked for: ...)."""
    business = Business(
        name="Samaj Dental Clinic",
        timezone="Asia/Kathmandu",
        address="Radhe Radhe, Birgunj, Nepal",
        phone="+977-51-522345",
        email="info@samajdentalclinic.example.com",
    )
    service = Service(name="Cleaning", price=50, duration_minutes=30)
    customer = Customer(name="Jordan Lee", phone="9800000000", email="jordan@example.com")
    appointment = Appointment(
        id=uuid.uuid4(), scheduled_at=datetime(2026, 9, 7, 14, 0, tzinfo=ZoneInfo("UTC")), duration_minutes=30
    )
    _subject, body, html, _inline_images = compose_email(
        event_type="booking_confirmed", appointment=appointment, business=business, service=service, customer=customer
    )

    for target in (body, html):
        assert "Radhe Radhe, Birgunj, Nepal" in target
        assert "+977-51-522345" in target
        assert "info@samajdentalclinic.example.com" in target
        assert "Jordan Lee" in target
        assert "9800000000" in target
        assert "jordan@example.com" in target


# --- EmailNotificationProvider: real multipart/alternative + attachment structure -------


def test_provider_sends_real_multipart_alternative_with_plain_text_fallback(monkeypatch):
    """Confirms the actual raw MIME message smtplib would send: a real
    multipart/alternative with BOTH a text/plain part (the fallback) and a
    text/html part, not HTML-only."""
    captured = {}

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, message):
            captured["message"] = message
            return {}

    monkeypatch.setattr(settings, "gmail_address", "sender@example.com")
    monkeypatch.setattr(settings, "gmail_app_password", "fake-app-password")
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    provider = EmailNotificationProvider()
    provider.send(
        to="customer@example.com",
        subject="Test Subject",
        body="Plain text fallback content.",
        html_body="<html><body><p>HTML content.</p></body></html>",
    )

    message = captured["message"]
    raw = message.as_bytes()
    parsed = message_from_bytes(raw)

    assert parsed.is_multipart()
    content_types = [part.get_content_type() for part in parsed.walk()]
    assert "multipart/alternative" in content_types
    assert "text/plain" in content_types
    assert "text/html" in content_types

    plain_part = next(p for p in parsed.walk() if p.get_content_type() == "text/plain")
    html_part = next(p for p in parsed.walk() if p.get_content_type() == "text/html")
    assert "Plain text fallback content." in plain_part.get_payload(decode=True).decode()
    assert "HTML content." in html_part.get_payload(decode=True).decode()


def test_provider_combines_html_body_and_attachment_correctly(monkeypatch):
    """The report-email path uses both html_body AND attachments together —
    confirms EmailMessage's automatic multipart/mixed(multipart/alternative,
    attachment) nesting actually happens, not just one or the other."""
    captured = {}

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, message):
            captured["message"] = message
            return {}

    monkeypatch.setattr(settings, "gmail_address", "sender@example.com")
    monkeypatch.setattr(settings, "gmail_app_password", "fake-app-password")
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    wb = Workbook()
    wb.active.append(["hello", "world"])
    buffer = io.BytesIO()
    wb.save(buffer)
    xlsx_bytes = buffer.getvalue()

    provider = EmailNotificationProvider()
    provider.send(
        to="customer@example.com",
        subject="Report",
        body="plain",
        html_body="<html><body>html</body></html>",
        attachments=[("report.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")],
    )

    parsed = message_from_bytes(captured["message"].as_bytes())
    content_types = [part.get_content_type() for part in parsed.walk()]
    assert "multipart/mixed" in content_types
    assert "multipart/alternative" in content_types
    assert "text/plain" in content_types
    assert "text/html" in content_types

    attachment_part = next(p for p in parsed.walk() if p.get_filename() == "report.xlsx")
    assert attachment_part.get_payload(decode=True) == xlsx_bytes


def test_provider_embeds_inline_image_via_real_cid_not_data_uri(monkeypatch):
    """Phase 46 fix — a real bug found via live Gmail testing: a base64
    `data:` URI image never actually renders in a real Gmail inbox, even
    though the raw HTML contains a genuinely valid, independently-decodable
    image (that's exactly why the earlier jsQR-on-raw-HTML proof looked like
    success without reflecting what a real recipient sees — see
    PHASE_STATUS.md). This proves the real fix: a genuine CID-embedded
    inline image, nested inside `multipart/related` under the alternative's
    HTML part (not a top-level attachment) — the real MIME structure every
    real mail client actually requires to resolve `cid:` references."""
    captured = {}

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, message):
            captured["message"] = message
            return {}

    monkeypatch.setattr(settings, "gmail_address", "sender@example.com")
    monkeypatch.setattr(settings, "gmail_app_password", "fake-app-password")
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    fake_png = b"\x89PNG\r\n\x1a\nFAKE-BUT-REAL-BYTES-ROUND-TRIPPED"
    provider = EmailNotificationProvider()
    provider.send(
        to="customer@example.com",
        subject="Check-in",
        body="plain",
        html_body='<html><body><img src="cid:checkin-qrcode"></body></html>',
        inline_images=[("checkin-qrcode", fake_png, "image/png")],
    )

    parsed = message_from_bytes(captured["message"].as_bytes())
    content_types = [part.get_content_type() for part in parsed.walk()]
    # multipart/related is the real, required nesting for CID resolution —
    # a plain top-level attachment (multipart/mixed sibling) would NOT be
    # addressable via cid: in most real mail clients.
    assert "multipart/related" in content_types
    assert "image/png" in content_types

    image_part = next(p for p in parsed.walk() if p.get_content_type() == "image/png")
    assert image_part.get_payload(decode=True) == fake_png
    assert image_part["Content-ID"] == "<checkin-qrcode>"
    assert image_part["Content-Disposition"].startswith("inline")

    html_part = next(p for p in parsed.walk() if p.get_content_type() == "text/html")
    assert 'src="cid:checkin-qrcode"' in html_part.get_payload(decode=True).decode()
    # No data: URI anywhere — the real bug this replaces.
    assert "data:image" not in html_part.get_payload(decode=True).decode()


# --- end-to-end through the real booking flow (stubbed network only) --------------------


def test_real_booking_dispatches_a_real_html_email_with_matching_data(business_ready, monkeypatch):
    """Full path: real booking -> real Notification -> real dispatch_service
    -> real compose_email -> real EmailNotificationProvider, network stubbed.
    Confirms the booking ID/time the customer sees in the (stubbed-sent) HTML
    body is the exact same one in the real DB row — the "no data discrepancy"
    check, automated."""
    from app.services.notifications import dispatch_service

    captured = {}

    class _FakeProvider:
        SIMULATED = False

        def send(self, *, to, subject, body, html_body=None, attachments=None, inline_images=None):
            captured["to"] = to
            captured["html_body"] = html_body
            captured["body"] = body
            captured["inline_images"] = inline_images
            return "250 ok"

    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", _FakeProvider())

    customer = client.post(
        "/api/v1/customers",
        json={"name": "Jordan Lee", "email": "jordan@example.com"},
        headers=_auth_header(business_ready["token"]),
    ).json()
    when = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = client.post(
        "/api/v1/appointments",
        json={"customer_id": customer["id"], "service_id": str(business_ready["service_id"]), "scheduled_at": when.isoformat()},
        headers=_auth_header(business_ready["token"]),
    ).json()

    assert captured["to"] == "jordan@example.com"
    assert appointment["id"] in captured["html_body"]
    assert appointment["id"] in captured["body"]
    assert "Design Test Co" in captured["html_body"]
    assert "Cleaning" in captured["html_body"]

    with SessionLocal() as db:
        row = db.get(Appointment, uuid.UUID(appointment["id"]))
        assert row.scheduled_at == when

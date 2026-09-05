"""Phase 29 — TIER 2 ITEM 6: adversarial input-validation sweep across 10
endpoints spanning different phases (auth/register, customers, services,
staff, knowledge, business profile, the public widget).

This is the REGRESSION-TEST record of a real live sweep that found 6 genuine
500s (raw psycopg2/ValueError exceptions reaching the client) before the fix
in app/schemas/common.py + the schemas listed below:
  - POST /customers: NUL byte in name, 200,000-char name
  - POST /services: 200,000-char name
  - POST /staff: NUL byte in name, 200,000-char name
  - POST /knowledge: NUL byte in title, 200,000-char title
  - PATCH /business/me: 200,000-char address, NUL byte in phone
  - POST /auth/register: 200,000-char business_name
  - POST /widget/{id}/messages (PUBLIC, unauthenticated): NUL byte in
    content, AND an uncapped 5MB content string that reached a real LLM API
    call before anything rejected it (cost/DoS exposure on an anonymous
    endpoint)

SQL-injection-shaped and XSS-shaped strings were also tested: both are
accepted as literal data (SQLAlchemy parameterizes every query — never
string-formatted SQL) and, for XSS, verified actually escaped wherever they
could reach an HTML surface (email templates — see
test_xss_payload_is_actually_escaped_in_rendered_email below), not merely
assumed safe because it wasn't reflected back in the JSON response."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.business import Business
from app.main import app
from app.services.notifications.templates.render import render_appointment_email

client = TestClient(app)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def business():
    email = f"inputval-{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Input Val Co", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = resp.json()["business_id"]
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()[
        "access_token"
    ]
    yield {"business_id": business_id, "token": token}
    with SessionLocal() as db:
        b = db.get(Business, uuid.UUID(business_id))
        if b is not None:
            db.delete(b)
        db.commit()


_LONG = "A" * 200_000
_NUL = "Bad\x00Value"


@pytest.mark.parametrize(
    "method,path,body_fn",
    [
        ("POST", "/api/v1/customers", lambda: {"name": _LONG}),
        ("POST", "/api/v1/customers", lambda: {"name": _NUL}),
        ("POST", "/api/v1/services", lambda: {"name": _LONG, "price": "10.00", "duration_minutes": 30}),
        ("POST", "/api/v1/staff", lambda: {"name": _LONG, "role": "dentist"}),
        ("POST", "/api/v1/staff", lambda: {"name": _NUL, "role": "dentist"}),
        ("POST", "/api/v1/knowledge", lambda: {"title": _LONG, "content": "hello"}),
        ("POST", "/api/v1/knowledge", lambda: {"title": _NUL, "content": "hello"}),
        ("PATCH", "/api/v1/business/me", lambda: {"address": _LONG}),
        ("PATCH", "/api/v1/business/me", lambda: {"phone": _NUL}),
    ],
)
def test_oversized_and_nul_byte_payloads_are_rejected_cleanly_not_500(method, path, body_fn, business):
    resp = client.request(method, path, json=body_fn(), headers=_auth_header(business["token"]))
    assert resp.status_code == 422, (
        f"SECURITY/CORRECTNESS FAILURE — {method} {path} returned {resp.status_code} instead of a "
        f"clean 422: {resp.text[:300]}"
    )
    assert resp.json()["error"]["type"] == "validation_error"


def test_register_rejects_oversized_business_name_not_500():
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": _LONG, "timezone": "UTC", "email": "x@example.com", "password": "correcthorse1"},
    )
    assert resp.status_code == 422, resp.text


def test_widget_rejects_nul_byte_and_oversized_content_not_500():
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Widget Input Val Co",
            "timezone": "UTC",
            "email": f"widgetinputval-{uuid.uuid4().hex[:10]}@example.com",
            "password": "correcthorse1",
        },
    )
    business_id = resp.json()["business_id"]
    try:
        nul_resp = client.post(f"/api/v1/widget/{business_id}/messages", json={"content": _NUL})
        assert nul_resp.status_code == 422, f"NUL byte in widget content: {nul_resp.status_code} {nul_resp.text}"

        huge_resp = client.post(f"/api/v1/widget/{business_id}/messages", json={"content": "A" * 5_000_000})
        assert huge_resp.status_code == 422, (
            f"5MB widget content should be rejected before reaching the LLM: "
            f"{huge_resp.status_code} {huge_resp.text[:200]}"
        )
    finally:
        with SessionLocal() as db:
            b = db.get(Business, uuid.UUID(business_id))
            if b is not None:
                db.delete(b)
            db.commit()


def test_sql_injection_shaped_string_is_stored_as_literal_data_not_executed(business):
    """SQLAlchemy parameterizes every query in this codebase — this proves it
    empirically rather than just trusting that claim: the payload is stored
    verbatim and the customers table survives untouched."""
    payload = "Robert'); DROP TABLE customers;--"
    resp = client.post("/api/v1/customers", json={"name": payload}, headers=_auth_header(business["token"]))
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == payload

    # If the DROP TABLE had actually executed, this next call would 500.
    listing = client.get("/api/v1/customers/" + resp.json()["id"], headers=_auth_header(business["token"]))
    assert listing.status_code == 200
    assert listing.json()["name"] == payload


def test_xss_shaped_string_is_accepted_as_data_and_escaped_in_rendered_email(business):
    payload = "<script>alert(document.cookie)</script>"
    resp = client.post("/api/v1/customers", json={"name": payload}, headers=_auth_header(business["token"]))
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == payload  # stored as literal data via the API, not sanitized/mangled

    # The real risk isn't storage — it's rendering. This app's ONE HTML
    # rendering surface (transactional emails) MUST escape it.
    html = render_appointment_email(
        business_name="Input Val Co",
        customer_name=payload,
        service_name="Cleaning",
        scheduled_at="2026-01-01 10:00",
        event_type="booking_confirmed",
    )
    assert payload not in html, "SECURITY FAILURE — unescaped XSS payload reached rendered HTML email"
    assert "&lt;script&gt;" in html


def test_wrong_types_rejected_cleanly_on_appointments(business):
    resp = client.post(
        "/api/v1/appointments",
        json={"customer_id": "not-a-uuid", "service_id": "also-not-a-uuid", "scheduled_at": "not-a-date"},
        headers=_auth_header(business["token"]),
    )
    assert resp.status_code == 422, resp.text


def test_wrong_type_rejected_cleanly_on_services_price(business):
    resp = client.post(
        "/api/v1/services",
        json={"name": "Svc", "price": "not-a-number", "duration_minutes": 30},
        headers=_auth_header(business["token"]),
    )
    assert resp.status_code == 422, resp.text

# ruff: noqa: F811  (fixtures imported from the Phase 44 suite are re-declared as test arguments — the pytest idiom)
"""Phase 47 bug fix: eSewa appends its own "?data=<base64>" to success_url/failure_url with no regard for an existing
query string, so the original ".../success?payment_id=X" came back as ".../success?payment_id=X?data=..." and a real,
COMPLETED eSewa payment was reported "No payment reference received" and left PENDING. The id now lives in the URL path;
the old shape is still accepted for eSewa sessions opened before the fix.
"""

import uuid
from decimal import Decimal
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.payment import Payment, PaymentStatus
from app.main import app
from app.services.payments.base import PaymentVerification
from app.services.payments.esewa import signed_form_fields
from tests.integration.test_payments import (  # noqa: F401
    _auth_header,
    _next_weekday_datetime,
    fake_provider,
    premium_npr_ready,
    two_businesses,
)

client = TestClient(app)

# the `data` value eSewa's sandbox really sent (Phase 47 live run, transaction 000H5DN) — kept verbatim
REAL_DATA = (
    "eyJ0cmFuc2FjdGlvbl9jb2RlIjoiMDAwSDVETiIsInN0YXR1cyI6IkNPTVBMRVRFIiwidG90YWxfYW1vdW50IjoiMTIuMCIsInRyYW5zYWN0aW9uX3V1"
    "aWQiOiI4MzBmYTVkZi0zZDQzLTRjNjgtOWQ3Yi0xYjE2OWJkNjFjN2UiLCJwcm9kdWN0X2NvZGUiOiJFUEFZVEVTVCIsInNpZ25lZF9maWVsZF9uYW1l"
    "cyI6InRyYW5zYWN0aW9uX2NvZGUsc3RhdHVzLHRvdGFsX2Ftb3VudCx0cmFuc2FjdGlvbl91dWlkLHByb2R1Y3RfY29kZSxzaWduZWRfZmllbGRfbmFt"
    "ZXMiLCJzaWduYXR1cmUiOiIwamFlRmdPeUtxNFFsS0dnWGNCQVduMFNndDdqZ0o2c1VpR1hmUmtrUUVvPSJ9"
)


@pytest.fixture
def pending_payment(premium_npr_ready, fake_provider) -> Payment:
    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(premium_npr_ready["customer_id"]),
            "service_id": str(premium_npr_ready["deposit_service_id"]),
            "scheduled_at": _next_weekday_datetime(10),
        },
        headers=_auth_header(premium_npr_ready["token_a"]),
    )
    assert resp.status_code == 201, resp.text
    with SessionLocal() as db:
        return db.query(Payment).filter(Payment.business_id == premium_npr_ready["business_id_a"]).one()


def _status(payment_id: uuid.UUID) -> PaymentStatus:
    with SessionLocal() as db:
        return db.get(Payment, payment_id).status


def test_return_urls_have_no_query_string_so_eSewas_appended_data_stays_well_formed():
    payment_id = uuid.uuid4()
    fields = signed_form_fields(payment_id=payment_id, amount=Decimal("12.00"))
    for key, leaf in (("success_url", "success"), ("failure_url", "failure")):
        assert "?" not in fields[key]
        appended = urlsplit(fields[key] + "?data=" + REAL_DATA)  # exactly what eSewa does
        assert appended.path == f"/api/v1/payments/esewa/{leaf}/{payment_id}"
        assert appended.query == "data=" + REAL_DATA
        assert fields[key].startswith(settings.backend_base_url)


def test_new_shape_success_url_with_real_esewa_data_completes_the_payment(pending_payment):
    resp = client.get(f"/api/v1/payments/esewa/success/{pending_payment.id}", params={"data": REAL_DATA})
    assert "Payment received" in resp.text
    assert _status(pending_payment.id) == PaymentStatus.COMPLETED


def test_old_shape_real_captured_malformed_url_still_completes_the_payment(pending_payment):
    # byte-for-byte the shape eSewa really sent: two "?" — only the payment id is swapped for a fresh test payment
    resp = client.get(f"/api/v1/payments/esewa/success?payment_id={pending_payment.id}?data={REAL_DATA}")
    assert resp.status_code == 200
    assert "Something went wrong" not in resp.text and "Payment received" in resp.text
    assert _status(pending_payment.id) == PaymentStatus.COMPLETED


def test_old_shape_failure_url_with_appended_data_is_identified_and_verified(pending_payment, fake_provider):
    fake_provider.verify_result = PaymentVerification(completed=False, raw_status="NOT_FOUND")
    resp = client.get(f"/api/v1/payments/esewa/failure?payment_id={pending_payment.id}?data={REAL_DATA}")
    assert "Payment not completed" in resp.text
    assert _status(pending_payment.id) == PaymentStatus.FAILED


def test_cancel_with_no_data_is_still_identified_by_the_path(pending_payment, fake_provider):
    fake_provider.verify_result = PaymentVerification(completed=False, raw_status="NOT_FOUND")
    resp = client.get(f"/api/v1/payments/esewa/failure/{pending_payment.id}")
    assert "Payment not completed" in resp.text
    assert _status(pending_payment.id) == PaymentStatus.FAILED


def test_redirect_is_never_trusted_on_its_own_the_gateway_lookup_decides(pending_payment, fake_provider):
    fake_provider.verify_result = PaymentVerification(completed=False, raw_status="PENDING")
    # a success-shaped URL whose payload claims COMPLETE, but eSewa's own lookup says otherwise
    client.get(f"/api/v1/payments/esewa/success/{pending_payment.id}", params={"data": REAL_DATA})
    assert _status(pending_payment.id) != PaymentStatus.COMPLETED


def test_garbage_id_gets_the_generic_error_not_a_crash():
    resp = client.get("/api/v1/payments/esewa/success/not-a-uuid")
    assert resp.status_code == 200 and "Something went wrong" in resp.text

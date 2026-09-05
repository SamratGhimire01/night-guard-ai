"""Phase 29 — TIER 1 ITEM 2: adversarial JWT/auth review across MULTIPLE
distinct routes, not just /auth/me. Every attack below is a real forged/
tampered/expired token sent to a real running app, never a mocked check."""

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.main import app

client = TestClient(app)

# One representative route per auth tier, hit with every attack below — the
# ticket's explicit ask ("not just the routes originally tested").
_PROTECTED_ROUTES = [
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/services"),
    ("GET", "/api/v1/appointments"),
    ("GET", "/api/v1/knowledge"),
    ("GET", "/api/v1/handoffs"),
    ("GET", "/api/v1/training/history"),
    ("GET", "/api/v1/reports/daily?date=2026-01-01"),
]


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def registered_business():
    email = _unique_email("jwt-audit-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "JWT Audit Co", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    user_id = uuid.UUID(resp.json()["user_id"])
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"})
    assert login.status_code == 200
    data = {"business_id": business_id, "user_id": user_id, "token": login.json()["access_token"]}
    yield data
    with SessionLocal() as db:
        business = db.get(Business, business_id)
        if business is not None:
            db.delete(business)
        db.commit()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _forge_alg_none_token(payload: dict) -> str:
    """Classic JWT attack: alg=none, no signature at all."""
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload, default=str).encode())
    return f"{header}.{body}."


def _forge_wrong_secret_token(payload: dict) -> str:
    return jwt.encode(payload, "attacker-guessed-secret-123", algorithm="HS256")


def _forge_tampered_payload_keep_original_signature(valid_token: str, new_payload: dict) -> str:
    """Splice a modified payload onto the ORIGINAL header+signature — proves
    the signature actually covers the payload (a naive verifier that only
    checks header+sig format, not the recomputed HMAC, would accept this)."""
    header_b64, _, sig_b64 = valid_token.split(".")
    new_body_b64 = _b64url(json.dumps(new_payload, default=str).encode())
    return f"{header_b64}.{new_body_b64}.{sig_b64}"


@pytest.mark.parametrize("method,path", _PROTECTED_ROUTES)
def test_missing_token_rejected_on_every_route(method, path):
    resp = client.request(method, path)
    assert resp.status_code == 401, f"{method} {path}: expected 401, got {resp.status_code}: {resp.text}"
    assert resp.json()["error"]["type"] == "unauthorized"


@pytest.mark.parametrize("method,path", _PROTECTED_ROUTES)
def test_garbage_token_rejected_on_every_route(method, path):
    resp = client.request(method, path, headers={"Authorization": "Bearer not.a.jwt.at.all"})
    assert resp.status_code == 401, f"{method} {path}: expected 401, got {resp.status_code}: {resp.text}"


@pytest.mark.parametrize("method,path", _PROTECTED_ROUTES)
def test_expired_token_rejected_on_every_route(method, path, registered_business):
    expired = create_access_token(
        user_id=registered_business["user_id"],
        business_id=registered_business["business_id"],
        role="owner",
        expires_minutes=-5,
    )
    resp = client.request(method, path, headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401, f"{method} {path}: expected 401, got {resp.status_code}: {resp.text}"
    assert "expired" in resp.json()["error"]["message"].lower()


@pytest.mark.parametrize("method,path", _PROTECTED_ROUTES)
def test_tampered_signature_rejected_on_every_route(method, path, registered_business):
    token = registered_business["token"]
    tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
    resp = client.request(method, path, headers={"Authorization": f"Bearer {tampered}"})
    assert resp.status_code == 401, f"{method} {path}: expected 401, got {resp.status_code}: {resp.text}"


def test_alg_none_forged_token_is_rejected(registered_business):
    """If this ever passed, an attacker could mint a token for ANY user_id/
    business_id/role with zero knowledge of SECRET_KEY."""
    forged = _forge_alg_none_token(
        {
            "sub": str(registered_business["user_id"]),
            "business_id": str(registered_business["business_id"]),
            "role": "owner",
            "iat": datetime.now(timezone.utc).timestamp(),
            "exp": (datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp(),
        }
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401, f"SECURITY FAILURE — alg=none token accepted! {resp.status_code}: {resp.text}"


def test_token_forged_with_wrong_secret_is_rejected(registered_business):
    forged = _forge_wrong_secret_token(
        {
            "sub": str(registered_business["user_id"]),
            "business_id": str(registered_business["business_id"]),
            "role": "owner",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401, f"SECURITY FAILURE — token signed with wrong secret accepted! {resp.text}"


def test_privilege_escalation_via_tampered_role_claim_is_rejected(registered_business):
    """Attacker has a real, validly-issued STAFF token and edits the JWT's own
    role claim from staff to owner, keeping the original (now-mismatched)
    signature — the only move available without knowing SECRET_KEY."""
    real_token = create_access_token(
        user_id=registered_business["user_id"], business_id=registered_business["business_id"], role="staff"
    )
    real_payload = jwt.decode(real_token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    escalated_payload = {**real_payload, "role": "owner"}
    forged = _forge_tampered_payload_keep_original_signature(real_token, escalated_payload)

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401, f"SECURITY FAILURE — role-tampered token accepted! {resp.text}"


def test_cross_business_id_tampering_in_token_is_rejected(registered_business):
    """Attacker edits business_id inside their OWN valid token to point at a
    victim business, keeping the original signature."""
    real_token = registered_business["token"]
    real_payload = jwt.decode(real_token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    tampered_payload = {**real_payload, "business_id": str(uuid.uuid4())}
    forged = _forge_tampered_payload_keep_original_signature(real_token, tampered_payload)

    resp = client.get("/api/v1/services", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401, f"SECURITY FAILURE — business_id-tampered token accepted! {resp.text}"


def test_token_for_deleted_user_is_rejected(registered_business):
    """A real, validly-signed, non-expired token whose user was deleted after
    issuance (e.g. offboarded staff whose access should be instantly dead —
    there is no revocation list, so this is the ONLY real backstop) must not
    still work."""
    token = registered_business["token"]
    with SessionLocal() as db:
        business = db.get(Business, registered_business["business_id"])
        db.delete(business)
        db.commit()

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, f"SECURITY FAILURE — token for deleted user still authenticated! {resp.text}"


def test_malformed_bearer_scheme_variants_rejected(registered_business):
    token = registered_business["token"]
    for bad_header in (
        token,  # no "Bearer " prefix at all
        f"Bearer{token}",  # missing space
        f"Basic {token}",  # wrong scheme
        "Bearer ",  # empty credentials
    ):
        resp = client.get("/api/v1/auth/me", headers={"Authorization": bad_header})
        assert resp.status_code in (401, 403), (
            f"header={bad_header!r} unexpectedly returned {resp.status_code}: {resp.text}"
        )
        assert resp.status_code != 200, f"SECURITY FAILURE — malformed scheme {bad_header!r} authenticated!"


def test_lowercase_bearer_scheme_is_accepted_and_this_is_correct_not_a_bug(registered_business):
    """`bearer <token>` (lowercase) DOES authenticate successfully — verified
    live below. This is Starlette's HTTPBearer treating the auth-scheme
    case-insensitively, which is the spec-correct behavior per RFC 7235 §2.1
    ("A client SHOULD use upper-case ... though case-insensitivity is
    required for auth-scheme by RFC 7235"). Not a vulnerability: the
    credential itself (the JWT after the scheme) still goes through the exact
    same full signature/expiry/user-existence verification either way —
    lowering the scheme name grants no attacker any bypass, it's just a
    second spelling of "Bearer" that this library correctly accepts."""
    token = registered_business["token"]
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"bearer {token}"})
    assert resp.status_code == 200, resp.text

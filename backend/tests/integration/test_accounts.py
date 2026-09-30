"""Forgot/reset/change password and team logins (app/services/account_service.py, routes in auth.py and team.py).

Real HTTP, real Postgres, real bcrypt and JWTs. Emails are captured instead of sent."""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.services.account_service as account_service
from app.core import rate_limit
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.main import app

client = TestClient(app)
PASSWORD = "correcthorse1"


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(account_service, "_email_in_background", lambda **kw: sent.append(kw))
    monkeypatch.setattr(rate_limit, "login_rate_limiter", rate_limit.RateLimiter())
    import app.api.routes.auth as auth_routes

    monkeypatch.setattr(auth_routes, "login_rate_limiter", rate_limit.RateLimiter())
    monkeypatch.setattr(auth_routes, "password_reset_rate_limiter", rate_limit.RateLimiter(max_attempts=5, window_seconds=3600))
    return sent


def _register(label="acct"):
    email = f"{label}-{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/v1/auth/register", json={"business_name": f"{label} Co", "timezone": "UTC", "email": email, "password": PASSWORD}
    )
    assert reg.status_code == 201, reg.text
    return reg.json()["business_id"], email


def _login(email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _link_token(mail):
    return mail["body"].split("token=")[1].split()[0]


@pytest.fixture
def owner():
    business_id, email = _register()
    token = _login(email).json()["access_token"]
    yield business_id, email, token
    with SessionLocal() as db:
        db.delete(db.get(Business, uuid.UUID(business_id)))
        db.commit()


# ---- login ----

def test_login_ignores_capital_letters_in_the_email(owner):
    _, email, _ = owner
    assert _login(email.upper()).status_code == 200


# ---- forgot / reset ----

def test_forgot_password_emails_a_link_that_sets_a_new_password_and_logs_in(owner, outbox):
    _, email, _ = owner
    resp = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert resp.status_code == 202
    assert outbox and outbox[0]["to"] == email

    reset = client.post("/api/v1/auth/reset-password", json={"token": _link_token(outbox[0]), "new_password": "newpass123"})
    assert reset.status_code == 200, reset.text
    assert client.get("/api/v1/auth/me", headers=_auth(reset.json()["access_token"])).status_code == 200
    assert _login(email, "newpass123").status_code == 200
    assert _login(email).status_code == 401


def test_reset_link_works_only_once(owner, outbox):
    _, email, _ = owner
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    token = _link_token(outbox[0])
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "newpass123"}).status_code == 200
    again = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "other456x"})
    assert again.status_code == 401
    assert "already been used" in again.json()["error"]["message"]


def test_forgot_password_gives_the_same_answer_for_unknown_emails(outbox):
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "nobody-here@example.com"})
    assert resp.status_code == 202
    assert outbox == []


def test_a_reset_link_cannot_be_used_as_a_login_token(owner, outbox):
    _, email, _ = owner
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert client.get("/api/v1/auth/me", headers=_auth(_link_token(outbox[0]))).status_code == 401


def test_a_login_token_cannot_be_used_as_a_reset_link(owner):
    _, _, token = owner
    resp = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "newpass123"})
    assert resp.status_code == 401


def test_reset_rejects_a_weak_new_password(owner, outbox):
    _, email, _ = owner
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    resp = client.post("/api/v1/auth/reset-password", json={"token": _link_token(outbox[0]), "new_password": "short"})
    assert resp.status_code == 422


def test_forgot_password_is_rate_limited_per_email(owner, outbox):
    _, email, _ = owner
    for _ in range(8):
        assert client.post("/api/v1/auth/forgot-password", json={"email": email}).status_code == 202
    assert len(outbox) == 5


# ---- change password ----

def test_change_password_signs_out_other_sessions_but_keeps_this_one(owner):
    _, email, token = owner
    other_session = _login(email).json()["access_token"]
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(token),
        json={"current_password": PASSWORD, "new_password": "newpass123"},
    )
    assert resp.status_code == 200, resp.text
    assert client.get("/api/v1/auth/me", headers=_auth(resp.json()["access_token"])).status_code == 200
    stale = client.get("/api/v1/auth/me", headers=_auth(other_session))
    assert stale.status_code == 401
    assert "password was changed" in stale.json()["error"]["message"]


def test_change_password_needs_the_current_password(owner):
    _, _, token = owner
    resp = client.post(
        "/api/v1/auth/change-password", headers=_auth(token), json={"current_password": "wrongpass1", "new_password": "newpass123"}
    )
    assert resp.status_code == 422


# ---- team ----

def test_owner_invites_a_staff_member_who_sets_a_password_and_logs_in(owner, outbox):
    _, _, token = owner
    new_email = f"staff-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/team", headers=_auth(token), json={"email": new_email, "role": "staff"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["member"]["role"] == "staff"
    assert outbox[-1]["to"] == new_email

    link_token = resp.json()["invite_link"].split("token=")[1]
    assert _login(new_email).status_code == 401  # no usable password until they choose one
    assert client.post("/api/v1/auth/reset-password", json={"token": link_token, "new_password": "staffpass1"}).status_code == 200
    staff_token = _login(new_email, "staffpass1").json()["access_token"]
    me = client.get("/api/v1/auth/me", headers=_auth(staff_token)).json()
    assert me["role"] == "staff"
    # staff can't manage the team
    assert client.get("/api/v1/team", headers=_auth(staff_token)).status_code == 403

    members = client.get("/api/v1/team", headers=_auth(token)).json()
    assert {m["email"] for m in members} >= {new_email}


def test_admin_can_add_staff_but_not_admins(owner):
    _, _, token = owner
    admin_email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    link = client.post("/api/v1/team", headers=_auth(token), json={"email": admin_email, "role": "admin"}).json()["invite_link"]
    client.post("/api/v1/auth/reset-password", json={"token": link.split("token=")[1], "new_password": "adminpass1"})
    admin_token = _login(admin_email, "adminpass1").json()["access_token"]
    assert client.post("/api/v1/team", headers=_auth(admin_token), json={"email": f"s-{uuid.uuid4().hex[:6]}@example.com", "role": "staff"}).status_code == 201
    assert client.post("/api/v1/team", headers=_auth(admin_token), json={"email": f"a-{uuid.uuid4().hex[:6]}@example.com", "role": "admin"}).status_code == 403


def test_role_change_takes_effect_immediately_and_removal_locks_them_out(owner):
    _, _, token = owner
    email = f"staff-{uuid.uuid4().hex[:8]}@example.com"
    invited = client.post("/api/v1/team", headers=_auth(token), json={"email": email, "role": "staff"}).json()
    client.post("/api/v1/auth/reset-password", json={"token": invited["invite_link"].split("token=")[1], "new_password": "staffpass1"})
    staff_token = _login(email, "staffpass1").json()["access_token"]
    member_id = invited["member"]["id"]

    assert client.patch(f"/api/v1/team/{member_id}", headers=_auth(token), json={"role": "admin"}).status_code == 200
    assert client.get("/api/v1/team", headers=_auth(staff_token)).status_code == 200  # now an admin, same token

    assert client.delete(f"/api/v1/team/{member_id}", headers=_auth(token)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=_auth(staff_token)).status_code == 401


def test_owner_cannot_remove_or_demote_themselves(owner):
    _, _, token = owner
    me = client.get("/api/v1/auth/me", headers=_auth(token)).json()
    assert client.delete(f"/api/v1/team/{me['user_id']}", headers=_auth(token)).status_code == 403
    assert client.patch(f"/api/v1/team/{me['user_id']}", headers=_auth(token), json={"role": "staff"}).status_code == 403


def test_an_email_that_already_has_a_login_cannot_be_invited_again(owner):
    _, email, token = owner
    assert client.post("/api/v1/team", headers=_auth(token), json={"email": email.upper(), "role": "staff"}).status_code == 409


def test_team_management_never_crosses_businesses(owner):
    _, _, token = owner
    other_business, other_email = _register("other")
    try:
        other_token = _login(other_email).json()["access_token"]
        invited = client.post("/api/v1/team", headers=_auth(token), json={"email": f"x-{uuid.uuid4().hex[:6]}@example.com", "role": "staff"}).json()
        member_id = invited["member"]["id"]
        assert client.delete(f"/api/v1/team/{member_id}", headers=_auth(other_token)).status_code == 404
        assert client.patch(f"/api/v1/team/{member_id}", headers=_auth(other_token), json={"role": "admin"}).status_code == 404
        assert member_id not in {m["id"] for m in client.get("/api/v1/team", headers=_auth(other_token)).json()}
    finally:
        with SessionLocal() as db:
            db.delete(db.get(Business, uuid.UUID(other_business)))
            db.commit()

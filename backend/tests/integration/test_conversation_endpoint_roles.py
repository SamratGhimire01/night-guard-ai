"""Phase 52 — POST /conversations/{id}/messages stores a message AS the customer and spends a real LLM call, so it is
owner/admin only: a staff login (who reads these conversations in the inbox) must not be able to plant customer-looking text."""

import pytest

from app.db.models.business import BusinessUser, BusinessUserRole
from app.db.database import SessionLocal
from app.core.security import create_access_token

from tests.integration.test_human_takeover import _auth, _count, _email, _messages, _new_conversation, biz, client, llm  # noqa: F401


def _post(cid, token):
    return client.post(f"/api/v1/conversations/{cid}/messages", json={"content": "I am the customer"}, headers=_auth(token) if token else {})


def test_staff_gets_403_and_nothing_is_stored_or_spent(biz, llm):
    cid = _new_conversation(biz["business_id"])
    resp = _post(cid, biz["staff_token"])
    assert resp.status_code == 403, resp.text
    assert llm.calls == 0  # no LLM call was made
    assert _messages(cid) == []  # no customer-looking message was planted


def test_owner_and_admin_are_unaffected(biz, llm):
    with SessionLocal() as db:
        admin = BusinessUser(business_id=biz["business_id"], email=_email("adm"), hashed_password="x", role=BusinessUserRole.ADMIN)
        db.add(admin)
        db.commit()
        db.refresh(admin)
        admin_token = create_access_token(user_id=admin.id, business_id=biz["business_id"], role="admin")
    for token in (biz["owner_token"], admin_token):
        cid = _new_conversation(biz["business_id"])
        resp = _post(cid, token)
        assert resp.status_code == 201, resp.text
        assert resp.json()["response"]


def test_unauthenticated_is_401(biz):
    assert _post(_new_conversation(biz["business_id"]), None).status_code == 401

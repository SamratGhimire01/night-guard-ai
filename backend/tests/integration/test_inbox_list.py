"""Phase 52 stage 4 (backend for the UI): the inbox list, the sidebar summary and the read marker."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.database import SessionLocal
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message, MessageSenderType as S
from app.db.models.customer import Customer
from app.db.models.handoff import HumanHandoff

from tests.integration.test_human_takeover import _auth, biz, client  # noqa: F401

NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731  (messages.created_at is naive UTC)


def _conv(business_id, name, channel, msgs, *, handoff=False, takeover_by=None, takeover_active=True):
    """msgs: [(sender, content, minutes_ago, delivery_status?)] -> a conversation with exactly those messages."""
    with SessionLocal() as db:
        customer = Customer(business_id=business_id, name=name)
        db.add(customer)
        db.flush()
        conv = Conversation(business_id=business_id, customer_id=customer.id, channel=channel, status="open")
        if takeover_by:
            conv.human_takeover_by = takeover_by
            conv.human_takeover_until = datetime.now(timezone.utc) + timedelta(hours=1 if takeover_active else -1)
        db.add(conv)
        db.flush()
        for sender, content, ago, *rest in msgs:
            db.add(Message(conversation_id=conv.id, sender_type=sender, content=content, created_at=NOW() - timedelta(minutes=ago),
                           delivery_status=rest[0] if rest else None))
        if handoff:
            db.add(HumanHandoff(business_id=business_id, conversation_id=conv.id, reason="asked for a human", status="open"))
        db.commit()
        return conv.id


def _list(token, **params):
    resp = client.get("/api/v1/inbox/conversations", params=params, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def world(biz):
    b, staff = biz["business_id"], biz["staff_id"]
    ids = {
        # AI answered: never "needs reply"
        "ai_done": _conv(b, "Ana Answered", "website", [(S.CUSTOMER, "hours?", 30), (S.AGENT, "9 to 5", 29)]),
        # escalated and the customer spoke last -> needs a person
        "handoff": _conv(b, "Hari Handoff", "whatsapp", [(S.CUSTOMER, "I want a human", 5)], handoff=True),
        # a staff member owns it and the customer answered -> needs a person
        "owned": _conv(b, "Olga Owned", "messenger", [(S.CUSTOMER, "hi", 20), (S.STAFF, "hello!", 15, "sent"), (S.CUSTOMER, "thanks, one more thing", 2)], takeover_by=staff),
        # a staff member owns it but staff spoke last -> waiting on the customer, not on us
        "waiting_on_cust": _conv(b, "Wes Waiting", "instagram", [(S.CUSTOMER, "q", 40), (S.STAFF, "answer", 10, "failed")], takeover_by=staff),
        # escalated earlier, the AI answered last -> has a handoff, but nobody is waiting
        "handoff_answered": _conv(b, "Hana Answered", "whatsapp", [(S.CUSTOMER, "help", 50), (S.AGENT, "on it", 49)], handoff=True),
        # takeover ran out -> back with the AI, not "needs reply" even though the customer spoke last
        "expired": _conv(b, "Eve Expired", "website", [(S.STAFF, "hi", 300), (S.CUSTOMER, "ok", 200)], takeover_by=staff, takeover_active=False),
    }
    return {**biz, **ids}


def test_needs_reply_is_a_human_responsible_conversation_where_the_customer_spoke_last(world):
    rows = {r["customer_name"]: r for r in _list(world["staff_token"])}
    assert {n for n, r in rows.items() if r["needs_reply"]} == {"Hari Handoff", "Olga Owned"}
    assert rows["Hana Answered"]["open_handoff"] and not rows["Hana Answered"]["needs_reply"]
    assert rows["Eve Expired"]["takeover_active"] is False and rows["Eve Expired"]["takeover_by_email"] is None
    assert rows["Olga Owned"]["takeover_active"] and rows["Olga Owned"]["takeover_by_email"]  # "who is handling this"


def test_tabs_channel_filter_search_and_ordering(world):
    tok = world["staff_token"]
    assert {r["customer_name"] for r in _list(tok, tab="needs_reply")} == {"Hari Handoff", "Olga Owned"}
    assert {r["customer_name"] for r in _list(tok, tab="handoffs")} == {"Hari Handoff", "Hana Answered"}
    assert {r["customer_name"] for r in _list(tok, channel="whatsapp")} == {"Hari Handoff", "Hana Answered"}
    assert [r["customer_name"] for r in _list(tok, q="olga")] == ["Olga Owned"]
    names = [r["customer_name"] for r in _list(tok)]
    assert names == ["Olga Owned", "Hari Handoff", "Wes Waiting", "Ana Answered", "Hana Answered", "Eve Expired"]  # newest activity first
    assert [r["customer_name"] for r in _list(tok, limit=2)] == names[:2]
    assert [r["customer_name"] for r in _list(tok, limit=2, offset=2)] == names[2:4]


def test_last_message_fields_and_delivery_status(world):
    rows = {r["customer_name"]: r for r in _list(world["owner_token"])}
    olga = rows["Olga Owned"]
    assert olga["last_message_sender"] == "customer" and olga["last_message_preview"] == "thanks, one more thing"
    wes = rows["Wes Waiting"]
    assert wes["last_message_sender"] == "staff" and wes["last_message_delivery_status"] == "failed"  # a failed staff send is visible in the list


def test_preview_is_truncated(biz):
    _conv(biz["business_id"], "Long Lena", "website", [(S.CUSTOMER, "x" * 500, 1)])
    assert len(_list(biz["staff_token"])[0]["last_message_preview"]) == 160


def test_unread_until_opened_and_again_after_a_new_customer_message(world):
    tok, cid = world["staff_token"], world["handoff"]
    row = lambda: next(r for r in _list(tok) if r["id"] == str(cid))  # noqa: E731
    assert row()["unread"] is True
    assert client.post(f"/api/v1/inbox/conversations/{cid}/read", headers=_auth(tok)).status_code == 204
    assert row()["unread"] is False and row()["needs_reply"] is True  # read, but still waiting for a person
    with SessionLocal() as db:
        db.add(Message(conversation_id=cid, sender_type=S.CUSTOMER, content="hello??"))
        db.commit()
    assert row()["unread"] is True


def test_summary_counts_and_tenant_isolation(world):
    resp = client.get("/api/v1/inbox/summary", headers=_auth(world["staff_token"]))
    assert resp.status_code == 200 and resp.json() == {"needs_reply": 2, "handoffs": 2}
    other = client.get("/api/v1/inbox/summary", headers=_auth(world["other_token"]))
    assert other.json() == {"needs_reply": 0, "handoffs": 0}
    assert _list(world["other_token"]) == []  # another business sees none of these conversations
    assert client.post(f"/api/v1/inbox/conversations/{world['handoff']}/read", headers=_auth(world["other_token"])).status_code == 404


def test_auth_and_validation(world):
    assert client.get("/api/v1/inbox/conversations").status_code == 401
    assert client.get("/api/v1/inbox/summary").status_code == 401
    assert client.get("/api/v1/inbox/conversations", params={"tab": "bogus"}, headers=_auth(world["staff_token"])).status_code == 422
    assert client.get("/api/v1/inbox/conversations", params={"channel": "sms"}, headers=_auth(world["staff_token"])).status_code == 422


def test_a_conversation_with_no_messages_is_not_listed(biz):
    with SessionLocal() as db:
        c = Customer(business_id=biz["business_id"], name="Empty")
        db.add(c)
        db.flush()
        db.add(Conversation(business_id=biz["business_id"], customer_id=c.id, channel="website", status="open"))
        db.commit()
    assert _list(biz["staff_token"]) == []


def test_thread_latest_returns_the_newest_window_oldest_first_and_timestamps_are_utc_tagged(biz):
    cid = _conv(biz["business_id"], "Long Thread", "website", [(S.CUSTOMER, f"m{i}", 100 - i) for i in range(30)])
    url = f"/api/v1/inbox/conversations/{cid}/messages"
    newest = client.get(url, params={"limit": 5, "latest": True}, headers=_auth(biz["staff_token"])).json()
    assert [m["content"] for m in newest] == ["m25", "m26", "m27", "m28", "m29"]  # the NEWEST five, still oldest-first
    oldest = client.get(url, params={"limit": 5}, headers=_auth(biz["staff_token"])).json()
    assert [m["content"] for m in oldest] == ["m0", "m1", "m2", "m3", "m4"]
    assert newest[0]["created_at"].endswith("Z") or newest[0]["created_at"].endswith("+00:00")  # never a naive string
    row = _list(biz["staff_token"])[0]
    assert row["last_message_at"].endswith("Z") or row["last_message_at"].endswith("+00:00")

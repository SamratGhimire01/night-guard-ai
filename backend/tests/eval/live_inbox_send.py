"""Live proof for Phase 52 stage 3 against the REAL running server (real HTTP, real DB, real Graph API calls).

    docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python tests/eval/live_inbox_send.py

Throwaway tenant; WhatsApp/Messenger/Instagram integrations carry THROWAWAY tokens and fake recipients, so Meta really is
called and really rejects the send — the point is to show the staff reply goes out on each real channel path and that the
outcome is recorded truthfully (never faked as "delivered"). It NEVER contacts a real customer. Deleted afterwards.
Parts: (1) staff-role 403 vs owner on POST /conversations/{id}/messages; (2) closed 24h window on an old conversation;
(3) a staff reply on WhatsApp / Messenger / Instagram; (4) the website widget receiving a staff reply through its poll.
"""

import uuid

import httpx
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.integration import Integration

BASE = "http://127.0.0.1:8000/api/v1"


def h(token):
    return {"Authorization": f"Bearer {token}"}


def seed(business_id, channel, ref, hours_old=0.05):
    with SessionLocal() as db:
        customer = Customer(business_id=business_id, name=f"Live {channel}")
        db.add(customer)
        db.flush()
        db.add(ChannelIdentity(business_id=business_id, channel=channel, external_ref=ref, customer_id=customer.id))
        conv = Conversation(business_id=business_id, customer_id=customer.id, channel=channel, status="open")
        db.add(conv)
        db.flush()
        db.add(Message(conversation_id=conv.id, sender_type=MessageSenderType.CUSTOMER, content="hello"))
        db.commit()
        cid = conv.id
        db.execute(text("UPDATE messages SET created_at = localtimestamp - make_interval(secs => :s) WHERE conversation_id = :c"),
                   {"s": hours_old * 3600, "c": cid})
        db.commit()
    return cid


def main():
    email = f"inbox-live-{uuid.uuid4().hex[:8]}@example.com"
    r = httpx.post(f"{BASE}/auth/register", json={"business_name": "Inbox Live Probe", "timezone": "UTC", "email": email, "password": "correcthorse1"})
    r.raise_for_status()
    biz = uuid.UUID(r.json()["business_id"])
    owner = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    with SessionLocal() as db:
        staff = BusinessUser(business_id=biz, email=f"staff-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role=BusinessUserRole.STAFF)
        db.add(staff)
        db.add_all([
            Integration(business_id=biz, type="whatsapp", enabled=True, config={"phone_number_id": "1000000000000001", "access_token": "THROWAWAY"}),
            Integration(business_id=biz, type="messenger", enabled=True, config={"page_id": "p1", "page_access_token": "THROWAWAY"}),
            Integration(business_id=biz, type="instagram", enabled=True, config={"ig_account_id": "17840000000000001", "access_token": "THROWAWAY"}),
        ])
        db.commit()
        db.refresh(staff)
        staff_token = create_access_token(user_id=staff.id, business_id=biz, role="staff")
    try:
        print("(1) role restriction on POST /conversations/{id}/messages")
        cid = seed(biz, "website", "x-role-probe")
        for label, tok in (("staff", staff_token), ("owner", owner)):
            resp = httpx.post(f"{BASE}/conversations/{cid}/messages", json={"content": "I am the customer"}, headers=h(tok), timeout=60)
            print(f"    {label:5} -> HTTP {resp.status_code}" + (f"  {resp.json()['error']['message']!r}" if resp.status_code == 403 else ""))
        with SessionLocal() as db:
            n = db.query(Message).filter(Message.conversation_id == cid, Message.content == "I am the customer").count()
        print(f"    'I am the customer' messages stored: {n} (only the owner's call stored one)")

        print("(2) the 24-hour window on an OLD conversation (customer last wrote 30h ago)")
        for channel, ref in (("whatsapp", "9779800000001"), ("messenger", "psid-old"), ("instagram", "igsid-old")):
            cid = seed(biz, channel, ref, hours_old=30)
            info = httpx.get(f"{BASE}/inbox/conversations/{cid}", headers=h(staff_token)).json()
            resp = httpx.post(f"{BASE}/inbox/conversations/{cid}/reply", json={"content": "hi"}, headers=h(staff_token))
            with SessionLocal() as db:
                stored = db.query(Message).filter(Message.conversation_id == cid, Message.sender_type == MessageSenderType.STAFF).count()
            print(f"    {channel:9} can_reply={info['reply']['can_reply']}  reply -> HTTP {resp.status_code}, staff messages stored={stored}, takeover={info['takeover']['active']}")
            print(f"              reason: {info['reply']['reason']}")

        print("(3) a staff reply on each real channel (recent conversation; real call to Meta, throwaway credentials)")
        for channel, ref in (("whatsapp", "0000000000"), ("messenger", "0000000000"), ("instagram", "0000000000")):
            cid = seed(biz, channel, ref)
            resp = httpx.post(f"{BASE}/inbox/conversations/{cid}/reply", json={"content": f"[test] staff reply on {channel}", "client_msg_id": uuid.uuid4().hex},
                              headers=h(staff_token), timeout=60)
            body = resp.json()
            info = httpx.get(f"{BASE}/inbox/conversations/{cid}", headers=h(staff_token)).json()
            print(f"    {channel:9} HTTP {resp.status_code} sender={body['sender_type']} delivery_status={body['delivery_status']} detail={body['delivery_detail']!r} "
                  f"takeover_active={info['takeover']['active']}")

        print("(4) website widget receives a staff reply through its real poll endpoint")
        w = httpx.post(f"{BASE}/widget/{biz}/messages", json={"content": "hi there"}, timeout=90).json()
        with SessionLocal() as db:
            wcid = db.query(Conversation).filter_by(business_id=biz, channel="website").order_by(Conversation.created_at.desc()).first().id
        resp = httpx.post(f"{BASE}/inbox/conversations/{wcid}/reply", json={"content": "Hello from the team (staff)"}, headers=h(staff_token))
        print(f"    reply -> HTTP {resp.status_code} status={resp.json()['delivery_status']} detail={resp.json()['delivery_detail']!r}")
        poll = httpx.get(f"{BASE}/widget/{biz}/updates", params={"session_token": w["session_token"], "after": w["agent_message_id"]}).json()
        print(f"    widget poll -> {[m['content'] for m in poll['messages']]}")
        nxt = httpx.post(f"{BASE}/widget/{biz}/messages", json={"content": "thanks", "session_token": w["session_token"]}, timeout=90).json()
        print(f"    visitor writes again while staff owns it -> response={nxt['response']!r} customer_message_id set={bool(nxt['customer_message_id'])}")
    finally:
        with SessionLocal() as db:
            b = db.get(Business, biz)
            if b is not None:
                db.delete(b)
            db.commit()


main()

"""Instagram gives an account TWO ids: `id` (what people paste as "Instagram Account ID") and `user_id` (the professional id Meta
puts in every webhook's entry[].id). A business that saved only the first had every inbound DM silently dropped ("no business
registered for ig_account_id=…") — found live on the clinic's own account. The resolver now matches either, and saving Instagram
credentials looks the second one up from the token."""

import uuid

import pytest

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.conversation import Conversation, Message
from app.db.models.integration import Integration
from app.services.channels import graph_api
from app.services.channels.instagram_webhook import _resolve_integration

from tests.integration.test_human_takeover import _auth, _post_raw_ig, biz, client, llm, sends  # noqa: F401

TYPED_ID, PROFESSIONAL_ID = "27943000000000001", "17841000000000001"


def _dm(account_id: str) -> dict:
    return {"object": "instagram", "entry": [{"id": account_id, "time": 1, "messaging": [
        {"sender": {"id": "igsid-x"}, "recipient": {"id": account_id}, "timestamp": 1,
         "message": {"mid": f"mid.{uuid.uuid4().hex}", "text": "hello"}}]}]}


@pytest.fixture
def ig_biz(biz):
    with SessionLocal() as db:
        row = db.query(Integration).filter_by(business_id=biz["business_id"], type="instagram").one()
        row.config = {"ig_account_id": TYPED_ID, "access_token": "IGAA-throwaway"}  # only the typed id, as on the clinic
        db.commit()
    return biz


def test_a_dm_addressed_to_the_professional_id_is_dropped_without_the_alias_and_handled_with_it(ig_biz, llm, sends):
    assert _post_raw_ig(_dm(PROFESSIONAL_ID)).status_code == 200  # the bug: unknown account -> silently dropped
    with SessionLocal() as db:
        assert db.query(Conversation).filter_by(business_id=ig_biz["business_id"]).count() == 0
        assert _resolve_integration(db, ig_account_id=PROFESSIONAL_ID) is None

        row = db.query(Integration).filter_by(business_id=ig_biz["business_id"], type="instagram").one()
        row.config = {**row.config, "ig_user_id": PROFESSIONAL_ID}
        db.commit()
        assert _resolve_integration(db, ig_account_id=PROFESSIONAL_ID).business_id == ig_biz["business_id"]
        assert _resolve_integration(db, ig_account_id=TYPED_ID).business_id == ig_biz["business_id"]  # typed id still works
        assert _resolve_integration(db, ig_account_id="17841999999999999") is None  # an unrelated account still doesn't

    assert _post_raw_ig(_dm(PROFESSIONAL_ID)).status_code == 200
    with SessionLocal() as db:
        c = db.query(Conversation).filter_by(business_id=ig_biz["business_id"], channel="instagram").one()
        assert db.query(Message).filter_by(conversation_id=c.id).count() == 2  # the customer's DM + the AI's reply
    assert [ch for ch, _ in sends["send"]] == ["instagram"]


def test_saving_instagram_credentials_stores_the_professional_id_looked_up_from_the_token(biz, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "app.services.integration_service.fetch_instagram_user_id",
        lambda *, access_token, api_version: seen.update(token=access_token) or PROFESSIONAL_ID,
    )
    resp = client.post("/api/v1/integrations", headers=_auth(biz["owner_token"]),
                       json={"type": "instagram", "config": {"ig_account_id": TYPED_ID, "access_token": "IGAA-new"}, "enabled": True})
    assert resp.status_code in (200, 201), resp.text
    assert seen["token"] == "IGAA-new"
    with SessionLocal() as db:
        cfg = db.query(Integration).filter_by(business_id=biz["business_id"], type="instagram").one().config
    assert cfg == {"ig_account_id": TYPED_ID, "access_token": "IGAA-new", "ig_user_id": PROFESSIONAL_ID}
    assert "access_token" not in resp.json()["config"]  # the secret is never echoed back


def test_a_failed_lookup_never_blocks_saving(biz, monkeypatch):
    monkeypatch.setattr("app.services.integration_service.fetch_instagram_user_id", lambda **kw: None)
    resp = client.post("/api/v1/integrations", headers=_auth(biz["owner_token"]),
                       json={"type": "instagram", "config": {"ig_account_id": TYPED_ID, "access_token": "IGAA-new"}, "enabled": True})
    assert resp.status_code in (200, 201)
    with SessionLocal() as db:
        assert "ig_user_id" not in db.query(Integration).filter_by(business_id=biz["business_id"], type="instagram").one().config


def test_fetch_instagram_user_id_uses_the_tokens_own_host_and_survives_failures(monkeypatch):
    import io, json, urllib.error, urllib.request

    urls = []

    class R:
        def __init__(self, p): self.p = p
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(self.p).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: urls.append(req.full_url) or R({"user_id": 17841000000000001, "id": "1"}))
    assert graph_api.fetch_instagram_user_id(access_token="IGAA-x", api_version="v25.0") == "17841000000000001"
    assert urls[0].startswith("https://graph.instagram.com/v25.0/me?fields=user_id")  # IGAA token -> the Instagram host

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert graph_api.fetch_instagram_user_id(access_token="IGAA-x", api_version="v25.0") is None
    assert graph_api.fetch_instagram_user_id(access_token="", api_version="v25.0") is None

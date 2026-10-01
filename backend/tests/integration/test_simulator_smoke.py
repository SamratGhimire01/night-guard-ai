"""Conversation simulator against the real engine and DB, with a stubbed LLM: businesses are created, a scenario is
played turn by turn, every reply is scored, and all SIM rows are gone afterwards."""

import json

from app.db.database import SessionLocal
from app.db.models.business import Business
from tests.eval.simulator import run as sim
from tests.eval.simulator.businesses import BY_KEY
from tests.eval.simulator.scenarios import BY_ID


class _Chat:
    def chat(self, messages):
        return json.dumps({"intent": "pricing_question", "response": "Teeth Cleaning ko 1500 parcha hajur.",
                           "message_language": "ne_roman", "needs_human_handoff": False})


class _Embed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


def test_play_scores_every_turn_and_cleans_up(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _Chat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _Embed())

    db = SessionLocal()
    try:
        business = sim.create_business(db, BY_KEY["dental"], with_knowledge=False)
        record = sim.play(business.id, BY_KEY["dental"], BY_ID["greet_price"], {}, None, 0)
        assert [t["customer"] for t in record["turns"]] == ["hlo", "Teeth Cleaning kati parcha?", "ok thank you"]
        assert all("error" not in t and t["reply"] for t in record["turns"])
        price_turn = record["turns"][1]
        assert price_turn["checks"] == [] and "ok" in price_turn
        # the stub says the same thing three times: the history-aware lint must notice the repeat
        assert any(f.startswith("repeat") for t in record["turns"] for f in t["lint"])
    finally:
        sim.delete_sim_businesses(db)
        assert db.query(Business).filter(Business.name.like(sim.SIM_PREFIX + "%")).count() == 0
        db.close()

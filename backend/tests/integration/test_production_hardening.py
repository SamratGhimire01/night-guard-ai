"""Production hardening: security headers, startup config checks, development-only pages hidden in production."""

import pytest
from fastapi.testclient import TestClient

import app.api.routes.widget as widget_module
from app.core.config import Settings
from app.core.production_checks import UnsafeProductionConfig, enforce, problems
from app.main import app

client = TestClient(app)

_GOOD = dict(
    database_url="postgresql://u:p@db/x",
    secret_key="4f9c2d7a8b1e6f3c0a5d9e2b7c4f1a8d6e3b0c9f",
    environment="production",
    dashboard_cors_origins="https://app.nightguard.example",
    dashboard_base_url="https://app.nightguard.example",
    backend_base_url="https://api.nightguard.example",
    esewa_base_url="https://epay.esewa.com.np",
    esewa_product_code="NP-ES-CLINIC",
    khalti_base_url="https://khalti.com",
    gmail_address="alerts@nightguard.example",
    gmail_app_password="abcd efgh ijkl mnop",
)


def _settings(**overrides):
    return Settings(**{**_GOOD, **overrides})


def test_every_response_carries_the_protective_headers():
    resp = client.get("/api/v1/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_a_route_that_sets_its_own_header_keeps_it():
    # widget.js is a script loaded by other sites; nosniff stays, nothing else gets duplicated
    resp = client.get("/widget.js")
    assert resp.headers.get_list("x-content-type-options") == ["nosniff"]


def test_a_good_production_config_starts():
    enforce(_settings())
    critical, warnings = problems(_settings())
    assert critical == [] and warnings == []


@pytest.mark.parametrize("key", ["short", "change-me-change-me-change-me-change-me", "x" * 20])
def test_production_refuses_a_weak_secret_key(key):
    with pytest.raises(UnsafeProductionConfig):
        enforce(_settings(secret_key=key))


def test_production_refuses_wildcard_dashboard_cors():
    with pytest.raises(UnsafeProductionConfig):
        enforce(_settings(dashboard_cors_origins="*"))


def test_production_warns_about_sandbox_payments_and_tunnel_links():
    _, warnings = problems(_settings(esewa_base_url="https://rc-epay.esewa.com.np", backend_base_url="https://abc.ngrok-free.dev"))
    assert any("eSewa is on its test sandbox" in w for w in warnings)
    assert any("BACKEND_BASE_URL" in w for w in warnings)


def test_development_has_no_production_checks():
    assert problems(_settings(environment="development", secret_key="dev")) == ([], [])


def test_development_test_pages_are_hidden_in_production(monkeypatch):
    assert client.get("/test-chat").status_code == 200
    monkeypatch.setattr(widget_module.app_settings, "environment", "production")
    assert client.get("/test-chat").status_code == 404
    assert client.get("/widget-demo").status_code == 404
    assert client.get("/widget.js").status_code == 200


def test_the_premium_test_scaffolding_is_gone():
    assert client.get("/api/v1/premium-test/ping").status_code == 404
    import app.services.conversation.orchestrator as orchestrator

    assert not hasattr(orchestrator, "_PREMIUM_TEST_TRIGGER")

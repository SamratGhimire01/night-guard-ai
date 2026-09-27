"""Regression tests for app.core.public_url — the guard that stops a customer-facing
link from ever being built from a localhost/dev-tunnel address while running in
production (see that module's docstring for the incident this fixes)."""
import pytest

from app.core.config import settings
from app.core.public_url import UnsafePublicURLError, public_backend_base_url


def test_dev_tunnel_and_localhost_are_fine_in_development(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    for url in (
        "http://localhost:8010",
        "http://127.0.0.1:8010",
        "https://unfiltrated-sharla-futile.ngrok-free.dev",
        "https://abcd1234.ngrok.io",
        "https://abcd1234.ngrok-free.app",
    ):
        monkeypatch.setattr(settings, "backend_base_url", url)
        assert public_backend_base_url() == url


def test_a_real_domain_is_fine_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "backend_base_url", "https://api.nightguard.ai")
    assert public_backend_base_url() == "https://api.nightguard.ai"


def test_localhost_and_dev_tunnels_are_refused_in_production(monkeypatch, caplog):
    monkeypatch.setattr(settings, "environment", "production")
    for url in (
        "http://localhost:8010",
        "http://127.0.0.1:8010",
        "https://unfiltrated-sharla-futile.ngrok-free.dev",
        "https://abcd1234.ngrok.io",
        "https://abcd1234.ngrok-free.app",
    ):
        monkeypatch.setattr(settings, "backend_base_url", url)
        with caplog.at_level("CRITICAL"):
            with pytest.raises(UnsafePublicURLError):
                public_backend_base_url()
        assert any("refusing to build a customer-facing link" in r.message for r in caplog.records)
        caplog.clear()


def test_a_hostname_that_merely_contains_ngrok_is_not_falsely_flagged(monkeypatch):
    """The regex anchors the WHOLE hostname -- a real domain that happens to contain
    "ngrok" as a substring (e.g. a business literally named ngrok-something.com) must
    not be refused; only an actual *.ngrok.{dev,app,io} host is."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "backend_base_url", "https://myngrokreseller.com")
    assert public_backend_base_url() == "https://myngrokreseller.com"

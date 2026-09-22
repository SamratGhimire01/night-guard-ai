"""Shared pytest fixtures."""

import smtplib

import pytest


class _NoNetworkSMTP:
    """Accepts everything, sends nothing. Until Phase 19 the suite made REAL Gmail SMTP sends through the platform's
    GMAIL_ADDRESS (57 per full run — booking/check-in/conversation tests with @example.com customers), enough over a few
    runs to exhaust that account's daily sending limit and make real customers' resend_confirmation emails fail with
    "550 5.4.5 Daily user sending limit exceeded". No test needs a real delivery; one that wants to inspect or fail a send
    installs its own fake with monkeypatch, which overrides this."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, *args, **kwargs):
        pass

    def send_message(self, message):
        return {}


@pytest.fixture(autouse=True)
def _never_send_real_email(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _NoNetworkSMTP)

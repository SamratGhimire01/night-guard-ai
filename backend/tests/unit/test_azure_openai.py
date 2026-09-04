"""Urgent fix (real 500 found live, PHASE_STATUS.md): a real, live-captured
`httpx.ConnectError: [Errno -2] Name or service not known` (a transient DNS
failure reaching the Azure Foundry endpoint) propagated straight past
`_post`'s old response-status-only retry loop as an unhandled exception,
producing a raw 500 on the widget endpoint. These tests exercise `_post`
directly, independent of any live network, to prove the fix: a
`httpx.TransportError` on `httpx.post` itself (not just an HTTP error status)
is now retried with the same budget as the pre-existing 404 case, and only
raises (as a `RuntimeError`, same as before) once that budget is exhausted."""

from unittest.mock import patch

import httpx
import pytest

from app.llm.azure_openai import _MAX_ATTEMPTS, _post


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_post_retries_transport_error_and_recovers():
    """A transient connection failure on the FIRST attempt (the exact real
    incident) is retried and a subsequent successful attempt is returned —
    the customer never needs to resend, unlike the original bug."""
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("[Errno -2] Name or service not known")
        return _FakeResponse(200, {"ok": True})

    with patch("app.llm.azure_openai.httpx.post", side_effect=flaky), patch("app.llm.azure_openai.time.sleep"):
        result = _post("embeddings", {"input": ["x"]})

    assert result == {"ok": True}
    assert calls["n"] == 2


def test_post_raises_runtime_error_after_exhausting_retries_on_sustained_transport_error():
    """A SUSTAINED outage (every attempt fails) exhausts the real retry
    budget and raises RuntimeError — never lets the raw httpx exception (with
    its embedded URL) escape uncaught, same discipline as the pre-existing
    404 case."""
    calls = {"n": 0}

    def always_fail(*args, **kwargs):
        calls["n"] += 1
        raise httpx.ConnectError("[Errno -2] Name or service not known")

    with patch("app.llm.azure_openai.httpx.post", side_effect=always_fail), patch("app.llm.azure_openai.time.sleep"):
        with pytest.raises(RuntimeError) as exc_info:
            _post("embeddings", {"input": ["x"]})

    assert calls["n"] == _MAX_ATTEMPTS
    # Never leaks the raw httpx exception message / request URL (Phase 9's
    # own real leak-and-fix, extended here to the transport-error path).
    assert "services.ai.azure.com" not in str(exc_info.value)
    assert "ConnectError" in str(exc_info.value)


def test_post_still_retries_the_pre_existing_404_case_unaffected():
    """Regression: the original 404-propagation-quirk retry (Phase 6) is
    completely unchanged by this fix."""
    calls = {"n": 0}

    def flaky_404(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(404)
        return _FakeResponse(200, {"ok": True})

    with patch("app.llm.azure_openai.httpx.post", side_effect=flaky_404), patch("app.llm.azure_openai.time.sleep"):
        result = _post("embeddings", {"input": ["x"]})

    assert result == {"ok": True}
    assert calls["n"] == 3


def test_post_does_not_retry_a_genuine_non_404_error_status():
    """Regression: a real 400/500 HTTP error status (not a transport-level
    failure) still raises immediately, never retried — unchanged."""
    calls = {"n": 0}

    def bad_request(*args, **kwargs):
        calls["n"] += 1
        return _FakeResponse(400)

    with patch("app.llm.azure_openai.httpx.post", side_effect=bad_request):
        with pytest.raises(RuntimeError, match="HTTP 400"):
            _post("embeddings", {"input": ["x"]})

    assert calls["n"] == 1

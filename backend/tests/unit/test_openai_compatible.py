"""Phase 39: the shared retry/error-classification logic behind both
app/llm/xai.py and app/llm/groq.py (app/llm/_openai_compatible.py). Same
structure as tests/unit/test_azure_openai.py, adapted for the retryable-
status set both these OpenAI-compatible REST APIs actually use (429/5xx),
not Azure Foundry's own 404 propagation quirk."""

from unittest.mock import patch

import httpx
import pytest

from app.llm._openai_compatible import MAX_ATTEMPTS, post


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _post(**overrides):
    kwargs = {
        "provider": "xai",
        "base_url": "https://api.example.test",
        "api_key": "test-key",
        "path": "chat/completions",
        "body": {"messages": []},
    }
    kwargs.update(overrides)
    return post(**kwargs)


def test_post_retries_transport_error_and_recovers():
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("[Errno -2] Name or service not known")
        return _FakeResponse(200, {"ok": True})

    with patch("app.llm._openai_compatible.httpx.post", side_effect=flaky), patch(
        "app.llm._openai_compatible.time.sleep"
    ):
        result = _post()

    assert result == {"ok": True}
    assert calls["n"] == 2


def test_post_raises_runtime_error_after_exhausting_retries_on_sustained_transport_error():
    calls = {"n": 0}

    def always_fail(*args, **kwargs):
        calls["n"] += 1
        raise httpx.ConnectError("[Errno -2] Name or service not known")

    with patch("app.llm._openai_compatible.httpx.post", side_effect=always_fail), patch(
        "app.llm._openai_compatible.time.sleep"
    ):
        with pytest.raises(RuntimeError) as exc_info:
            _post()

    assert calls["n"] == MAX_ATTEMPTS
    assert "api.example.test" not in str(exc_info.value)
    assert "ConnectError" in str(exc_info.value)


def test_post_retries_a_429_rate_limit_and_recovers():
    calls = {"n": 0}

    def flaky_429(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(429)
        return _FakeResponse(200, {"ok": True})

    with patch("app.llm._openai_compatible.httpx.post", side_effect=flaky_429), patch(
        "app.llm._openai_compatible.time.sleep"
    ):
        result = _post()

    assert result == {"ok": True}
    assert calls["n"] == 3


def test_post_retries_a_502_and_recovers():
    calls = {"n": 0}

    def flaky_502(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return _FakeResponse(502)
        return _FakeResponse(200, {"ok": True})

    with patch("app.llm._openai_compatible.httpx.post", side_effect=flaky_502), patch(
        "app.llm._openai_compatible.time.sleep"
    ):
        result = _post()

    assert result == {"ok": True}
    assert calls["n"] == 2


def test_post_does_not_retry_a_genuine_non_retryable_error_status():
    calls = {"n": 0}

    def bad_request(*args, **kwargs):
        calls["n"] += 1
        return _FakeResponse(400)

    with patch("app.llm._openai_compatible.httpx.post", side_effect=bad_request):
        with pytest.raises(RuntimeError, match="HTTP 400"):
            _post()

    assert calls["n"] == 1


def test_post_does_not_retry_a_403_permission_denied():
    """Regression: this is the REAL failure mode hit live against the xAI
    account this phase (billing/spend-limit gate, PHASE_STATUS.md Phase 39)
    -- proves it's correctly classified permanent, not retried."""
    calls = {"n": 0}

    def forbidden(*args, **kwargs):
        calls["n"] += 1
        return _FakeResponse(403)

    with patch("app.llm._openai_compatible.httpx.post", side_effect=forbidden):
        with pytest.raises(RuntimeError, match="HTTP 403"):
            _post()

    assert calls["n"] == 1

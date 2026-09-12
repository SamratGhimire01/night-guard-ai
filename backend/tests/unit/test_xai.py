"""Phase 39: GrokChatProvider (app/llm/xai.py) itself -- retry/error
discipline lives in app/llm/_openai_compatible.py and is covered by
tests/unit/test_openai_compatible.py; this proves GrokChatProvider wires the
right endpoint/key/model into that shared call and extracts the real reply
text correctly."""

from unittest.mock import patch

from app.llm.xai import GrokChatProvider


def test_chat_calls_the_shared_post_with_xai_settings_and_returns_the_reply_text():
    with patch("app.llm.xai.settings") as fake_settings, patch("app.llm.xai.post") as fake_post:
        fake_settings.xai_endpoint = "https://api.x.ai/v1"
        fake_settings.xai_api_key = "test-xai-key"
        fake_settings.xai_chat_model = "grok-4"
        fake_post.return_value = {"choices": [{"message": {"content": "Hello there"}}]}

        result = GrokChatProvider().chat([{"role": "user", "content": "hi"}])

        assert result == "Hello there"
        fake_post.assert_called_once_with(
            provider="xai",
            base_url="https://api.x.ai/v1",
            api_key="test-xai-key",
            path="chat/completions",
            body={"messages": [{"role": "user", "content": "hi"}], "model": "grok-4"},
        )


def test_chat_returns_empty_string_for_a_null_content_reply():
    with patch("app.llm.xai.settings"), patch("app.llm.xai.post") as fake_post:
        fake_post.return_value = {"choices": [{"message": {"content": None}}]}
        assert GrokChatProvider().chat([]) == ""

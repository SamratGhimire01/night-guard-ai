"""Phase 39: GroqChatProvider (app/llm/groq.py) -- same discipline as
test_xai.py. Retry/error handling itself is covered by
test_openai_compatible.py; this proves GroqChatProvider wires the right
endpoint/key/model into that shared call and extracts the real reply text."""

from unittest.mock import patch

from app.llm.groq import GroqChatProvider


def test_chat_calls_the_shared_post_with_groq_settings_and_returns_the_reply_text():
    with patch("app.llm.groq.settings") as fake_settings, patch("app.llm.groq.post") as fake_post:
        fake_settings.groq_endpoint = "https://api.groq.com/openai/v1"
        fake_settings.groq_api_key = "test-groq-key"
        fake_settings.groq_chat_model = "openai/gpt-oss-120b"
        fake_post.return_value = {"choices": [{"message": {"content": "Hello there"}}]}

        result = GroqChatProvider().chat([{"role": "user", "content": "hi"}])

        assert result == "Hello there"
        fake_post.assert_called_once_with(
            provider="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key="test-groq-key",
            path="chat/completions",
            body={"messages": [{"role": "user", "content": "hi"}], "model": "openai/gpt-oss-120b"},
        )


def test_chat_returns_empty_string_for_a_null_content_reply():
    with patch("app.llm.groq.settings"), patch("app.llm.groq.post") as fake_post:
        fake_post.return_value = {"choices": [{"message": {"content": None}}]}
        assert GroqChatProvider().chat([]) == ""

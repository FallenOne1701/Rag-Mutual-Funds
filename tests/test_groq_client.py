"""Phase 3.1 — shared Groq client (Architecture §11.2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.config.settings import Settings
from src.generation.groq_client import (
    ChatMessage,
    ChatResult,
    GroqAPIError,
    GroqClient,
    GroqConfigError,
    get_groq_client,
    reset_groq_client_cache,
)


def _settings(**kwargs) -> Settings:
    base = {
        "groq_api_key": "gsk_test_key_not_real",
        "groq_model": "openai/gpt-oss-120b",
        "groq_model_fast": "openai/gpt-oss-20b",
        "groq_max_tokens": 256,
        "groq_temperature": 0.1,
    }
    base.update(kwargs)
    return Settings(**base)


def _fake_response(text: str, model: str = "openai/gpt-oss-120b") -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
    )


def test_missing_api_key_raises_config_error():
    client = GroqClient(settings=_settings(groq_api_key=""))
    with pytest.raises(GroqConfigError, match="GROQ_API_KEY"):
        client.chat([{"role": "user", "content": "hi"}])


def test_placeholder_api_key_rejected():
    client = GroqClient(settings=_settings(groq_api_key="your_groq_api_key_here"))
    with pytest.raises(GroqConfigError):
        client.chat([ChatMessage(role="user", content="hi")])


def test_chat_uses_primary_model_by_default():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response(
        "The expense ratio is 1.02%."
    )
    client = GroqClient(settings=_settings(), client=sdk)
    result = client.chat(
        [
            {"role": "system", "content": "Facts only."},
            {"role": "user", "content": "Expense ratio?"},
        ]
    )
    assert isinstance(result, ChatResult)
    assert result.ok
    assert result.text == "The expense ratio is 1.02%."
    assert result.model == "openai/gpt-oss-120b"
    assert result.prompt_tokens == 10
    call_kwargs = sdk.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "openai/gpt-oss-120b"
    assert call_kwargs["temperature"] == 0.1
    assert call_kwargs["max_tokens"] == 256


def test_chat_use_fast_selects_fast_model():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response(
        "ok", model="openai/gpt-oss-20b"
    )
    client = GroqClient(settings=_settings(), client=sdk)
    result = client.chat(
        [{"role": "user", "content": "retry"}],
        use_fast=True,
    )
    assert result.model == "openai/gpt-oss-20b"
    assert (
        sdk.chat.completions.create.call_args.kwargs["model"]
        == "openai/gpt-oss-20b"
    )


def test_explicit_model_overrides_use_fast():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response("x", model="custom")
    client = GroqClient(settings=_settings(), client=sdk)
    client.chat(
        [{"role": "user", "content": "hi"}],
        model="custom-model",
        use_fast=True,
    )
    assert sdk.chat.completions.create.call_args.kwargs["model"] == "custom-model"


def test_rate_limit_retries_once_then_succeeds(monkeypatch):
    sdk = MagicMock()
    rate_err = Exception("Error code: 429 - rate limit")
    rate_err.status_code = 429  # type: ignore[attr-defined]
    sdk.chat.completions.create.side_effect = [
        rate_err,
        _fake_response("recovered"),
    ]
    slept: list[float] = []
    monkeypatch.setattr(
        "src.generation.groq_client.time.sleep",
        lambda s: slept.append(s),
    )
    client = GroqClient(settings=_settings(), client=sdk)
    result = client.chat([{"role": "user", "content": "hi"}])
    assert result.text == "recovered"
    assert slept == [1.0]
    assert sdk.chat.completions.create.call_count == 2


def test_rate_limit_exhausted_raises_api_error(monkeypatch):
    sdk = MagicMock()
    rate_err = Exception("429 rate limit")
    rate_err.status_code = 429  # type: ignore[attr-defined]
    sdk.chat.completions.create.side_effect = rate_err
    monkeypatch.setattr("src.generation.groq_client.time.sleep", lambda s: None)
    client = GroqClient(settings=_settings(), client=sdk)
    with pytest.raises(GroqAPIError, match="Groq chat failed"):
        client.chat([{"role": "user", "content": "hi"}])
    assert sdk.chat.completions.create.call_count == 2


def test_non_rate_limit_fails_without_retry():
    sdk = MagicMock()
    sdk.chat.completions.create.side_effect = RuntimeError("boom")
    client = GroqClient(settings=_settings(), client=sdk)
    with pytest.raises(GroqAPIError, match="boom"):
        client.chat([{"role": "user", "content": "hi"}])
    assert sdk.chat.completions.create.call_count == 1


def test_empty_messages_rejected():
    client = GroqClient(settings=_settings(), client=MagicMock())
    with pytest.raises(ValueError, match="empty"):
        client.chat([])


def test_get_groq_client_singleton():
    reset_groq_client_cache()
    a = get_groq_client()
    b = get_groq_client()
    assert a is b
    reset_groq_client_cache()

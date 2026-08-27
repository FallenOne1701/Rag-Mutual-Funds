"""
Groq SDK wrapper — sole LLM client for this project (Architecture §11.2).

Shared by Generator (Phase 3.2+) and optional Query Classifier (Phase 4).
No other LLM vendor. Embeddings stay local (see Embedding Service).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence

from src.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# Architecture: one backoff retry on rate limit, then caller falls back.
_RATE_LIMIT_STATUS = 429
_RETRY_SLEEP_SECONDS = 1.0


class GroqClientError(Exception):
    """Base error for Groq client failures."""


class GroqConfigError(GroqClientError):
    """Missing or invalid configuration (e.g. empty GROQ_API_KEY)."""


class GroqAPIError(GroqClientError):
    """Groq API call failed after retries (or non-retryable error)."""


class GroqBudgetError(GroqClientError):
    """Free-tier request / token budget is spent; caller should fall back."""


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ChatResult:
    """Normalized chat completion payload for Generator / Classifier."""

    text: str
    model: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def ok(self) -> bool:
        return bool(self.text and self.text.strip())


def _as_messages(
    messages: Sequence[ChatMessage | dict[str, str]],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        if isinstance(m, ChatMessage):
            out.append(m.to_dict())
        else:
            role = str(m.get("role") or "").strip()
            content = str(m.get("content") or "")
            if not role:
                raise ValueError("Each message needs a non-empty 'role'")
            out.append({"role": role, "content": content})
    if not out:
        raise ValueError("messages must not be empty")
    return out


def _strip_reasoning(text: str) -> str:
    """Drop `<think>` blocks some Groq reasoning models emit inline."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    # Unterminated block (truncated by max_tokens) leaves nothing usable
    cleaned = re.sub(r"<think>.*\Z", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _is_rate_limit(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status == _RATE_LIMIT_STATUS:
        return True
    # groq / httpx style
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == _RATE_LIMIT_STATUS:
        return True
    name = type(exc).__name__.lower()
    if "ratelimit" in name or "rate_limit" in name:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "429" in msg


class GroqClient:
    """
    Thin wrapper around the official `groq` SDK.

    - Primary model: settings.groq_model (`openai/gpt-oss-120b`)
    - Fast model: settings.groq_model_fast (`openai/gpt-oss-20b`) via use_fast=True
    - On HTTP 429: sleep once, retry once; then raise GroqAPIError
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: Any | None = None,
        budget: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._budget = budget

    @property
    def budget(self) -> Any | None:
        """Shared free-tier budget, unless disabled in settings."""
        if self._budget is None and self.settings.groq_budget_enabled:
            from src.generation.budget import get_budget

            self._budget = get_budget()
        return self._budget

    @property
    def primary_model(self) -> str:
        return self.settings.groq_model

    @property
    def fast_model(self) -> str:
        return self.settings.groq_model_fast

    def _require_api_key(self) -> str:
        key = (self.settings.groq_api_key or "").strip()
        if not key or key.startswith("your_groq"):
            raise GroqConfigError(
                "GROQ_API_KEY is missing or unset. "
                "Copy .env.example to .env and set a real Groq API key."
            )
        return key

    def _get_sdk(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise GroqConfigError(
                "The 'groq' package is not installed. Run: pip install groq"
            ) from exc
        self._client = Groq(api_key=self._require_api_key())
        return self._client

    def chat(
        self,
        messages: Sequence[ChatMessage | dict[str, str]],
        *,
        model: str | None = None,
        use_fast: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """
        Create a chat completion.

        Prefer `use_fast=True` for validator retry / optional classification.
        Explicit `model=` overrides both.
        """
        resolved_model = model or (
            self.fast_model if use_fast else self.primary_model
        )
        temp = (
            self.settings.groq_temperature
            if temperature is None
            else temperature
        )
        tokens = (
            self.settings.groq_max_tokens
            if max_tokens is None
            else max_tokens
        )
        payload = _as_messages(messages)
        # Ensure key is present even when injecting a fake client in tests
        # that still construct via settings — real SDK path checks again.
        if self._client is None:
            self._require_api_key()

        budget = self.budget
        if budget is not None:
            from src.generation.budget import GroqBudgetExceeded, estimate_tokens

            try:
                budget.check(estimate_tokens(payload, tokens))
            except GroqBudgetExceeded as exc:
                raise GroqBudgetError(str(exc)) from exc

        last_exc: BaseException | None = None
        for attempt in range(2):
            try:
                result = self._create_once(
                    payload,
                    model=resolved_model,
                    temperature=temp,
                    max_tokens=tokens,
                )
                if budget is not None:
                    budget.record(
                        (result.prompt_tokens or 0) + (result.completion_tokens or 0)
                    )
                return result
            except GroqConfigError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if budget is not None:
                    budget.record(0)  # failed call still consumes a request slot
                if attempt == 0 and _is_rate_limit(exc):
                    logger.warning(
                        "Groq rate limit (429); retrying once after %.1fs",
                        _RETRY_SLEEP_SECONDS,
                    )
                    time.sleep(_RETRY_SLEEP_SECONDS)
                    continue
                break

        raise GroqAPIError(
            f"Groq chat failed (model={resolved_model}): {last_exc}"
        ) from last_exc

    def _create_once(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ChatResult:
        sdk = self._get_sdk()
        response = sdk.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        text = _strip_reasoning(choice.message.content or "")
        usage = getattr(response, "usage", None)
        return ChatResult(
            text=text,
            model=getattr(response, "model", None) or model,
            finish_reason=getattr(choice, "finish_reason", None),
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=(
                getattr(usage, "completion_tokens", None) if usage else None
            ),
        )


def get_groq_client() -> GroqClient:
    """Process-wide Groq client (settings from `.env`)."""
    return _cached_groq_client()


@lru_cache
def _cached_groq_client() -> GroqClient:
    return GroqClient()


def reset_groq_client_cache() -> None:
    """Clear singleton (tests / settings reload)."""
    _cached_groq_client.cache_clear()

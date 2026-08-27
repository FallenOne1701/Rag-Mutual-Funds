"""Groq free-tier budget tests (Phase 4)."""

from __future__ import annotations

import pytest

from src.generation.budget import GroqBudget, GroqBudgetExceeded, estimate_tokens


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _budget(clock: _Clock, **kwargs) -> GroqBudget:
    defaults = dict(
        requests_per_minute=30,
        requests_per_day=1000,
        tokens_per_minute=8000,
        tokens_per_day=200_000,
    )
    defaults.update(kwargs)
    return GroqBudget(clock=clock, **defaults)


def test_estimate_includes_prompt_and_completion_allowance() -> None:
    messages = [{"role": "user", "content": "x" * 400}]
    assert estimate_tokens(messages, 512) == 100 + 512


def test_under_budget_passes() -> None:
    b = _budget(_Clock())
    b.check(600)
    b.record(600)
    assert b.snapshot().tokens_minute == 600


def test_tokens_per_minute_is_the_binding_limit() -> None:
    clock = _Clock()
    b = _budget(clock)
    for _ in range(12):  # 12 x 600 = 7200 tokens, still only 12 of 30 requests
        b.check(600)
        b.record(600)
    with pytest.raises(GroqBudgetExceeded) as exc:
        b.check(1000)
    assert exc.value.limit == "tokens_per_minute"
    assert b.snapshot().requests_minute == 12


def test_minute_window_rolls_off() -> None:
    clock = _Clock()
    b = _budget(clock, tokens_per_minute=1000)
    b.record(900)
    with pytest.raises(GroqBudgetExceeded):
        b.check(500)
    clock.advance(61)
    b.check(500)  # minute window cleared
    assert b.snapshot().tokens_minute == 0
    assert b.snapshot().tokens_day == 900


def test_daily_token_limit() -> None:
    clock = _Clock()
    b = _budget(clock, tokens_per_day=1500, tokens_per_minute=100_000)
    b.record(1400)
    with pytest.raises(GroqBudgetExceeded) as exc:
        b.check(200)
    assert exc.value.limit == "tokens_per_day"


def test_requests_per_minute_limit() -> None:
    clock = _Clock()
    b = _budget(clock, requests_per_minute=2, tokens_per_minute=100_000)
    b.record(1)
    b.record(1)
    with pytest.raises(GroqBudgetExceeded) as exc:
        b.check(1)
    assert exc.value.limit == "requests_per_minute"


def test_client_raises_budget_error_instead_of_calling_groq() -> None:
    from src.config.settings import Settings
    from src.generation.groq_client import GroqBudgetError, GroqClient

    class _Sdk:
        def __init__(self) -> None:
            self.calls = 0

        class _Completions:
            def __init__(self, outer) -> None:  # noqa: ANN001
                self.outer = outer

            def create(self, **kwargs):  # noqa: ANN003
                self.outer.calls += 1
                raise AssertionError("Groq must not be called when over budget")

        @property
        def chat(self):  # noqa: ANN201
            outer = self

            class _Chat:
                completions = _Sdk._Completions(outer)

            return _Chat()

    sdk = _Sdk()
    clock = _Clock()
    spent = _budget(clock, tokens_per_minute=100)
    spent.record(100)

    client = GroqClient(
        settings=Settings(groq_api_key="gsk_test"),
        client=sdk,
        budget=spent,
    )
    with pytest.raises(GroqBudgetError):
        client.chat([{"role": "user", "content": "hello"}])
    assert sdk.calls == 0

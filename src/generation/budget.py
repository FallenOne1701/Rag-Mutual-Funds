"""
Groq free-tier budget (Phase 4).

`openai/gpt-oss-120b` allows 30 requests/min, 1,000/day, 8,000 tokens/min and
200,000 tokens/day. Tokens per minute binds first, so the client checks an
estimate before each call and records actual usage after. When the budget is
spent we raise instead of calling Groq, and the caller degrades to a Groww
scheme-page link (Architecture: degrade, don't queue).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque

from src.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_MINUTE = 60.0
_DAY = 24 * 60 * 60.0

# Rough chars-per-token for the pre-call estimate; usage is reconciled after.
_CHARS_PER_TOKEN = 4


class GroqBudgetExceeded(Exception):
    """Raised before a call that would breach the configured Groq quota."""

    def __init__(self, limit: str, message: str) -> None:
        super().__init__(message)
        self.limit = limit


@dataclass(frozen=True)
class BudgetSnapshot:
    requests_minute: int
    requests_day: int
    tokens_minute: int
    tokens_day: int

    def to_dict(self) -> dict[str, int]:
        return {
            "requests_minute": self.requests_minute,
            "requests_day": self.requests_day,
            "tokens_minute": self.tokens_minute,
            "tokens_day": self.tokens_day,
        }


def estimate_tokens(messages: Any, max_tokens: int) -> int:
    """Prompt estimate + the full completion allowance (reasoning included)."""
    chars = 0
    try:
        for m in messages:
            content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            chars += len(str(content or ""))
    except TypeError:
        chars = 0
    return max(1, chars // _CHARS_PER_TOKEN) + max(0, int(max_tokens))


class GroqBudget:
    """Sliding-window counter for requests and tokens per minute and per day."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        requests_per_minute: int | None = None,
        requests_per_day: int | None = None,
        tokens_per_minute: int | None = None,
        tokens_per_day: int | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        cfg = settings or get_settings()
        self.requests_per_minute = (
            cfg.groq_requests_per_minute if requests_per_minute is None else requests_per_minute
        )
        self.requests_per_day = (
            cfg.groq_requests_per_day if requests_per_day is None else requests_per_day
        )
        self.tokens_per_minute = (
            cfg.groq_tokens_per_minute if tokens_per_minute is None else tokens_per_minute
        )
        self.tokens_per_day = cfg.groq_tokens_per_day if tokens_per_day is None else tokens_per_day
        self._clock = clock
        self._events: Deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0][0] >= _DAY:
            self._events.popleft()

    def _totals(self, now: float) -> tuple[int, int, int, int]:
        req_min = tok_min = req_day = tok_day = 0
        for ts, tokens in self._events:
            age = now - ts
            if age >= _DAY:
                continue
            req_day += 1
            tok_day += tokens
            if age < _MINUTE:
                req_min += 1
                tok_min += tokens
        return req_min, req_day, tok_min, tok_day

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            now = self._clock()
            self._prune(now)
            req_min, req_day, tok_min, tok_day = self._totals(now)
        return BudgetSnapshot(req_min, req_day, tok_min, tok_day)

    def check(self, estimated_tokens: int) -> None:
        """Raise GroqBudgetExceeded if this call would breach a limit."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            req_min, req_day, tok_min, tok_day = self._totals(now)

        checks = (
            ("requests_per_minute", req_min + 1, self.requests_per_minute),
            ("requests_per_day", req_day + 1, self.requests_per_day),
            ("tokens_per_minute", tok_min + estimated_tokens, self.tokens_per_minute),
            ("tokens_per_day", tok_day + estimated_tokens, self.tokens_per_day),
        )
        for name, projected, limit in checks:
            if limit and projected > limit:
                raise GroqBudgetExceeded(
                    name,
                    f"Groq {name} budget reached ({projected} > {limit}); "
                    "returning a Groww page link instead of calling Groq.",
                )

    def record(self, tokens: int) -> None:
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._events.append((now, max(0, int(tokens))))

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_shared_budget: GroqBudget | None = None
_shared_lock = threading.Lock()


def get_budget() -> GroqBudget:
    """Process-wide budget shared by every GroqClient."""
    global _shared_budget
    with _shared_lock:
        if _shared_budget is None:
            _shared_budget = GroqBudget()
        return _shared_budget


def reset_budget() -> None:
    global _shared_budget
    with _shared_lock:
        _shared_budget = None

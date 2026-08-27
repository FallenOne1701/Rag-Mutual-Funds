"""Online query path tests — classify → refuse | retrieve → generate (Phase 4)."""

from __future__ import annotations

import pytest

from src.config.settings import Settings
from src.generation.pipeline import answer_question
from src.generation.refusal import EDUCATIONAL_URL, build_refusal
from src.generation.validator import validate
from src.retrieval.query_parser import parse_query
from src.retrieval.retriever import RetrievalResult, RetrievedChunk

SCHEME_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"


def _settings(**kwargs) -> Settings:
    base = dict(
        groq_api_key="gsk_test",
        classifier_groq_fallback=False,
        groq_budget_enabled=False,
    )
    base.update(kwargs)
    return Settings(**base)


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="hdfc-large-cap::expense_ratio",
        text="Expense ratio: 1.02%",
        scheme_id="hdfc-large-cap-fund-direct-growth",
        scheme_name="HDFC Large Cap Fund Direct Growth",
        fact_key="expense_ratio",
        source_url=SCHEME_URL,
        document_date="2026-08-24",
        ingested_at="2026-08-24T00:00:00Z",
        page_or_section="Fund details",
        similarity=0.84,
        distance=0.16,
        category="Large Cap",
    )


class _Retriever:
    """Local Retriever stub; counts calls so we can assert refusals skip it."""

    def __init__(self, result: RetrievalResult | None = None) -> None:
        self.result = result
        self.calls = 0

    def retrieve(self, question: str) -> RetrievalResult:
        self.calls += 1
        if self.result is not None:
            return self.result
        chunk = _chunk()
        return RetrievalResult(
            status="ok",
            query=question,
            hints=parse_query(question),
            winner=chunk,
            candidates=[chunk],
            fallback_url=SCHEME_URL,
        )


class _Groq:
    """Groq stub that fails the test if a refusal path ever calls it."""

    def __init__(self, reply: str = "The expense ratio is 1.02%.") -> None:
        self.reply = reply
        self.calls = 0

    def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
        from src.generation.groq_client import ChatResult

        self.calls += 1
        return ChatResult(text=self.reply, model="fake", prompt_tokens=100, completion_tokens=20)


@pytest.mark.parametrize(
    "message,intent",
    [
        ("Should I invest in HDFC Large Cap Fund?", "advisory"),
        ("Which is better, HDFC Large Cap or HDFC Mid Cap?", "comparative"),
        ("My PAN is ABCDE1234F, check my folio balance", "pii_account"),
        ("Write me a poem about compounding", "out_of_scope"),
    ],
)
def test_refusals_cost_zero_groq_calls(message: str, intent: str) -> None:
    groq = _Groq()
    retriever = _Retriever()
    outcome = answer_question(
        message, retriever=retriever, client=groq, settings=_settings()
    )
    assert outcome.classification.intent == intent
    assert outcome.response.type == "refusal"
    assert outcome.response.citation["url"] == EDUCATIONAL_URL
    assert groq.calls == 0
    assert retriever.calls == 0
    assert outcome.validated, outcome.validation_errors


def test_pii_values_never_appear_in_the_reply() -> None:
    outcome = answer_question(
        "Send my statement to dhruv@example.com, OTP is 448213",
        retriever=_Retriever(),
        client=_Groq(),
        settings=_settings(),
    )
    assert outcome.classification.intent == "pii_account"
    assert "dhruv@example.com" not in outcome.response.text
    assert "448213" not in outcome.response.text


def test_performance_links_the_scheme_page_without_groq() -> None:
    groq = _Groq()
    retriever = _Retriever()
    outcome = answer_question(
        "If I had invested 10000 in HDFC Large Cap 5 years ago what would it be worth?",
        retriever=retriever,
        client=groq,
        settings=_settings(),
    )
    assert outcome.classification.intent == "performance"
    assert groq.calls == 0
    assert retriever.calls == 1  # local retrieval only, to find the scheme page
    assert outcome.response.citation["url"] == SCHEME_URL
    assert "do not calculate" in outcome.response.text.lower()
    assert outcome.validated, outcome.validation_errors


def test_factual_question_reaches_groq_once() -> None:
    groq = _Groq()
    outcome = answer_question(
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
        retriever=_Retriever(),
        client=groq,
        settings=_settings(),
    )
    assert outcome.classification.intent == "factual"
    assert groq.calls == 1
    assert outcome.response.type == "answer"
    assert outcome.response.citation["url"] == SCHEME_URL
    assert outcome.validated, outcome.validation_errors


def test_long_message_is_truncated_not_rejected() -> None:
    long_tail = " padding" * 500
    outcome = answer_question(
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?" + long_tail,
        retriever=_Retriever(),
        client=_Groq(),
        settings=_settings(max_message_chars=80),
    )
    assert outcome.response.meta and outcome.response.meta.get("truncated_input") is True


def test_outcome_dict_carries_intent() -> None:
    outcome = answer_question(
        "Should I invest in HDFC Large Cap Fund?",
        retriever=_Retriever(),
        client=_Groq(),
        settings=_settings(),
    )
    payload = outcome.to_dict()
    assert payload["type"] == "refusal"
    assert payload["meta"]["intent"] == "advisory"


@pytest.mark.parametrize(
    "intent",
    ["advisory", "comparative", "performance", "pii_account", "out_of_scope"],
)
def test_every_refusal_passes_the_response_contract(intent: str) -> None:
    payload = build_refusal(intent).to_dict()
    result = validate(payload)
    assert result.ok, result.errors
    assert payload["type"] == "refusal"

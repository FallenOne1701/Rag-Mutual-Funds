"""Phase 3 — Generator + validate/retry/fallback pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.config.settings import Settings
from src.generation.generator import (
    generate_answer,
    generate_from_retrieval,
    is_performance_query,
    performance_link_response,
)
from src.generation.groq_client import GroqClient
from src.retrieval.query_parser import QueryHints
from src.retrieval.retriever import RetrievedChunk, RetrievalResult


def _settings() -> Settings:
    return Settings(
        groq_api_key="gsk_test",
        groq_model="openai/gpt-oss-120b",
        groq_model_fast="openai/gpt-oss-20b",
        groq_max_tokens=256,
        groq_temperature=0.1,
    )


def _fake_response(text: str, model: str = "openai/gpt-oss-120b") -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=10),
    )


def _winner(**kwargs) -> RetrievedChunk:
    base = dict(
        chunk_id="hdfc-large-cap-fund-direct-growth::expense_ratio",
        text="The expense ratio of HDFC Large Cap Fund Direct Growth is 1.02%.",
        similarity=0.8,
        distance=0.2,
        scheme_id="hdfc-large-cap-fund-direct-growth",
        scheme_name="HDFC Large Cap Fund Direct Growth",
        category="Large-cap",
        source_url="https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        fact_key="expense_ratio",
        page_or_section="Expense Ratio",
        document_date="2026-08-24",
        ingested_at="2026-08-25T12:00:00+00:00",
    )
    base.update(kwargs)
    return RetrievedChunk(**base)


def _ok_retrieval(question: str = "What is the expense ratio?") -> RetrievalResult:
    w = _winner()
    return RetrievalResult(
        status="ok",
        query=question,
        hints=QueryHints(
            scheme_ids=("hdfc-large-cap-fund-direct-growth",),
            fact_key="expense_ratio",
            raw_query=question,
        ),
        winner=w,
        candidates=[w],
        fallback_url=w.source_url,
    )


def test_is_performance_query():
    assert is_performance_query("What returns will I get?")
    assert is_performance_query("Show me 5 year CAGR")
    assert not is_performance_query("What is the expense ratio?")


def test_performance_bypass_skips_groq():
    sdk = MagicMock()
    client = GroqClient(settings=_settings(), client=sdk)
    out = generate_from_retrieval(
        "What returns will I get on HDFC Large Cap?",
        _ok_retrieval(),
        client=client,
        settings=_settings(),
    )
    assert sdk.chat.completions.create.call_count == 0
    assert out.meta and out.meta.get("performance_bypass")
    assert "I do not calculate" in out.text
    assert out.citation["url"].startswith("https://groww.in/")
    assert out.footer.startswith("Last updated from sources:")
    assert out.disclaimer == "Facts-only. No investment advice."


def test_generate_answer_calls_primary_model():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response(
        "The expense ratio is 1.02% as per the Groww scheme page."
    )
    client = GroqClient(settings=_settings(), client=sdk)
    text = generate_answer(
        "Expense ratio?",
        [_winner().to_dict()],
        client=client,
        settings=_settings(),
    )
    assert "1.02%" in text
    assert sdk.chat.completions.create.call_args.kwargs["model"] == "openai/gpt-oss-120b"


def test_generate_from_retrieval_happy_path():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response(
        "The expense ratio of HDFC Large Cap Fund Direct Growth is 1.02%."
    )
    client = GroqClient(settings=_settings(), client=sdk)
    out = generate_from_retrieval(
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
        _ok_retrieval(),
        client=client,
        settings=_settings(),
    )
    assert out.type == "answer"
    assert out.citation["url"].endswith("hdfc-large-cap-fund-direct-growth")
    assert "1.02%" in out.text
    assert out.meta is None or out.meta.get("attempt") == "primary"


def test_validator_fail_retries_fast_model():
    sdk = MagicMock()
    sdk.chat.completions.create.side_effect = [
        _fake_response(
            "You should buy this fund because it is the best fund. "
            "It is worth investing. Also compare others. Extra sentence four."
        ),
        _fake_response(
            "The expense ratio is 1.02%.",
            model="openai/gpt-oss-20b",
        ),
    ]
    client = GroqClient(settings=_settings(), client=sdk)
    out = generate_from_retrieval(
        "Expense ratio?",
        _ok_retrieval(),
        client=client,
        settings=_settings(),
    )
    assert sdk.chat.completions.create.call_count == 2
    assert (
        sdk.chat.completions.create.call_args_list[1].kwargs["model"]
        == "openai/gpt-oss-20b"
    )
    assert out.meta and out.meta.get("attempt") == "fast_retry"
    assert "1.02%" in out.text


def test_both_attempts_fail_groww_fallback():
    sdk = MagicMock()
    bad = (
        "You should invest now. This is the best fund. "
        "It is worth investing for sure. And one more sentence."
    )
    sdk.chat.completions.create.side_effect = [
        _fake_response(bad),
        _fake_response(bad, model="openai/gpt-oss-20b"),
    ]
    client = GroqClient(settings=_settings(), client=sdk)
    out = generate_from_retrieval(
        "Expense ratio?",
        _ok_retrieval(),
        client=client,
        settings=_settings(),
    )
    assert out.meta and out.meta.get("fallback") is True
    assert out.citation["url"].startswith("https://groww.in/")


def test_low_confidence_retrieval_no_groq():
    sdk = MagicMock()
    client = GroqClient(settings=_settings(), client=sdk)
    retrieval = RetrievalResult(
        status="no_scheme",
        query="What is the benchmark?",
        hints=QueryHints(
            scheme_ids=(),
            fact_key="benchmark",
            raw_query="What is the benchmark?",
        ),
        winner=None,
        candidates=[],
        fallback_url="https://groww.in/p/mutual-funds",
        message="Please name the scheme.",
    )
    out = generate_from_retrieval(
        "What is the benchmark?",
        retrieval,
        client=client,
        settings=_settings(),
    )
    assert sdk.chat.completions.create.call_count == 0
    assert "scheme" in out.text.lower() or "sources" in out.text.lower()
    assert out.citation["url"] == "https://groww.in/p/mutual-funds"


def test_performance_link_response_contract():
    out = performance_link_response(
        citation={
            "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
            "title": "HDFC Large Cap — Groww",
        },
        document_date="2026-08-24",
        settings=_settings(),
    )
    assert out.type == "answer"
    assert out.footer == "Last updated from sources: 2026-08-24"

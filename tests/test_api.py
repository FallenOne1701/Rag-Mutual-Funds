"""Chat Endpoint tests — GET /health, POST /chat, GET /schemes (Phase 5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import deps, main
from src.api.main import app, reset_rate_limits
from src.generation.validator import validate
from src.retrieval.query_parser import parse_query
from src.retrieval.retriever import RetrievalResult, RetrievedChunk

SCHEME_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
EDUCATIONAL_URL = "https://groww.in/p/mutual-funds"


class _Retriever:
    """Local Retriever stub — no embedding model, no Chroma."""

    def __init__(self, *, vectors: int = 31) -> None:
        self.vectors = vectors

    def vector_count(self) -> int:
        if self.vectors < 0:
            raise RuntimeError("index missing")
        return self.vectors

    def retrieve(self, question: str) -> RetrievalResult:
        chunk = RetrievedChunk(
            chunk_id="hdfc-large-cap::expense_ratio",
            text="Expense ratio: 1.02%",
            similarity=0.84,
            distance=0.16,
            scheme_id="hdfc-large-cap-fund-direct-growth",
            scheme_name="HDFC Large Cap Fund Direct Growth",
            category="Large Cap",
            source_url=SCHEME_URL,
            fact_key="expense_ratio",
            page_or_section="Fund details",
            document_date="2026-08-24",
            ingested_at="2026-08-24T00:00:00Z",
        )
        return RetrievalResult(
            status="ok",
            query=question,
            hints=parse_query(question),
            winner=chunk,
            candidates=[chunk],
            fallback_url=SCHEME_URL,
        )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Stub the Retriever and Groq; keep rate-limit state clean per test."""
    deps.set_retriever(_Retriever())
    reset_rate_limits()

    def _fake_generate(question, retrieval, **kwargs):
        from src.generation.generator import package_response

        return package_response(
            resp_type="answer",
            text="The expense ratio of HDFC Large Cap Fund Direct Growth is 1.02%.",
            citation={
                "url": SCHEME_URL,
                "title": "HDFC Large Cap Fund Direct Growth — Groww",
            },
            document_date="2026-08-24",
            meta={"attempt": "primary"},
        )

    monkeypatch.setattr("src.generation.pipeline.generate_from_retrieval", _fake_generate)
    yield
    deps.set_retriever(None)


@pytest.fixture
def client() -> TestClient:
    # No context manager: skip lifespan warmup so the stub Retriever stays in place
    return TestClient(app)


# --- health ----------------------------------------------------------------


def test_health_reports_index_and_groq(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["phase"] == "5"
    assert body["index"]["ready"] is True
    assert body["index"]["vectors"] == 31
    assert body["groq"]["model"]
    assert body["disclaimer"] == "Facts-only. No investment advice."


def test_health_degraded_when_index_missing(client: TestClient) -> None:
    deps.set_retriever(_Retriever(vectors=-1))
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["index"]["ready"] is False
    assert body["index"]["detail"]


def test_health_degraded_when_index_empty(client: TestClient) -> None:
    deps.set_retriever(_Retriever(vectors=0))
    body = client.get("/health").json()
    assert body["index"]["ready"] is False
    assert "ingest" in body["index"]["detail"]


# --- chat ------------------------------------------------------------------


def test_factual_question_returns_answer_contract(client: TestClient) -> None:
    res = client.post(
        "/chat",
        json={"message": "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "answer"
    assert body["citation"]["url"] == SCHEME_URL
    assert body["footer"].startswith("Last updated from sources:")
    assert body["disclaimer"] == "Facts-only. No investment advice."
    assert body["meta"]["intent"] == "factual"
    assert validate(body).ok


def test_advice_question_is_refused_with_educational_link(client: TestClient) -> None:
    res = client.post("/chat", json={"message": "Should I invest in HDFC Large Cap Fund?"})
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "refusal"
    assert body["citation"]["url"] == EDUCATIONAL_URL
    assert body["meta"]["intent"] == "advisory"
    assert validate(body).ok


def test_pii_question_is_refused_without_echoing_values(client: TestClient) -> None:
    body = client.post(
        "/chat", json={"message": "My PAN is ABCDE1234F, show my folio"}
    ).json()
    assert body["type"] == "refusal"
    assert body["meta"]["intent"] == "pii_account"
    assert "ABCDE1234F" not in body["text"]


def test_performance_question_links_scheme_page(client: TestClient) -> None:
    body = client.post(
        "/chat", json={"message": "What were the 3 year returns of HDFC Large Cap Fund?"}
    ).json()
    assert body["meta"]["intent"] == "performance"
    assert "do not calculate" in body["text"].lower()
    assert validate(body).ok


def test_empty_message_is_rejected(client: TestClient) -> None:
    assert client.post("/chat", json={"message": ""}).status_code == 422


def test_huge_message_is_rejected_before_the_pipeline(client: TestClient) -> None:
    assert client.post("/chat", json={"message": "x" * 5000}).status_code == 422


def test_long_but_allowed_message_is_shortened_not_refused(client: TestClient) -> None:
    message = "What is the expense ratio of HDFC Large Cap Fund Direct Growth? " + ("pad " * 300)
    body = client.post("/chat", json={"message": message}).json()
    assert body["type"] == "answer"
    assert body["meta"].get("truncated_input") is True


def test_pipeline_failure_degrades_to_a_groww_link(client: TestClient, monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("chroma exploded")

    monkeypatch.setattr("src.api.routes.chat.answer_question", _boom)
    res = client.post("/chat", json={"message": "What is the expense ratio of HDFC Large Cap?"})
    assert res.status_code == 200
    body = res.json()
    assert body["citation"]["url"] == EDUCATIONAL_URL
    assert body["meta"]["reason"] == "internal_error"
    assert validate(body).ok


def test_rate_limit_returns_429(client: TestClient, monkeypatch) -> None:
    from src.config.settings import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        main, "get_settings", lambda: Settings(api_rate_limit_per_minute=2)
    )
    payload = {"message": "What is the expense ratio of HDFC Large Cap Fund?"}
    assert client.post("/chat", json=payload).status_code == 200
    assert client.post("/chat", json=payload).status_code == 200
    third = client.post("/chat", json=payload)
    assert third.status_code == 429
    assert "per minute" in third.json()["detail"]


# --- schemes ---------------------------------------------------------------


def test_schemes_lists_the_corpus(client: TestClient) -> None:
    body = client.get("/schemes").json()
    assert body["count"] == 15
    ids = {s["scheme_id"] for s in body["schemes"]}
    assert "hdfc-large-cap-fund-direct-growth" in ids
    for scheme in body["schemes"]:
        assert scheme["url"].startswith("https://groww.in/")

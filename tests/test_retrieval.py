"""Phase 2 — query parsing + metadata-first Retriever."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.settings import Settings, load_schemes
from src.ingestion.indexer import index_chunks
from src.retrieval.query_parser import detect_fact_key, detect_schemes, parse_query
from src.retrieval.retriever import (
    RetrievedChunk,
    Retriever,
    _rank_candidates,
    _select_winner,
)


class FakeEmbedder:
    model_name = "fake-embedder"
    _dim = 8

    def embed_documents(self, texts):
        out = []
        for t in texts:
            base = float(len(t) % 97) / 97.0
            # Mix in a few character codes so similar labels stay a bit distinct
            extra = [(ord(t[i % len(t)]) % 13) / 100.0 for i in range(self._dim - 1)]
            vec = [base] + extra
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out

    def embed_query(self, text: str):
        return self.embed_documents([text])[0]

    @property
    def dimension(self) -> int:
        return self._dim


QUIZ = [
    (
        "Expense ratio of HDFC Large Cap?",
        "hdfc-large-cap-fund-direct-growth",
        "expense_ratio",
    ),
    (
        "Mid Cap minimum SIP",
        "hdfc-mid-cap-fund-direct-growth",
        "min_sip",
    ),
    (
        "ELSS lock-in",
        "hdfc-elss-tax-saver-fund-direct-plan-growth",
        "lock_in",
    ),
    (
        "Exit load of the gold FoF",
        "hdfc-gold-etf-fund-of-fund-direct-plan-growth",
        "exit_load",
    ),
    (
        "Small Cap benchmark",
        "hdfc-small-cap-fund-direct-growth",
        "benchmark",
    ),
]


# --- Query parser -----------------------------------------------------------


def test_detect_large_cap_and_expense():
    hints = parse_query("What is the expense ratio of HDFC Large Cap Fund?")
    assert hints.scheme_id == "hdfc-large-cap-fund-direct-growth"
    assert hints.fact_key == "expense_ratio"


def test_detect_mid_cap_short_query():
    hints = parse_query("expense ratio Mid Cap")
    assert hints.scheme_id == "hdfc-mid-cap-fund-direct-growth"
    assert hints.fact_key == "expense_ratio"


def test_hdfc_alone_is_not_a_scheme():
    assert detect_schemes("What does HDFC charge?") == ()


def test_ambiguous_two_schemes():
    hints = parse_query("Compare Mid Cap and Large Cap expense ratio")
    assert hints.ambiguous_scheme
    assert hints.scheme_id is None


def test_benchmark_without_fund():
    hints = parse_query("What is the benchmark?")
    assert hints.fact_key == "benchmark"
    assert not hints.has_scheme


def test_gold_fof_and_elss_aliases():
    assert detect_schemes("exit load gold fund") == (
        "hdfc-gold-etf-fund-of-fund-direct-plan-growth",
    )
    assert detect_schemes("ELSS lock-in period") == (
        "hdfc-elss-tax-saver-fund-direct-plan-growth",
    )
    assert detect_fact_key("TER of the fund") == "expense_ratio"


def test_quiz_seed_detection():
    for question, scheme_id, fact_key in QUIZ:
        hints = parse_query(question)
        assert hints.scheme_id == scheme_id, question
        assert hints.fact_key == fact_key, question


# --- Ranking helpers --------------------------------------------------------


def _chunk(fact_key: str, sim: float, scheme: str = "hdfc-mid-cap-fund-direct-growth") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"{scheme}::{fact_key}",
        text=f"text {fact_key}",
        similarity=sim,
        distance=1.0 - sim,
        scheme_id=scheme,
        scheme_name="HDFC Mid Cap Fund Direct Growth",
        category="Mid-cap",
        source_url=f"https://groww.in/mutual-funds/{scheme}",
        fact_key=fact_key,
        page_or_section=fact_key,
        document_date="2026-08-24",
        ingested_at="2026-08-25T12:00:00+00:00",
    )


def test_fact_key_boost_prefers_expense_over_higher_sim_exit_load():
    ranked = _rank_candidates(
        [
            _chunk("exit_load", 0.80),
            _chunk("expense_ratio", 0.72),
            _chunk("min_sip", 0.70),
        ],
        preferred_fact_key="expense_ratio",
    )
    assert ranked[0].fact_key == "expense_ratio"


def test_select_winner_rejects_low_similarity():
    assert _select_winner([_chunk("expense_ratio", 0.40)], min_similarity=0.58) is None
    assert _select_winner([_chunk("expense_ratio", 0.70)], min_similarity=0.58) is not None


def test_select_winner_rejects_non_groww_url():
    bad = _chunk("expense_ratio", 0.90)
    bad.source_url = "https://example.com/x"
    assert _select_winner([bad], min_similarity=0.50) is None


# --- Retriever end-to-end (temp Chroma + fake embeddings) --------------------


def _load_all_chunks() -> list[dict]:
    path = Path("data/processed/all_chunks.json")
    if not path.is_file():
        pytest.skip("all_chunks.json missing — run chunker first")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def indexed_retriever(tmp_path: Path) -> Retriever:
    chunks = _load_all_chunks()
    index_dir = tmp_path / "index"
    index_chunks(
        chunks,
        embedder=FakeEmbedder(),
        index_dir=index_dir,
        collection_name="retriever_test",
    )
    settings = Settings(
        retrieval_top_k=7,  # all facts for a scheme (fake vectors; boost needs full pool)
        retrieval_min_similarity=0.01,
        data_index_dir=index_dir,
        chroma_collection_name="retriever_test",
    )
    return Retriever(
        settings=settings,
        embedder=FakeEmbedder(),
        index_dir=index_dir,
        collection_name="retriever_test",
        schemes=list(load_schemes()["schemes"]),
    )


def test_retrieve_quiz_seeds_land_on_right_fund(indexed_retriever: Retriever):
    for question, scheme_id, fact_key in QUIZ:
        result = indexed_retriever.retrieve(question)
        assert result.ok, f"{question} -> {result.status} {result.message}"
        assert result.winner is not None
        assert result.winner.scheme_id == scheme_id
        assert result.winner.fact_key == fact_key
        assert result.winner.source_url.startswith("https://groww.in/")
        assert result.winner.citation["url"] == result.winner.source_url
        assert "Groww" in result.winner.citation["title"]


def test_retrieve_short_mid_cap_expense_prefers_fact(indexed_retriever: Retriever):
    result = indexed_retriever.retrieve("expense ratio Mid Cap")
    assert result.ok
    assert result.winner is not None
    assert result.winner.scheme_id == "hdfc-mid-cap-fund-direct-growth"
    assert result.winner.fact_key == "expense_ratio"


def test_retrieve_ambiguous_benchmark_no_fund(indexed_retriever: Retriever):
    result = indexed_retriever.retrieve("What is the benchmark?")
    assert result.status == "no_scheme"
    assert result.winner is None
    assert result.fallback_url == "https://groww.in/p/mutual-funds"


def test_retrieve_ambiguous_two_funds(indexed_retriever: Retriever):
    result = indexed_retriever.retrieve("Mid Cap vs Large Cap expense ratio")
    assert result.status == "ambiguous_scheme"
    assert result.winner is None


def test_citation_never_invented(indexed_retriever: Retriever):
    result = indexed_retriever.retrieve("ELSS lock-in")
    assert result.ok and result.winner is not None
    # Must match indexed metadata for that scheme
    assert (
        result.winner.source_url
        == "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
    )

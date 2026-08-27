"""Phase 1.4–1.5 — Embedding Service + Vector Store (Indexer)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingestion.indexer import (
    build_index,
    collection_count,
    index_chunks,
    open_collection,
)
from src.retrieval.embedder import EmbeddingService


class FakeEmbedder:
    """Deterministic tiny vectors — no HuggingFace download in unit tests."""

    model_name = "fake-embedder"
    _dim = 8

    def embed_documents(self, texts):
        out = []
        for t in texts:
            # Length-based signal so similar strings share rough magnitude
            base = float(len(t) % 97) / 97.0
            vec = [base] + [0.01 * ((i + len(t)) % 7) for i in range(self._dim - 1)]
            # L2-normalize lightly
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out

    def embed_query(self, text: str):
        return self.embed_documents([text])[0]

    @property
    def dimension(self) -> int:
        return self._dim


SAMPLE_CHUNKS = [
    {
        "chunk_id": "hdfc-large-cap-fund-direct-growth::expense_ratio",
        "text": "The expense ratio of HDFC Large Cap Fund Direct Growth is 1.02%.",
        "scheme_id": "hdfc-large-cap-fund-direct-growth",
        "scheme_name": "HDFC Large Cap Fund Direct Growth",
        "category": "Large-cap",
        "amc": "HDFC Mutual Fund",
        "document_type": "groww_scheme_page",
        "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "source_domain": "groww.in",
        "page_or_section": "Expense Ratio",
        "fact_key": "expense_ratio",
        "content_hash": "sha256:aaa",
        "document_date": "2026-08-24",
        "ingested_at": "2026-08-25T12:05:20+00:00",
        "part_index": 0,
        "part_count": 1,
    },
    {
        "chunk_id": "hdfc-large-cap-fund-direct-growth::exit_load",
        "text": "Exit load for HDFC Large Cap Fund Direct Growth: 1% within 1 year.",
        "scheme_id": "hdfc-large-cap-fund-direct-growth",
        "scheme_name": "HDFC Large Cap Fund Direct Growth",
        "category": "Large-cap",
        "amc": "HDFC Mutual Fund",
        "document_type": "groww_scheme_page",
        "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "source_domain": "groww.in",
        "page_or_section": "Exit Load",
        "fact_key": "exit_load",
        "content_hash": "sha256:bbb",
        "document_date": "2026-08-24",
        "ingested_at": "2026-08-25T12:05:20+00:00",
        "part_index": 0,
        "part_count": 1,
    },
    {
        "chunk_id": "hdfc-elss-tax-saver-fund-direct-plan-growth::lock_in",
        "text": "The lock-in period is 3 years.",
        "scheme_id": "hdfc-elss-tax-saver-fund-direct-plan-growth",
        "scheme_name": "HDFC ELSS Tax Saver Fund Direct Plan Growth",
        "category": "ELSS",
        "amc": "HDFC Mutual Fund",
        "document_type": "groww_scheme_page",
        "source_url": "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
        "source_domain": "groww.in",
        "page_or_section": "Lock-in",
        "fact_key": "lock_in",
        "content_hash": "sha256:ccc",
        "document_date": "2026-08-24",
        "ingested_at": "2026-08-25T12:05:21+00:00",
        "part_index": 0,
        "part_count": 1,
    },
]


def test_fake_embedder_dimensions():
    emb = FakeEmbedder()
    vecs = emb.embed_documents(["a", "bb"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 8
    assert abs(sum(x * x for x in vecs[0]) - 1.0) < 1e-5


def test_embedding_service_accepts_injected_model():
    class StubModel:
        def encode(self, texts, **kwargs):
            return [[0.5, 0.5] for _ in texts]

    svc = EmbeddingService(model_name="stub", model=StubModel())
    out = svc.embed_documents(["hello"])
    assert out == [[0.5, 0.5]]
    assert svc.dimension == 2
    q = svc.embed_query("expense ratio")
    assert len(q) == 2


def test_index_chunks_upsert_and_dedupe(tmp_path: Path):
    index_dir = tmp_path / "index"
    emb = FakeEmbedder()
    n = index_chunks(
        SAMPLE_CHUNKS,
        embedder=emb,
        index_dir=index_dir,
        collection_name="test_chunks",
    )
    assert n == 3
    assert collection_count(index_dir=index_dir, collection_name="test_chunks") == 3

    # Re-upsert same ids — still 3, not 6
    n2 = index_chunks(
        SAMPLE_CHUNKS,
        embedder=emb,
        index_dir=index_dir,
        collection_name="test_chunks",
    )
    assert n2 == 3
    assert collection_count(index_dir=index_dir, collection_name="test_chunks") == 3

    col = open_collection(index_dir=index_dir, collection_name="test_chunks")
    got = col.get(ids=["hdfc-large-cap-fund-direct-growth::expense_ratio"])
    assert got["ids"] == ["hdfc-large-cap-fund-direct-growth::expense_ratio"]
    assert got["metadatas"][0]["source_url"].startswith("https://groww.in/")
    assert got["metadatas"][0]["fact_key"] == "expense_ratio"


def test_build_index_from_all_chunks(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    index_dir = tmp_path / "index"
    (processed / "all_chunks.json").write_text(
        json.dumps(SAMPLE_CHUNKS),
        encoding="utf-8",
    )
    schemes = [
        {
            "scheme_id": "hdfc-large-cap-fund-direct-growth",
            "scheme_name": "HDFC Large Cap Fund Direct Growth",
            "category": "Large-cap",
            "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        },
        {
            "scheme_id": "hdfc-elss-tax-saver-fund-direct-plan-growth",
            "scheme_name": "HDFC ELSS Tax Saver Fund Direct Plan Growth",
            "category": "ELSS",
            "url": "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
        },
    ]
    report = build_index(
        schemes=schemes,
        processed_dir=processed,
        index_dir=index_dir,
        collection_name="test_build",
        embedder=FakeEmbedder(),
        write_report=True,
    )
    assert report.all_ok
    assert report.total_chunks == 3
    assert report.upserted == 3
    assert report.ok_count == 2
    assert (index_dir / "index_report.json").is_file()

    # Second run still 3 vectors
    report2 = build_index(
        schemes=schemes,
        processed_dir=processed,
        index_dir=index_dir,
        collection_name="test_build",
        embedder=FakeEmbedder(),
        write_report=True,
    )
    assert report2.upserted == 3
    assert collection_count(index_dir=index_dir, collection_name="test_build") == 3


def test_build_index_missing_chunks_file(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    report = build_index(
        schemes=[
            {
                "scheme_id": "x",
                "scheme_name": "X",
                "category": "c",
                "url": "https://groww.in/mutual-funds/x",
            }
        ],
        processed_dir=processed,
        index_dir=tmp_path / "index",
        embedder=FakeEmbedder(),
        write_report=False,
    )
    assert not report.all_ok
    assert "all_chunks.json" in (report.error or "")


def test_build_index_skips_non_groww_url(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    bad = dict(SAMPLE_CHUNKS[0])
    bad["chunk_id"] = "bad::expense_ratio"
    bad["scheme_id"] = "hdfc-large-cap-fund-direct-growth"
    bad["source_url"] = "https://example.com/not-groww"
    (processed / "all_chunks.json").write_text(
        json.dumps([bad, SAMPLE_CHUNKS[1]]),
        encoding="utf-8",
    )
    schemes = [
        {
            "scheme_id": "hdfc-large-cap-fund-direct-growth",
            "scheme_name": "HDFC Large Cap Fund Direct Growth",
            "category": "Large-cap",
            "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        }
    ]
    report = build_index(
        schemes=schemes,
        processed_dir=processed,
        index_dir=tmp_path / "index",
        collection_name="skip_bad",
        embedder=FakeEmbedder(),
        write_report=False,
    )
    assert report.upserted == 1
    assert collection_count(
        index_dir=tmp_path / "index", collection_name="skip_bad"
    ) == 1

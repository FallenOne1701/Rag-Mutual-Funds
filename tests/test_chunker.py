"""Phase 1.3 — Chunker (fact-atomic sections from processed JSON)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingestion.chunker import (
    chunk_document,
    chunk_processed_document,
    chunk_scheme_pages,
    estimate_tokens,
)


SAMPLE_DOC = {
    "scheme_id": "hdfc-large-cap-fund-direct-growth",
    "scheme_name": "HDFC Large Cap Fund Direct Growth",
    "category": "Large-cap",
    "amc": "HDFC Mutual Fund",
    "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    "source_domain": "groww.in",
    "document_type": "groww_scheme_page",
    "document_date": "2026-08-24",
    "ingested_at": "2026-08-25T12:05:20+00:00",
    "content_hash": "sha256:abc",
    "facts": {
        "expense_ratio": "1.02%",
        "exit_load": "Exit load of 1% if redeemed within 1 year",
        "min_sip": "₹100",
        "riskometer": "Very High",
        "benchmark": "NIFTY 100 Total Return Index",
        "lock_in": None,
    },
    "missing_facts": ["lock_in"],
    "sections": [
        {
            "page_or_section": "Expense Ratio",
            "fact_key": "expense_ratio",
            "text": "The expense ratio of HDFC Large Cap Fund Direct Growth is 1.02%.",
        },
        {
            "page_or_section": "Exit Load",
            "fact_key": "exit_load",
            "text": "Exit load for HDFC Large Cap Fund Direct Growth: 1% within 1 year.",
        },
        {
            "page_or_section": "Minimum SIP",
            "fact_key": "min_sip",
            "text": "The minimum SIP amount for HDFC Large Cap Fund Direct Growth is ₹100.",
        },
        {
            "page_or_section": "Riskometer",
            "fact_key": "riskometer",
            "text": "The riskometer for HDFC Large Cap Fund Direct Growth is Very High.",
        },
        {
            "page_or_section": "Benchmark",
            "fact_key": "benchmark",
            "text": "The fund benchmark is NIFTY 100 Total Return Index.",
        },
        {
            "page_or_section": "Investment Objective",
            "fact_key": "investment_objective",
            "text": "Investment objective: long-term capital appreciation in Large-Cap companies.",
        },
    ],
    "normalized_text": "SHOULD NOT BE INDEXED AS A MEGA CHUNK " * 20,
}


def test_estimate_tokens():
    assert estimate_tokens("one two three") == 3


def test_chunk_processed_document_one_per_section():
    chunks = chunk_processed_document(SAMPLE_DOC)
    assert len(chunks) == 6
    keys = {c.fact_key for c in chunks}
    assert "lock_in" not in keys
    assert "expense_ratio" in keys
    expense = next(c for c in chunks if c.fact_key == "expense_ratio")
    assert expense.source_url.startswith("https://groww.in/")
    assert expense.page_or_section == "Expense Ratio"
    assert expense.chunk_id == "hdfc-large-cap-fund-direct-growth::expense_ratio"
    assert expense.content_hash.startswith("sha256:")
    assert expense.document_date == "2026-08-24"
    # normalized_text must not appear as its own chunk
    assert all("SHOULD NOT BE INDEXED" not in c.text for c in chunks)


def test_chunk_skips_missing_lock_in_even_if_section_present():
    doc = json.loads(json.dumps(SAMPLE_DOC))
    doc["sections"].append(
        {
            "page_or_section": "Lock-in",
            "fact_key": "lock_in",
            "text": "Invented lock-in should be dropped.",
        }
    )
    chunks = chunk_processed_document(doc)
    assert all(c.fact_key != "lock_in" for c in chunks)


def test_chunk_elss_includes_lock_in():
    doc = json.loads(json.dumps(SAMPLE_DOC))
    doc["scheme_id"] = "hdfc-elss-tax-saver-fund-direct-plan-growth"
    doc["scheme_name"] = "HDFC ELSS Tax Saver Fund Direct Plan Growth"
    doc["category"] = "ELSS"
    doc["facts"]["lock_in"] = "3 years"
    doc["missing_facts"] = []
    doc["sections"].append(
        {
            "page_or_section": "Lock-in",
            "fact_key": "lock_in",
            "text": "The lock-in period is 3 years.",
        }
    )
    chunks = chunk_processed_document(doc)
    assert any(c.fact_key == "lock_in" for c in chunks)
    assert len(chunks) == 7


def test_chunk_splits_oversized_section():
    doc = json.loads(json.dumps(SAMPLE_DOC))
    long_text = " ".join(f"word{i}" for i in range(50))
    doc["sections"] = [
        {
            "page_or_section": "Expense Ratio",
            "fact_key": "expense_ratio",
            "text": long_text,
        }
    ]
    doc["missing_facts"] = []
    chunks = chunk_processed_document(
        doc,
        max_section_tokens=20,
        overlap_tokens=5,
    )
    assert len(chunks) > 1
    assert all(c.fact_key == "expense_ratio" for c in chunks)
    assert chunks[0].part_count == len(chunks)
    assert chunks[0].chunk_id.endswith("__p0")


def test_chunk_document_compat_helper():
    out = chunk_document(
        "The expense ratio is 1.02%.",
        {
            "scheme_id": "hdfc-large-cap-fund-direct-growth",
            "scheme_name": "HDFC Large Cap Fund Direct Growth",
            "category": "Large-cap",
            "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
            "fact_key": "expense_ratio",
            "page_or_section": "Expense Ratio",
            "document_date": "2026-08-24",
        },
    )
    assert len(out) == 1
    assert out[0]["fact_key"] == "expense_ratio"
    assert out[0]["text"].startswith("The expense ratio")


def test_chunk_scheme_pages_writes_files(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    scheme_id = SAMPLE_DOC["scheme_id"]
    (processed / f"{scheme_id}.json").write_text(
        json.dumps(SAMPLE_DOC),
        encoding="utf-8",
    )
    report = chunk_scheme_pages(
        schemes=[
            {
                "scheme_id": scheme_id,
                "scheme_name": SAMPLE_DOC["scheme_name"],
                "category": "Large-cap",
                "url": SAMPLE_DOC["source_url"],
            }
        ],
        processed_dir=processed,
        write_report=True,
    )
    assert report.all_ok
    assert report.total_chunks == 6
    assert (processed / "chunks" / f"{scheme_id}.json").exists()
    all_chunks = json.loads((processed / "all_chunks.json").read_text(encoding="utf-8"))
    assert len(all_chunks) == 6
    assert (processed / "chunk_report.json").exists()

    # Re-run must not duplicate
    report2 = chunk_scheme_pages(
        schemes=[
            {
                "scheme_id": scheme_id,
                "scheme_name": SAMPLE_DOC["scheme_name"],
                "category": "Large-cap",
                "url": SAMPLE_DOC["source_url"],
            }
        ],
        processed_dir=processed,
        write_report=True,
    )
    assert report2.total_chunks == 6


def test_chunk_scheme_pages_missing_processed_is_error(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    report = chunk_scheme_pages(
        schemes=[
            {
                "scheme_id": "missing",
                "scheme_name": "Missing",
                "category": "x",
                "url": "https://groww.in/mutual-funds/missing",
            }
        ],
        processed_dir=processed,
        write_report=False,
    )
    assert not report.all_ok
    assert "Processed JSON missing" in (report.results[0].error or "")

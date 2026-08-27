"""Phase 1.2 — Parser & Normalizer (Groww facts + normalized text)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingestion.parser import (
    _format_lock_in,
    normalize_whitespace,
    parse_scheme_html,
    parse_scheme_pages,
)

MINIMAL_NEXT_DATA = {
    "props": {
        "pageProps": {
            "mfServerSideData": {
                "scheme_name": "HDFC Large Cap Fund Direct Growth",
                "fund_house": "HDFC Mutual Fund",
                "expense_ratio": "1.02",
                "exit_load": "Exit load of 1% if redeemed within 1 year",
                "min_sip_investment": 100,
                "benchmark_name": "NIFTY 100 Total Return Index",
                "lock_in": {"years": None, "months": None, "days": None},
                "nav_date": "24-Aug-2026",
                "description": "Invests predominantly in Large-Cap companies.",
                "return_stats": [{"risk": "Very High"}],
                "historic_fund_expense": [
                    {"expense_ratio": 1.02, "as_on_date": "2026-08-23T00:00:00"}
                ],
            }
        }
    }
}


def _html_with_next_data(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False)
    return (
        "<!DOCTYPE html><html><head><title>Test</title></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{blob}</script>'
        "<h1>HDFC Large Cap Fund Direct Growth</h1>"
        "</body></html>"
    )


def test_normalize_whitespace_collapses_and_strips():
    assert normalize_whitespace("  foo\u00a0\u00a0bar\n\n\nbaz  ") == "foo bar\n\nbaz"


def test_format_lock_in_elss_three_years():
    assert _format_lock_in({"years": 3, "months": 0, "days": 0}) == "3 years"


def test_format_lock_in_all_null_is_none():
    assert _format_lock_in({"years": None, "months": None, "days": None}) is None


def test_parse_scheme_html_extracts_core_facts():
    html = _html_with_next_data(MINIMAL_NEXT_DATA)
    doc = parse_scheme_html(
        html,
        scheme_id="hdfc-large-cap-fund-direct-growth",
        scheme_name="HDFC Large Cap Fund Direct Growth",
        category="Large-cap",
        source_url="https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        ingested_at="2026-08-25T12:00:00+00:00",
    )
    assert doc.facts["expense_ratio"] == "1.02%"
    assert "1%" in (doc.facts["exit_load"] or "")
    assert doc.facts["min_sip"] == "₹100"
    assert doc.facts["riskometer"] == "Very High"
    assert doc.facts["benchmark"] == "NIFTY 100 Total Return Index"
    assert doc.facts["lock_in"] is None
    assert "lock_in" in doc.missing_facts
    assert doc.document_date == "2026-08-24"
    assert doc.source_domain == "groww.in"
    assert doc.parse_source == "next_data"
    assert "expense ratio" in doc.normalized_text.lower()
    assert any(s.fact_key == "expense_ratio" for s in doc.sections)


def test_parse_scheme_html_elss_lock_in():
    payload = json.loads(json.dumps(MINIMAL_NEXT_DATA))
    mf = payload["props"]["pageProps"]["mfServerSideData"]
    mf["scheme_name"] = "HDFC ELSS Tax Saver Fund Direct Plan Growth"
    mf["lock_in"] = {"years": 3, "months": 0, "days": 0}
    mf["exit_load"] = "Nil"
    mf["min_sip_investment"] = 500
    html = _html_with_next_data(payload)
    doc = parse_scheme_html(
        html,
        scheme_id="hdfc-elss-tax-saver-fund-direct-plan-growth",
        scheme_name="HDFC ELSS Tax Saver Fund Direct Plan Growth",
        category="ELSS",
        source_url="https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
    )
    assert doc.facts["lock_in"] == "3 years"
    assert "lock_in" not in doc.missing_facts


def test_parse_scheme_html_html_fallback_when_no_next_data():
    html = """<!DOCTYPE html><html><body>
    <h1>HDFC Mid Cap Fund Direct Growth</h1>
    <p>Expense Ratio 0.75%</p>
    <p>Exit load: Nil</p>
    <p>Minimum SIP ₹100</p>
    <p>Fund benchmark NIFTY Midcap 150 Total Return Index</p>
    <p>Riskometer Very High</p>
    </body></html>"""
    doc = parse_scheme_html(
        html,
        scheme_id="hdfc-mid-cap-fund-direct-growth",
        scheme_name="HDFC Mid Cap Fund Direct Growth",
        category="Mid-cap",
        source_url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    )
    assert doc.parse_source == "html_fallback"
    assert doc.facts["expense_ratio"] == "0.75%"
    assert doc.facts["min_sip"] == "₹100"


def test_parse_scheme_html_raises_when_no_facts():
    html = "<!DOCTYPE html><html><body><p>Hello navigation chrome only</p></body></html>"
    with pytest.raises(ValueError, match="No core fund facts"):
        parse_scheme_html(
            html,
            scheme_id="empty",
            scheme_name="Empty",
            category="x",
            source_url="https://groww.in/mutual-funds/empty",
        )


def test_parse_scheme_pages_writes_processed(tmp_path: Path):
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    raw.mkdir()
    scheme = {
        "scheme_id": "hdfc-large-cap-fund-direct-growth",
        "scheme_name": "HDFC Large Cap Fund Direct Growth",
        "category": "Large-cap",
        "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    }
    html_path = raw / f"{scheme['scheme_id']}.html"
    html_path.write_text(_html_with_next_data(MINIMAL_NEXT_DATA), encoding="utf-8")
    (raw / f"{scheme['scheme_id']}.meta.json").write_text(
        json.dumps(
            {
                "scheme_id": scheme["scheme_id"],
                "ingested_at": "2026-08-25T12:00:00+00:00",
                "content_hash": "sha256:abc",
                "source_url": scheme["url"],
            }
        ),
        encoding="utf-8",
    )

    report = parse_scheme_pages(
        schemes=[scheme],
        raw_dir=raw,
        processed_dir=processed,
        write_report=True,
    )
    assert report.all_ok
    out = processed / f"{scheme['scheme_id']}.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["facts"]["expense_ratio"] == "1.02%"
    assert data["source_url"] == scheme["url"]
    assert (processed / "parse_report.json").exists()


def test_parse_scheme_pages_missing_raw_is_error(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    report = parse_scheme_pages(
        schemes=[
            {
                "scheme_id": "missing-scheme",
                "scheme_name": "Missing",
                "category": "x",
                "url": "https://groww.in/mutual-funds/missing",
            }
        ],
        raw_dir=raw,
        processed_dir=tmp_path / "processed",
        write_report=False,
    )
    assert not report.all_ok
    assert report.error_count == 1
    assert "Raw HTML missing" in (report.results[0].error or "")

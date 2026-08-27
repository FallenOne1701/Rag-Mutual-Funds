"""Phase 3 — Response Validator (response contract)."""

from __future__ import annotations

from src.generation.validator import count_sentences, validate, validate_response


def _ok_payload(**overrides):
    base = {
        "type": "answer",
        "text": (
            "The expense ratio of HDFC Large Cap Fund Direct Growth is 1.02% "
            "as shown on the Groww scheme page."
        ),
        "citation": {
            "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
            "title": "HDFC Large Cap Fund Direct Growth — Groww",
        },
        "footer": "Last updated from sources: 2026-08-24",
        "disclaimer": "Facts-only. No investment advice.",
    }
    base.update(overrides)
    return base


def test_count_sentences_ignores_decimals():
    assert count_sentences("The expense ratio is 1.02%. That is the annual fee.") == 2
    assert count_sentences("One. Two. Three. Four.") == 4


def test_valid_answer_passes():
    ok, errors = validate_response(_ok_payload())
    assert ok
    assert errors == []


def test_rejects_too_many_sentences():
    text = "One sentence. Two sentence. Three sentence. Four is too many."
    result = validate(_ok_payload(text=text))
    assert not result.ok
    assert any(e.startswith("too_many_sentences") for e in result.errors)


def test_rejects_missing_citation_and_footer():
    result = validate(
        _ok_payload(citation={}, footer="", disclaimer="Facts-only. No investment advice.")
    )
    assert not result.ok
    assert "missing_citation_url" in result.errors or "missing_citation" in result.errors
    assert "missing_footer" in result.errors or "footer_missing_date" in result.errors


def test_rejects_non_groww_citation():
    result = validate(
        _ok_payload(
            citation={
                "url": "https://www.amfiindia.com/x",
                "title": "AMFI",
            }
        )
    )
    assert "citation_domain_not_allowlisted" in result.errors


def test_rejects_citation_not_from_retrieval():
    result = validate(
        _ok_payload(),
        allowed_citation_urls={
            "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
        },
    )
    assert "citation_not_from_retrieval" in result.errors


def test_rejects_advice_language():
    result = validate(
        _ok_payload(text="You should buy this fund. It is worth investing now.")
    )
    assert "advice_language" in result.errors


def test_rejects_wrong_disclaimer():
    result = validate(_ok_payload(disclaimer="Not financial advice only."))
    assert "missing_or_wrong_disclaimer" in result.errors


def test_allows_matching_retrieval_url():
    url = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
    result = validate(_ok_payload(), allowed_citation_urls=[url])
    assert result.ok

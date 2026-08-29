"""Phase 0 — settings, scheme registry, Groww allowlist."""

from __future__ import annotations

from src.config.settings import (
    ALLOWED_SOURCE_DOMAINS,
    get_settings,
    is_allowed_source_url,
    load_schemes,
)


def test_allowed_domains_groww_only():
    assert ALLOWED_SOURCE_DOMAINS == frozenset({"groww.in"})


def test_is_allowed_source_url():
    assert is_allowed_source_url(
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
    )
    assert is_allowed_source_url("https://www.groww.in/p/mutual-funds")
    assert not is_allowed_source_url("https://www.amfiindia.com/investor-corner")
    assert not is_allowed_source_url("https://evil.example/groww.in")


def test_load_schemes_has_fifteen_hdfc_groww_urls():
    data = load_schemes()
    schemes = data["schemes"]
    assert len(schemes) == 15
    urls = {s["url"] for s in schemes}
    assert all(u.startswith("https://groww.in/mutual-funds/") for u in urls)
    assert all(is_allowed_source_url(u) for u in urls)
    ids = {s["scheme_id"] for s in schemes}
    assert "hdfc-large-cap-fund-direct-growth" in ids
    assert "hdfc-elss-tax-saver-fund-direct-plan-growth" in ids


def test_refusal_link_is_groww_overview():
    data = load_schemes()
    refusal = data["refusal"]
    assert refusal["url"] == "https://groww.in/p/mutual-funds"
    assert is_allowed_source_url(refusal["url"])


def test_settings_defaults_match_architecture():
    get_settings.cache_clear()
    s = get_settings()
    assert s.groq_model == "openai/gpt-oss-120b"
    assert s.groq_model_fast == "openai/gpt-oss-20b"
    assert s.groq_max_tokens == 512
    assert s.groq_temperature == 0.1
    assert s.retrieval_top_k == 3
    assert s.disclaimer == "Facts-only. No investment advice."
    assert "groww.in" in s.allowed_source_domains
    assert s.data_raw_dir.name == "raw"
    assert s.data_index_dir.name == "index"

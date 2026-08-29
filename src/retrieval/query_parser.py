"""
Rule-based query parsing for Retriever (implementation-plan Step 2).

Detects scheme_id / fact_key from the user question against schemes.yaml
and known FAQ phrases. No Groq — deterministic aliases only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.config.settings import load_schemes

# Longer / more specific aliases first within each scheme.
_SCHEME_ALIASES: dict[str, tuple[str, ...]] = {
    "hdfc-mid-cap-fund-direct-growth": (
        "mid cap fund",
        "mid-cap fund",
        "midcap fund",
        "mid cap",
        "mid-cap",
        "midcap",
    ),
    "hdfc-small-cap-fund-direct-growth": (
        "small cap fund",
        "small-cap fund",
        "smallcap fund",
        "small cap",
        "small-cap",
        "smallcap",
    ),
    "hdfc-large-cap-fund-direct-growth": (
        "large cap fund",
        "large-cap fund",
        "largecap fund",
        "large cap",
        "large-cap",
        "largecap",
    ),
    "hdfc-gold-etf-fund-of-fund-direct-plan-growth": (
        "gold etf fund of fund",
        "gold fund of fund",
        "gold fof",
        "gold etf",
        "gold fund",
        "gold",
    ),
    "hdfc-elss-tax-saver-fund-direct-plan-growth": (
        "elss tax saver",
        "tax saver fund",
        "tax-saver",
        "tax saver",
        "elss",
    ),
    "hdfc-defence-fund-direct-growth": (
        "defence fund",
        "defense fund",
        "defence",
        "defense",
    ),
    "hdfc-pharma-and-healthcare-fund-direct-growth": (
        "pharma and healthcare fund",
        "pharma healthcare fund",
        "pharma and healthcare",
        "pharma healthcare",
        "healthcare fund",
    ),
    "hdfc-focused-fund-direct-growth": (
        "focused fund",
        "focus fund",
    ),
    "hdfc-innovation-fund-direct-growth": (
        "innovation fund",
        "innovation",
    ),
    "hdfc-banking-financial-services-fund-direct-growth": (
        "banking and financial services fund",
        "banking financial services fund",
        "banking & financial services",
        "banking financial services",
        "bfsi fund",
    ),
    "hdfc-gilt-fund-direct-growth": (
        "gilt fund",
        "gilt",
    ),
    "hdfc-ultra-short-to-short-term-fund-direct-growth": (
        "ultra short to short term fund",
        "ultra short short term fund",
        "ultra short term fund",
        "ultra short",
    ),
    "hdfc-mnc-fund-direct-growth": (
        "mnc fund",
        "mnc",
    ),
    "hdfc-medium-to-long-term-fund-direct-growth": (
        "medium to long term fund",
        "medium to long duration fund",
        "medium to long term",
        "medium to long duration",
    ),
    "hdfc-arbitrage-fund-direct-growth": (
        "arbitrage fund",
        "arbitrage",
    ),
}

# fact_key → phrases (checked case-insensitively; longer phrases first)
_FACT_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "expense_ratio",
        (
            "expense ratio",
            "expense-ratio",
            "total expense",
            "ter",
        ),
    ),
    (
        "exit_load",
        (
            "exit load",
            "exit-load",
            "redemption load",
        ),
    ),
    (
        "min_sip",
        (
            "minimum sip",
            "min sip",
            "minimum investment",
            "min investment",
            "sip amount",
            "sip",
        ),
    ),
    (
        "riskometer",
        (
            "riskometer",
            "risk level",
            "risk rating",
            "how risky",
        ),
    ),
    (
        "benchmark",
        (
            "benchmark index",
            "fund benchmark",
            "benchmark",
        ),
    ),
    (
        "lock_in",
        (
            "lock-in period",
            "lock in period",
            "lock-in",
            "lock in",
            "lockin",
        ),
    ),
    (
        "investment_objective",
        (
            "investment objective",
            "invests in",
            "investment goal",
            "objective",
        ),
    ),
)


@dataclass(frozen=True)
class QueryHints:
    """Parsed signals from a user question (may be partial)."""

    scheme_ids: tuple[str, ...]
    fact_key: str | None
    raw_query: str

    @property
    def scheme_id(self) -> str | None:
        """Single resolved scheme, or None if zero / ambiguous."""
        if len(self.scheme_ids) == 1:
            return self.scheme_ids[0]
        return None

    @property
    def ambiguous_scheme(self) -> bool:
        return len(self.scheme_ids) > 1

    @property
    def has_scheme(self) -> bool:
        return len(self.scheme_ids) == 1


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[?\u2019']", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _scheme_registry_aliases(schemes: list[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    """Merge static aliases with scheme_name / scheme_id tokens from registry."""
    merged: dict[str, list[str]] = {
        sid: list(aliases) for sid, aliases in _SCHEME_ALIASES.items()
    }
    for scheme in schemes:
        sid = str(scheme["scheme_id"])
        names: list[str] = merged.setdefault(sid, [])
        scheme_name = str(scheme.get("scheme_name") or "").lower()
        if scheme_name and scheme_name not in names:
            names.insert(0, scheme_name)
        # slug without leading hdfc-
        slug = sid
        if slug.startswith("hdfc-"):
            slug = slug[len("hdfc-") :]
        slug_spaced = slug.replace("-", " ")
        if slug_spaced and slug_spaced not in names:
            names.append(slug_spaced)
    return {k: tuple(v) for k, v in merged.items()}


def detect_schemes(
    query: str,
    *,
    schemes: list[dict[str, Any]] | None = None,
) -> tuple[str, ...]:
    """
    Return all scheme_ids whose aliases appear in the query.

    \"HDFC\" alone does not match (all corpus funds are HDFC).
    Longer aliases win ties when multiple aliases hit the same scheme.
    """
    if schemes is None:
        schemes = list(load_schemes()["schemes"])
    normalized = _normalize(query)
    alias_map = _scheme_registry_aliases(schemes)

    hits: dict[str, int] = {}
    for scheme_id, aliases in alias_map.items():
        best = 0
        for alias in aliases:
            alias_n = _normalize(alias)
            if not alias_n:
                continue
            if alias_n in normalized:
                best = max(best, len(alias_n))
        if best:
            hits[scheme_id] = best

    if not hits:
        return ()
    # Prefer more specific (longer) alias matches; keep all schemes that hit
    # so ambiguous multi-fund queries surface as ambiguous.
    return tuple(sorted(hits.keys(), key=lambda s: (-hits[s], s)))


def detect_fact_key(query: str) -> str | None:
    """Return the first matching fact_key, or None."""
    normalized = _normalize(query)
    for fact_key, phrases in _FACT_PHRASES:
        for phrase in phrases:
            if _normalize(phrase) in normalized:
                return fact_key
    return None


def parse_query(
    query: str,
    *,
    schemes: list[dict[str, Any]] | None = None,
) -> QueryHints:
    """Detect scheme + fact signals for metadata-first retrieval."""
    return QueryHints(
        scheme_ids=detect_schemes(query, schemes=schemes),
        fact_key=detect_fact_key(query),
        raw_query=query.strip(),
    )

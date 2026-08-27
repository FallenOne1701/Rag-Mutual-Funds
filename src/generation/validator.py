"""
Response Validator — enforce the Architecture response contract (Phase 3).

Checks: ≤3 sentences, Groww citation, last-updated footer, disclaimer,
no advice / comparison language. Citation URL must be allowlisted groww.in
and (when provided) one of the retrieved chunk URLs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from src.config.settings import get_settings, is_allowed_source_url

FOOTER_PREFIX = "Last updated from sources:"
DEFAULT_DISCLAIMER = "Facts-only. No investment advice."

# Advice / comparison cues (deterministic; complements Phase 4 classifier)
_ADVICE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bshould you\b",
        r"\bshould i\b",
        r"\bi recommend\b",
        r"\brecommend(?:ed|ing)?\b",
        r"\bbetter (?:fund|choice|option)\b",
        r"\bbest fund\b",
        r"\bworth investing\b",
        r"\bbuy or sell\b",
        r"\byou should (?:buy|invest|sell)\b",
        r"\bgo for\b",
        r"\bmust invest\b",
        r"\bideal for (?:you|investors who want)\b",
    )
)

# Split sentences without treating 1.02% as a boundary
_SENTENCE_SPLIT = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z\"'])|(?<=[.!?])\s*$",
)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": list(self.errors)}


def count_sentences(text: str) -> int:
    """Count sentences; ignore decimal points inside numbers (e.g. 1.02%)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    # Protect decimals: 1.02 -> 1<DOT>02
    protected = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", cleaned)
    parts = [p.strip() for p in re.split(r"[.!?]+", protected) if p.strip()]
    return len(parts)


def _has_advice_language(text: str) -> list[str]:
    hits: list[str] = []
    for pat in _ADVICE_PATTERNS:
        if pat.search(text or ""):
            hits.append(pat.pattern)
    return hits


def _normalize_footer_date(footer: str) -> str | None:
    m = re.search(
        rf"{re.escape(FOOTER_PREFIX)}\s*(\d{{4}}-\d{{2}}-\d{{2}})",
        footer or "",
        flags=re.IGNORECASE,
    )
    return m.group(1) if m else None


def validate_response(
    payload: dict[str, Any],
    *,
    allowed_citation_urls: Sequence[str] | None = None,
    max_sentences: int = 3,
) -> tuple[bool, list[str]]:
    """
    Validate an Architecture response package.

    Returns (ok, error_codes_or_messages). Prefer `validate()` for structured result.
    """
    result = validate(
        payload,
        allowed_citation_urls=allowed_citation_urls,
        max_sentences=max_sentences,
    )
    return result.ok, result.errors


def validate(
    payload: dict[str, Any],
    *,
    allowed_citation_urls: Sequence[str] | Iterable[str] | None = None,
    max_sentences: int = 3,
    require_disclaimer: str | None = None,
) -> ValidationResult:
    """Full Response Validator checks."""
    errors: list[str] = []
    disclaimer = require_disclaimer or get_settings().disclaimer or DEFAULT_DISCLAIMER

    if not isinstance(payload, dict):
        return ValidationResult(ok=False, errors=["payload_not_object"])

    resp_type = payload.get("type")
    if resp_type not in ("answer", "refusal"):
        errors.append("invalid_type")

    text = str(payload.get("text") or "").strip()
    if not text:
        errors.append("missing_text")
    else:
        n = count_sentences(text)
        if n > max_sentences:
            errors.append(f"too_many_sentences:{n}>{max_sentences}")
        advice_hits = _has_advice_language(text)
        if advice_hits:
            errors.append("advice_language")

    citation = payload.get("citation")
    if not isinstance(citation, dict):
        errors.append("missing_citation")
        citation_url = ""
    else:
        citation_url = str(citation.get("url") or "").strip()
        citation_title = str(citation.get("title") or "").strip()
        if not citation_url:
            errors.append("missing_citation_url")
        elif not is_allowed_source_url(citation_url):
            errors.append("citation_domain_not_allowlisted")
        if not citation_title:
            errors.append("missing_citation_title")

    if allowed_citation_urls is not None and citation_url:
        allowed = {u.strip() for u in allowed_citation_urls if u and str(u).strip()}
        if allowed and citation_url not in allowed:
            errors.append("citation_not_from_retrieval")

    footer = str(payload.get("footer") or "").strip()
    if not footer:
        errors.append("missing_footer")
    elif _normalize_footer_date(footer) is None:
        errors.append("footer_missing_date")

    got_disclaimer = str(payload.get("disclaimer") or "").strip()
    if got_disclaimer != disclaimer:
        errors.append("missing_or_wrong_disclaimer")

    return ValidationResult(ok=len(errors) == 0, errors=errors)

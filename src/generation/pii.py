"""
PII guard — block personal data before any Groq call (Phase 4).

Architecture: PAN / Aadhaar / OTP / email / phone must never reach the LLM,
and no user accounts or PII are stored. Detection runs first in the Query
Classifier, ahead of every other rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PII_PAN = "pan"
PII_AADHAAR = "aadhaar"
PII_EMAIL = "email"
PII_PHONE = "phone"
PII_OTP = "otp"
PII_ACCOUNT = "account"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (PII_PAN, re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    (PII_AADHAAR, re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")),
    (PII_EMAIL, re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    (PII_PHONE, re.compile(r"(?:\+91[\s-]?)?\b[6-9]\d{9}\b")),
    (PII_OTP, re.compile(r"\botp\b[^0-9]{0,20}\d{4,8}\b", re.IGNORECASE)),
    (PII_OTP, re.compile(r"\b(?:otp|one[\s-]?time password)\b", re.IGNORECASE)),
)

# Account / folio talk carries no regex-detectable value but is still a
# personal-account request, which we neither serve nor log.
_ACCOUNT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bmy (?:folio|account|portfolio|holdings?|units?|balance|statement|investments?)\b",
        r"\bfolio (?:number|no\.?|id)\b",
        r"\baccount (?:number|no\.?|balance|statement)\b",
        r"\b(?:kyc|aadhaar|aadhar|pan card)\b",
        r"\bmy (?:kyc|pan)\b",
        r"\bredeem my\b",
        r"\bcheck my\b",
    )
)

_REDACTION = "[redacted]"


@dataclass(frozen=True)
class PIIFinding:
    """What was detected, without ever keeping the matched value."""

    kinds: tuple[str, ...] = field(default_factory=tuple)

    @property
    def found(self) -> bool:
        return bool(self.kinds)


def detect_pii(message: str) -> PIIFinding:
    """Return the kinds of personal data present. Never returns the values."""
    text = message or ""
    kinds: list[str] = []
    for kind, pattern in _PATTERNS:
        if kind not in kinds and pattern.search(text):
            kinds.append(kind)
    if PII_ACCOUNT not in kinds and any(p.search(text) for p in _ACCOUNT_PATTERNS):
        kinds.append(PII_ACCOUNT)
    return PIIFinding(kinds=tuple(kinds))


def contains_pii(message: str) -> bool:
    return detect_pii(message).found


def redact(message: str) -> str:
    """Mask detected values — for log lines only, never for an LLM prompt."""
    text = message or ""
    for _kind, pattern in _PATTERNS:
        text = pattern.sub(_REDACTION, text)
    return text

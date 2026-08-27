"""
Query Classifier — decide *before* retrieval whether we should answer (Phase 4).

Intents follow the Architecture wording: factual, advisory, comparative,
performance calc, PII / account, out of scope. Deterministic keyword rules
decide the common cases at zero token cost; a small Groq check runs only when
the rules are genuinely undecided (see the free-tier budget in Architecture).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from src.config.settings import Settings, get_settings
from src.generation.pii import detect_pii

logger = logging.getLogger(__name__)

Intent = Literal[
    "factual",
    "advisory",
    "comparative",
    "performance",
    "pii_account",
    "out_of_scope",
]

INTENTS: tuple[Intent, ...] = (
    "factual",
    "advisory",
    "comparative",
    "performance",
    "pii_account",
    "out_of_scope",
)

_ADVISORY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bshould i\b",
        r"\bshould we\b",
        r"\bshall i\b",
        r"\bcan you (?:suggest|advise|recommend)\b",
        r"\brecommend\b",
        r"\bsuggest (?:a|an|any|some|the best)\b",
        r"\badvi[sc]e\b",
        r"\bworth (?:investing|buying|it)\b",
        r"\bgood (?:fund|investment|option|choice|idea)\b",
        r"\bbest (?:fund|scheme|option|plan)\b",
        r"\bsafe to invest\b",
        r"\bis it safe\b",
        r"\bbuy or sell\b",
        r"\bshould .{0,20}\binvest\b",
        r"\bsuitable for\b",
        r"\bgood for (?:me|retirement|long term|short term)\b",
        r"\bwhich fund (?:should|to)\b",
        r"\bhow much should i\b",
        r"\bwhere should i (?:invest|put)\b",
        r"\bwill it (?:grow|rise|fall|do well)\b",
        r"\bpredict\b",
    )
)

_COMPARATIVE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwhich (?:one )?is better\b",
        r"\bwhich is (?:the )?(?:best|better|safer)\b",
        r"\bbetter (?:than|fund|option|choice)\b",
        r"\bcompare\b",
        r"\bcomparison\b",
        r"\bvs\.?\b",
        r"\bversus\b",
        r"\brank(?:ing|ed)?\b",
        r"\btop \d+ (?:funds?|schemes?)\b",
        r"\bdifference between\b",
        r"\bor\b.{0,40}\bwhich (?:should|one)\b",
        r"\boutperform",
    )
)

# Hypothetical growth wording counts as a performance calculation too.
_PERFORMANCE_EXTRA: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwhat would it be worth\b",
        r"\bwould (?:it|that|my money) (?:be worth|have grown)\b",
        r"\bif i had invested\b",
        r"\bgrown to\b",
        r"\bvalue (?:today|now)\b",
    )
)

# Vocabulary that marks a question as being about our corpus at all.
_DOMAIN_TERMS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bmutual fund\b",
        r"\bhdfc\b",
        r"\belss\b",
        r"\bsip\b",
        r"\btax saver\b",
        r"\blarge cap\b",
        r"\bmid cap\b",
        r"\bsmall cap\b",
        r"\bgold fund\b",
        r"\bscheme\b",
        r"\bdirect (?:plan|growth)\b",
        r"\bfund\b",
    )
)

# The specific facts our corpus stores — these make a question answerable.
_FACT_TERMS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bexpense ratio\b",
        r"\bexit load\b",
        r"\block[\s-]?in\b",
        r"\bbenchmark\b",
        r"\bfund manager\b",
        r"\bminimum (?:investment|sip|amount|application)\b",
        r"\bmin(?:imum)? sip\b",
        r"\binvestment objective\b",
        r"\bobjective\b",
        r"\bfund size\b",
        r"\baum\b",
        r"\brisk(?:ometer| level)?\b",
        r"\bcategory\b",
        r"\bexpense\b",
        r"\bplan type\b",
    )
)

CLASSIFIER_SYSTEM_PROMPT = """You label questions for a facts-only mutual fund FAQ assistant.
Reply with exactly one word from this list and nothing else:
factual, advisory, comparative, performance, out_of_scope

factual = asks for a published detail of one scheme (expense ratio, exit load, minimum SIP, lock-in, benchmark, objective, fund manager)
advisory = asks whether to invest, what suits the user, or any opinion
comparative = asks to compare, rank, or pick between funds
performance = asks about returns, NAV history, or what an investment would be worth
out_of_scope = anything else"""


@dataclass(frozen=True)
class Classification:
    """Intent plus why it was chosen — `source` is 'rules', 'groq', or 'default'."""

    intent: Intent
    source: str = "rules"
    reason: str = ""
    pii_kinds: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_answerable(self) -> bool:
        """Only factual questions reach the Generator."""
        return self.intent == "factual"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"intent": self.intent, "source": self.source}
        if self.reason:
            d["reason"] = self.reason
        if self.pii_kinds:
            d["pii_kinds"] = list(self.pii_kinds)
        return d


def _first_match(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pat in patterns:
        if pat.search(text):
            return pat.pattern
    return None


def _looks_in_domain(text: str) -> bool:
    return any(p.search(text) for p in _DOMAIN_TERMS)


def _names_a_stored_fact(text: str) -> bool:
    return any(p.search(text) for p in _FACT_TERMS)


def classify_rules(message: str) -> Classification | None:
    """
    Deterministic pass. Returns None when the rules are undecided.

    Order is deliberate: PII first (never reaches Groq), then refusal
    intents, then factual. Every branch here costs zero tokens.
    """
    text = (message or "").strip()
    if not text:
        return Classification("out_of_scope", reason="empty_message")

    finding = detect_pii(text)
    if finding.found:
        return Classification("pii_account", reason="pii_detected", pii_kinds=finding.kinds)

    hit = _first_match(_COMPARATIVE_PATTERNS, text)
    if hit:
        return Classification("comparative", reason=hit)

    hit = _first_match(_ADVISORY_PATTERNS, text)
    if hit:
        return Classification("advisory", reason=hit)

    # Late import keeps generator/classifier import order simple
    from src.generation.generator import is_performance_query

    if is_performance_query(text) or _first_match(_PERFORMANCE_EXTRA, text):
        return Classification("performance", reason="performance_query")

    in_domain = _looks_in_domain(text)
    if _names_a_stored_fact(text):
        # Naming a stored fact is enough; if no scheme is named the Retriever
        # asks which one, still without spending a Groq call.
        return Classification("factual", reason="fact_term")

    if not in_domain:
        # Nothing ties this to our corpus — refuse for free rather than ask Groq
        return Classification("out_of_scope", reason="no_domain_terms")

    # In-domain but no fact named ("tell me about the ELSS fund") — genuinely fuzzy
    return None


def classify_with_groq(
    message: str,
    *,
    client: Any | None = None,
    settings: Settings | None = None,
) -> Classification | None:
    """
    One short Groq call on the fast model for genuinely fuzzy input.

    Returns None if the call fails, is over budget, or the label is unusable —
    the caller then falls back to out_of_scope (safe default).
    """
    cfg = settings or get_settings()
    from src.generation.groq_client import GroqClient, GroqClientError

    groq = client or GroqClient(settings=cfg)
    try:
        result = groq.chat(
            [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": (message or "").strip()},
            ],
            use_fast=True,
            temperature=0.0,
        )
    except GroqClientError as exc:
        logger.warning("Groq classify unavailable: %s", exc)
        return None

    label = (result.text or "").strip().lower().split()[:1]
    if not label:
        return None
    word = label[0].strip(".,:;\"'")
    if word not in INTENTS or word == "pii_account":
        return None
    return Classification(word, source="groq", reason="groq_label")


def classify(
    message: str,
    *,
    client: Any | None = None,
    settings: Settings | None = None,
    allow_groq: bool | None = None,
) -> Classification:
    """
    Full Query Classifier: rules first, optional Groq for fuzzy input.

    Unknown input defaults to out_of_scope so we refuse rather than guess.
    """
    cfg = settings or get_settings()
    decided = classify_rules(message)
    if decided is not None:
        return decided

    use_groq = cfg.classifier_groq_fallback if allow_groq is None else allow_groq
    if use_groq:
        guessed = classify_with_groq(message, client=client, settings=cfg)
        if guessed is not None:
            return guessed

    return Classification("out_of_scope", source="default", reason="no_rule_match")

"""
Generator — Groq writes a short answer from retrieved context only (Phase 3).

Primary model: settings.groq_model (`openai/gpt-oss-120b`).
Validator retry: settings.groq_model_fast (`openai/gpt-oss-20b`).
Citation / footer / disclaimer are attached from retrieval metadata (never invented).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal, Sequence

from src.config.settings import Settings, get_settings, load_schemes
from src.generation.groq_client import GroqAPIError, GroqClient, GroqClientError, get_groq_client
from src.generation.validator import DEFAULT_DISCLAIMER, FOOTER_PREFIX, validate
from src.retrieval.retriever import RetrievedChunk, RetrievalResult

logger = logging.getLogger(__name__)

ResponseType = Literal["answer", "refusal"]

SYSTEM_PROMPT = """You are a facts-only mutual fund FAQ assistant.
Answer ONLY using the provided context. Do not use outside knowledge.
Maximum 3 sentences. Be calm and literal.
No investment advice, recommendations, comparisons, rankings, or return calculations.
Do not invent numbers. If the context is insufficient, say you could not verify it from the provided sources.
Do not include URLs, footers, or disclaimers in your reply — plain answer text only."""

STRICT_SYSTEM_PROMPT = """You are a facts-only mutual fund FAQ assistant. STRICT MODE.
Use ONLY the context below. Max 2 short sentences.
State the fact plainly. No advice, no comparisons, no predictions, no returns math.
No URLs, no footer, no disclaimer — answer text only."""

_PERFORMANCE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\breturns?\b",
        r"\bcagr\b",
        r"\bperformance\b",
        r"\bnav\b",
        r"\bgain(?:ed|s)?\b",
        r"\bprofit\b",
        r"\bif i invest\b",
        r"\bhow much (?:will|would) i\b",
        r"\bprojected\b",
        r"\bannuali[sz]ed\b",
        # hypothetical growth phrasing ("if I had invested … what would it be worth")
        r"\bif i had invested\b",
        r"\bwould (?:it|that|my money|my investment) (?:be worth|have grown)\b",
        r"\bwhat would it be worth\b",
        r"\bgrown to\b",
        r"\bvalue (?:today|now)\b",
    )
)


@dataclass
class AssistantResponse:
    """Architecture response contract (answer or refusal-shaped package)."""

    type: ResponseType
    text: str
    citation: dict[str, str]
    footer: str
    disclaimer: str
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.type,
            "text": self.text,
            "citation": dict(self.citation),
            "footer": self.footer,
            "disclaimer": self.disclaimer,
        }
        if self.meta:
            d["meta"] = dict(self.meta)
        return d


def is_performance_query(question: str) -> bool:
    """True when the ask is about returns / performance (skip Groq generation)."""
    q = (question or "").strip()
    if not q:
        return False
    return any(p.search(q) for p in _PERFORMANCE_PATTERNS)


def _footer_for(document_date: str | None, ingested_at: str | None = None) -> str:
    if document_date and re.match(r"^\d{4}-\d{2}-\d{2}$", document_date.strip()):
        day = document_date.strip()
    elif ingested_at and len(ingested_at) >= 10 and ingested_at[4] == "-":
        day = ingested_at[:10]
    else:
        day = date.today().isoformat()
    return f"{FOOTER_PREFIX} {day}"


def _disclaimer(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    return cfg.disclaimer or DEFAULT_DISCLAIMER


def _refusal_citation() -> dict[str, str]:
    refusal = load_schemes().get("refusal") or {}
    return {
        "url": str(refusal.get("url") or "https://groww.in/p/mutual-funds"),
        "title": str(refusal.get("title") or "Mutual Funds on Groww"),
    }


def refusal_citation() -> dict[str, str]:
    """Groww educational link used by the Refusal Handler."""
    return _refusal_citation()


def package_response(
    *,
    resp_type: ResponseType,
    text: str,
    citation: dict[str, str],
    document_date: str | None = None,
    ingested_at: str | None = None,
    settings: Settings | None = None,
    meta: dict[str, Any] | None = None,
) -> AssistantResponse:
    """Public packager (citation + footer + disclaimer) for non-generated replies."""
    return _package(
        resp_type=resp_type,
        text=text,
        citation=citation,
        document_date=document_date,
        ingested_at=ingested_at,
        settings=settings,
        meta=meta,
    )


def _context_block(chunks: Sequence[RetrievedChunk | dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, c in enumerate(chunks, start=1):
        if isinstance(c, RetrievedChunk):
            text = c.text
            meta = (
                f"scheme={c.scheme_name}; fact={c.fact_key}; "
                f"section={c.page_or_section}; source={c.source_url}"
            )
        else:
            text = str(c.get("text") or "")
            meta = (
                f"scheme={c.get('scheme_name')}; fact={c.get('fact_key')}; "
                f"source={c.get('source_url')}"
            )
        lines.append(f"[{i}] ({meta})\n{text}")
    return "\n\n".join(lines)


def build_user_prompt(
    question: str,
    contexts: Sequence[RetrievedChunk | dict[str, Any]],
) -> str:
    return (
        f"Context:\n{_context_block(contexts)}\n\n"
        f"User question: {question.strip()}\n\n"
        "Answer in at most 3 sentences using only the context."
    )


def _package(
    *,
    resp_type: ResponseType,
    text: str,
    citation: dict[str, str],
    document_date: str | None,
    ingested_at: str | None = None,
    settings: Settings | None = None,
    meta: dict[str, Any] | None = None,
) -> AssistantResponse:
    return AssistantResponse(
        type=resp_type,
        text=text.strip(),
        citation=citation,
        footer=_footer_for(document_date, ingested_at),
        disclaimer=_disclaimer(settings),
        meta=meta,
    )


def groww_link_fallback(
    *,
    reason: str,
    citation: dict[str, str],
    document_date: str | None = None,
    ingested_at: str | None = None,
    settings: Settings | None = None,
    message: str | None = None,
) -> AssistantResponse:
    """Safe Groww page link when generation/validation fails (still Groq-only stack)."""
    text = message or (
        "I couldn't produce a verified short answer from our sources. "
        "Please see the Groww scheme page linked below for the latest details."
    )
    return _package(
        resp_type="answer",
        text=text,
        citation=citation,
        document_date=document_date,
        ingested_at=ingested_at,
        settings=settings,
        meta={"fallback": True, "reason": reason},
    )


def performance_link_response(
    *,
    citation: dict[str, str],
    document_date: str | None = None,
    ingested_at: str | None = None,
    settings: Settings | None = None,
) -> AssistantResponse:
    """Architecture: performance / returns → Groww page link only, no calculated returns."""
    return _package(
        resp_type="answer",
        text=(
            "I do not calculate or quote investment returns. "
            "Please check performance figures on the Groww scheme page linked below."
        ),
        citation=citation,
        document_date=document_date,
        ingested_at=ingested_at,
        settings=settings,
        meta={"performance_bypass": True},
    )


def generate_answer(
    question: str,
    contexts: list[dict] | list[RetrievedChunk],
    *,
    client: GroqClient | None = None,
    use_fast: bool = False,
    strict: bool = False,
    settings: Settings | None = None,
) -> str:
    """
    Call Groq to phrase answer text from contexts only.

    Returns plain text (no citation/footer). Raises GroqClientError on failure.
    """
    cfg = settings or get_settings()
    groq = client or get_groq_client()
    system = STRICT_SYSTEM_PROMPT if strict else SYSTEM_PROMPT
    result = groq.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": build_user_prompt(question, contexts)},
        ],
        use_fast=use_fast,
        temperature=cfg.groq_temperature,
        max_tokens=cfg.groq_max_tokens,
    )
    return result.text.strip()


def _allowed_urls_from_retrieval(retrieval: RetrievalResult) -> list[str]:
    urls: list[str] = []
    if retrieval.winner and retrieval.winner.source_url:
        urls.append(retrieval.winner.source_url)
    for c in retrieval.candidates:
        if c.source_url and c.source_url not in urls:
            urls.append(c.source_url)
    if retrieval.fallback_url and retrieval.fallback_url not in urls:
        urls.append(retrieval.fallback_url)
    return urls


def generate_from_retrieval(
    question: str,
    retrieval: RetrievalResult,
    *,
    client: GroqClient | None = None,
    settings: Settings | None = None,
) -> AssistantResponse:
    """
    Full Phase-3 path: performance bypass → Groq generate → validate →
    fast retry → Groww link fallback.
    """
    cfg = settings or get_settings()
    groq = client or GroqClient(settings=cfg)

    # Citation always from stored metadata when we have a winner
    if retrieval.ok and retrieval.winner:
        citation = retrieval.winner.citation
        doc_date = retrieval.winner.document_date
        ingested = retrieval.winner.ingested_at
        contexts: list[RetrievedChunk] = [retrieval.winner] + [
            c for c in retrieval.candidates if c.chunk_id != retrieval.winner.chunk_id
        ][:2]
    else:
        # Low confidence / no scheme: still may have fallback Groww URL
        citation = {
            "url": retrieval.fallback_url or _refusal_citation()["url"],
            "title": "Groww",
        }
        # Prefer registry title for refusal overview
        if citation["url"].endswith("/p/mutual-funds"):
            citation = _refusal_citation()
        doc_date = None
        ingested = None
        contexts = []

    if is_performance_query(question):
        # Prefer scheme page when known
        if retrieval.hints.scheme_id and retrieval.fallback_url:
            citation = {
                "url": retrieval.fallback_url,
                "title": (
                    f"{retrieval.winner.scheme_name} — Groww"
                    if retrieval.winner
                    else "Groww scheme page"
                ),
            }
        elif retrieval.ok and retrieval.winner:
            citation = retrieval.winner.citation
        return performance_link_response(
            citation=citation,
            document_date=doc_date,
            ingested_at=ingested,
            settings=cfg,
        )

    if not retrieval.ok or not contexts:
        msg = retrieval.message or (
            "I couldn't find verified information for that query in our sources."
        )
        return groww_link_fallback(
            reason=retrieval.status,
            citation=citation,
            document_date=doc_date,
            ingested_at=ingested,
            settings=cfg,
            message=msg,
        )

    allowed = _allowed_urls_from_retrieval(retrieval)

    def _try(text: str, *, attempt: str) -> AssistantResponse | None:
        packaged = _package(
            resp_type="answer",
            text=text,
            citation=citation,
            document_date=doc_date,
            ingested_at=ingested,
            settings=cfg,
            meta={"attempt": attempt, "model_path": attempt},
        )
        result = validate(
            packaged.to_dict(),
            allowed_citation_urls=allowed,
        )
        if result.ok:
            return packaged
        logger.info("Validator rejected (%s): %s", attempt, result.errors)
        return None

    # Attempt 1 — primary model
    try:
        draft = generate_answer(
            question,
            contexts,
            client=groq,
            use_fast=False,
            strict=False,
            settings=cfg,
        )
        ok = _try(draft, attempt="primary")
        if ok:
            return ok
    except GroqClientError as exc:
        logger.warning("Primary Groq generation failed: %s", exc)

    # Attempt 2 — fast model + stricter prompt
    try:
        draft = generate_answer(
            question,
            contexts,
            client=groq,
            use_fast=True,
            strict=True,
            settings=cfg,
        )
        ok = _try(draft, attempt="fast_retry")
        if ok:
            return ok
    except GroqClientError as exc:
        logger.warning("Fast Groq retry failed: %s", exc)

    return groww_link_fallback(
        reason="validation_or_generation_failed",
        citation=citation,
        document_date=doc_date,
        ingested_at=ingested,
        settings=cfg,
    )

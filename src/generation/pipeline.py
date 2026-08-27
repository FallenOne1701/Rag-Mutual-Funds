"""
Online query path (Phase 4) — Query Classifier → Refusal Handler | Retriever →
Generator → Response Validator.

Only factual questions reach Groq. Advisory, comparative, performance, PII /
account and out-of-scope questions are settled by deterministic guardrails, so
a refusal costs zero tokens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.config.settings import Settings, get_settings
from src.generation.classifier import Classification, classify
from src.generation.generator import (
    AssistantResponse,
    generate_from_retrieval,
    performance_link_response,
    refusal_citation,
)
from src.generation.refusal import refuse
from src.generation.validator import validate

logger = logging.getLogger(__name__)


@dataclass
class ChatOutcome:
    """Response plus how it was reached (intent, retrieval status, validation)."""

    response: AssistantResponse
    classification: Classification
    retrieval_status: str | None = None
    validated: bool = True
    validation_errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = self.response.to_dict()
        payload.setdefault("meta", {})
        payload["meta"].update(
            {
                "intent": self.classification.intent,
                "intent_source": self.classification.source,
            }
        )
        if self.retrieval_status:
            payload["meta"]["retrieval_status"] = self.retrieval_status
        return payload


def _truncate(message: str, settings: Settings) -> tuple[str, bool]:
    limit = settings.max_message_chars
    text = (message or "").strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip(), True
    return text, False


def _performance_response(
    question: str,
    retriever: Any,
    settings: Settings,
) -> tuple[AssistantResponse, str | None]:
    """Scheme-page link only — no Groq call, no computed returns."""
    citation = refusal_citation()
    doc_date = None
    status: str | None = None
    try:
        retrieval = retriever.retrieve(question)
        status = retrieval.status
        if retrieval.winner:
            citation = {
                "url": retrieval.winner.source_url,
                "title": f"{retrieval.winner.scheme_name} — Groww",
            }
            doc_date = retrieval.winner.document_date
        elif retrieval.fallback_url:
            citation = {"url": retrieval.fallback_url, "title": "Groww scheme page"}
    except Exception as exc:  # retrieval is local; never block the refusal on it
        logger.warning("Retrieval failed on performance query: %s", exc)

    return (
        performance_link_response(citation=citation, document_date=doc_date, settings=settings),
        status,
    )


def answer_question(
    message: str,
    *,
    retriever: Any | None = None,
    client: Any | None = None,
    settings: Settings | None = None,
) -> ChatOutcome:
    """Run one user message through the full online query path."""
    cfg = settings or get_settings()
    question, truncated = _truncate(message, cfg)

    classification = classify(question, client=client, settings=cfg)
    logger.info(
        "intent=%s source=%s", classification.intent, classification.source
    )

    if classification.intent == "performance":
        if retriever is None:
            from src.retrieval.retriever import Retriever

            retriever = Retriever()
        response, status = _performance_response(question, retriever, cfg)
    elif not classification.is_answerable:
        response = refuse(classification, settings=cfg)
        status = None
    else:
        if retriever is None:
            from src.retrieval.retriever import Retriever

            retriever = Retriever()
        retrieval = retriever.retrieve(question)
        status = retrieval.status
        response = generate_from_retrieval(question, retrieval, client=client, settings=cfg)

    if truncated and response.meta is not None:
        response.meta["truncated_input"] = True

    checks = validate(response.to_dict())
    if not checks.ok:
        logger.warning("Validator rejected final package: %s", checks.errors)

    return ChatOutcome(
        response=response,
        classification=classification,
        retrieval_status=status,
        validated=checks.ok,
        validation_errors=checks.errors or None,
    )

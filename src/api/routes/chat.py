"""
Chat routes — POST /chat and GET /schemes (Phase 5).

`/chat` runs the online query path: Query Classifier → Refusal Handler or
Retriever → Generator → Response Validator. Every reply, including failures,
comes back in the Architecture response contract so the UI always has a
citation, footer, and disclaimer to render.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.api.deps import get_retriever, list_schemes
from src.api.schemas import ChatRequest, ChatResponse, SchemesResponse
from src.config.settings import get_settings
from src.generation.generator import groww_link_fallback, refusal_citation
from src.generation.pipeline import answer_question

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> dict:
    """Answer one user message, or refuse politely with the educational link."""
    cfg = get_settings()
    try:
        outcome = answer_question(request.message, retriever=get_retriever(), settings=cfg)
    except Exception as exc:  # degrade to a Groww link rather than a 500
        logger.exception("Chat pipeline failed: %s", exc)
        fallback = groww_link_fallback(
            reason="internal_error",
            citation=refusal_citation(),
            document_date=None,
            settings=cfg,
        )
        return fallback.to_dict()

    if not outcome.validated:
        logger.warning("Serving a package the validator rejected: %s", outcome.validation_errors)
    return outcome.to_dict()


@router.get("/schemes", response_model=SchemesResponse)
def schemes() -> dict:
    """Schemes in the corpus — lets the UI suggest questions it can answer."""
    entries = list_schemes()
    return {"count": len(entries), "schemes": entries}

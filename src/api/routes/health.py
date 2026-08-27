"""Health route — is the service, the index, and the Groq config up? (Phase 5)."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.deps import index_status
from src.api.schemas import HealthResponse
from src.config.settings import get_settings
from src.generation.budget import get_budget

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> dict:
    cfg = get_settings()
    ready, vectors, collection, detail = index_status(cfg)
    key = (cfg.groq_api_key or "").strip()
    configured = bool(key) and not key.startswith("your_groq")
    used = get_budget().snapshot()

    return {
        "status": "ok" if (ready and configured) else "degraded",
        "phase": "5",
        "index": {
            "ready": ready,
            "vectors": vectors,
            "collection": collection,
            "detail": detail if detail else None,
        },
        "groq": {
            "configured": configured,
            "model": cfg.groq_model,
            "model_fast": cfg.groq_model_fast,
            "requests_today": used.requests_day,
            "tokens_today": used.tokens_day,
        },
        "disclaimer": cfg.disclaimer,
    }

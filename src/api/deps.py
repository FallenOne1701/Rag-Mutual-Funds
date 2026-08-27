"""
Shared API dependencies (Phase 5).

The Retriever holds the local embedding model and the Chroma collection, so it
is built once per process and reused across requests.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from src.config.settings import Settings, get_settings, load_schemes

logger = logging.getLogger(__name__)

_retriever: Any | None = None
_lock = threading.Lock()


def get_retriever() -> Any:
    """Process-wide Retriever (loads the embedding model on first use)."""
    global _retriever
    with _lock:
        if _retriever is None:
            from src.retrieval.retriever import Retriever

            logger.info("Loading Retriever (embedding model + Chroma collection)")
            _retriever = Retriever()
        return _retriever


def set_retriever(retriever: Any | None) -> None:
    """Inject a Retriever (tests) or clear the cached one."""
    global _retriever
    with _lock:
        _retriever = retriever


def index_status(settings: Settings | None = None) -> tuple[bool, int | None, str, str | None]:
    """(ready, vector_count, collection_name, detail) for the health check."""
    cfg = settings or get_settings()
    collection = cfg.chroma_collection_name
    try:
        count = get_retriever().vector_count()
    except Exception as exc:  # index missing or unreadable
        return False, None, collection, f"{type(exc).__name__}: {exc}"
    if not count:
        return False, 0, collection, "Index is empty — run: python scripts/ingest.py"
    return True, int(count), collection, None


def list_schemes(settings: Settings | None = None) -> list[dict[str, str]]:
    """Scheme registry entries for `GET /schemes` (UI hints)."""
    cfg = settings or get_settings()
    registry = load_schemes(cfg.schemes_path)
    return [
        {
            "scheme_id": str(s.get("scheme_id") or ""),
            "scheme_name": str(s.get("scheme_name") or ""),
            "category": str(s.get("category") or ""),
            "url": str(s.get("url") or ""),
        }
        for s in registry.get("schemes", [])
    ]

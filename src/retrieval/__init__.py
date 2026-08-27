"""Retrieval — Embedding Service, query parsing, and Retriever (Phase 2)."""

from __future__ import annotations

from typing import Any

from src.retrieval.embedder import (
    EmbeddingService,
    embed_texts,
    get_embedding_service,
)
from src.retrieval.query_parser import (
    QueryHints,
    detect_fact_key,
    detect_schemes,
    parse_query,
)

__all__ = [
    "EmbeddingService",
    "QueryHints",
    "RetrievedChunk",
    "RetrievalResult",
    "Retriever",
    "detect_fact_key",
    "detect_schemes",
    "embed_texts",
    "get_embedding_service",
    "parse_query",
    "retrieve",
]


def __getattr__(name: str) -> Any:
    # Lazy: Retriever imports open_collection from indexer; avoid circular import
    # when ingestion loads the Embedding Service during corpus build.
    if name in {
        "RetrievedChunk",
        "RetrievalResult",
        "Retriever",
        "retrieve",
    }:
        from src.retrieval import retriever as _retriever

        return getattr(_retriever, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

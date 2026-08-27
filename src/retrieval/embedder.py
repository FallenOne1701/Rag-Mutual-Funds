"""
Embedding Service — local vectors (Architecture §3 / §11).

Same model at offline ingest and online query time. Groq does not provide
embeddings; we use sentence-transformers (`BAAI/bge-small-en-v1.5` by default).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol, Sequence

from src.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# BGE retrieval instruction for queries (documents stay unprefixed).
_BGE_QUERY_INSTRUCTION = (
    "Represent this sentence for searching relevant passages: "
)


class Embedder(Protocol):
    """Minimal protocol so tests can inject a fake without loading the model."""

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...


class EmbeddingService:
    """
    Local Embedding Service wrapping sentence-transformers.

    - Documents: encoded as-is (ingest / Vector Store).
    - Queries: BGE instruction prefix for asymmetric retrieval (Phase 2).
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        settings: Settings | None = None,
        model: object | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._model_name = model_name or cfg.embedding_model_name
        self._batch_size = getattr(cfg, "embedding_batch_size", 32)
        self._model = model  # lazy-loaded unless injected
        self._dimension: int | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            # Probe once via a tiny encode
            vec = self.embed_documents(["dimension probe"])[0]
            self._dimension = len(vec)
        return self._dimension

    def _get_model(self) -> object:
        if self._model is None:
            logger.info("Loading embedding model: %s", self._model_name)
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            logger.info("Embedding model ready: %s", self._model_name)
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed corpus snippets for the Vector Store (no query instruction)."""
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(  # type: ignore[attr-defined]
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [list(map(float, row)) for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed a user question (BGE query instruction + normalize)."""
        prefixed = f"{_BGE_QUERY_INSTRUCTION}{text.strip()}"
        return self.embed_documents([prefixed])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Module-level helper: embed document texts with the shared service."""
    return get_embedding_service().embed_documents(texts)


@lru_cache
def get_embedding_service() -> EmbeddingService:
    """Process-wide Embedding Service (loads the local model once)."""
    return EmbeddingService()

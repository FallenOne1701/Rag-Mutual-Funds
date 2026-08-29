"""
Retriever — metadata-first dense search over Groww fact chunks (Phase 2).

Flow (implementation-plan Step 2):
  parse scheme/fact → embed query → Chroma (scheme filter when known)
  → soft-prefer matching fact_key → one winner + citation metadata.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.config.settings import Settings, get_settings, load_schemes
from src.retrieval.embedder import Embedder, get_embedding_service
from src.retrieval.query_parser import QueryHints, parse_query

logger = logging.getLogger(__name__)

RetrievalStatus = Literal[
    "ok",
    "low_confidence",
    "ambiguous_scheme",
    "no_scheme",
    "empty",
]

# Soft preference: matching fact_key sorts above others (then by similarity).
_FACT_MATCH_SORT_KEY = 1


@dataclass
class RetrievedChunk:
    """One Vector Store hit with Architecture metadata + similarity."""

    chunk_id: str
    text: str
    similarity: float
    distance: float
    scheme_id: str
    scheme_name: str
    category: str
    source_url: str
    fact_key: str
    page_or_section: str
    document_date: str | None
    ingested_at: str | None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def citation(self) -> dict[str, str]:
        """Citation package — URL always from stored metadata."""
        title = f"{self.scheme_name} — Groww" if self.scheme_name else "Groww"
        return {"url": self.source_url, "title": title}


@dataclass
class RetrievalResult:
    """Outcome of one retrieve() call."""

    status: RetrievalStatus
    query: str
    hints: QueryHints
    winner: RetrievedChunk | None = None
    candidates: list[RetrievedChunk] = field(default_factory=list)
    fallback_url: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.winner is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query": self.query,
            "detected_scheme_id": self.hints.scheme_id,
            "detected_scheme_ids": list(self.hints.scheme_ids),
            "detected_fact_key": self.hints.fact_key,
            "ambiguous_scheme": self.hints.ambiguous_scheme,
            "winner": self.winner.to_dict() if self.winner else None,
            "citation": self.winner.citation if self.winner else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "fallback_url": self.fallback_url,
            "message": self.message,
        }


def _scheme_url_map(schemes: list[dict[str, Any]]) -> dict[str, str]:
    return {str(s["scheme_id"]): str(s["url"]) for s in schemes}


def _refusal_url(registry: dict[str, Any] | None = None) -> str:
    data = registry or load_schemes()
    refusal = data.get("refusal") or {}
    return str(refusal.get("url") or "https://groww.in/p/mutual-funds")


def _distance_to_similarity(distance: float) -> float:
    """Chroma cosine space: distance in [0, 2]; similarity ≈ 1 - distance."""
    return 1.0 - float(distance)


def _hit_from_chroma(
    chunk_id: str,
    document: str,
    metadata: dict[str, Any],
    distance: float,
) -> RetrievedChunk:
    meta = dict(metadata or {})
    doc_date = meta.get("document_date") or None
    if doc_date == "":
        doc_date = None
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=document or "",
        similarity=_distance_to_similarity(distance),
        distance=float(distance),
        scheme_id=str(meta.get("scheme_id") or ""),
        scheme_name=str(meta.get("scheme_name") or ""),
        category=str(meta.get("category") or ""),
        source_url=str(meta.get("source_url") or ""),
        fact_key=str(meta.get("fact_key") or ""),
        page_or_section=str(meta.get("page_or_section") or ""),
        document_date=doc_date,
        ingested_at=str(meta.get("ingested_at") or "") or None,
        content_hash=str(meta.get("content_hash") or "") or None,
        metadata=meta,
    )


def _rank_candidates(
    hits: list[RetrievedChunk],
    *,
    preferred_fact_key: str | None,
) -> list[RetrievedChunk]:
    """
    Soft-prefer detected fact_key, then higher similarity.

    Fixes short queries like \"expense ratio Mid Cap\" where exit_load
    can outrank expense_ratio under pure dense search.
    """

    def sort_key(h: RetrievedChunk) -> tuple[int, float]:
        match = (
            _FACT_MATCH_SORT_KEY
            if preferred_fact_key and h.fact_key == preferred_fact_key
            else 0
        )
        return (match, h.similarity)

    return sorted(hits, key=sort_key, reverse=True)


def _select_winner(
    ranked: list[RetrievedChunk],
    *,
    min_similarity: float,
) -> RetrievedChunk | None:
    if not ranked:
        return None
    top = ranked[0]
    if top.similarity < min_similarity:
        return None
    if not top.source_url.startswith("https://groww.in"):
        logger.warning("Dropping hit with non-Groww citation: %s", top.chunk_id)
        return None
    return top


class Retriever:
    """Online Retriever over the local Chroma Vector Store."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
        index_dir: Path | None = None,
        collection_name: str | None = None,
        schemes: list[dict[str, Any]] | None = None,
        collection: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder or get_embedding_service()
        self.index_dir = (
            Path(index_dir)
            if index_dir is not None
            else Path(self.settings.data_index_dir)
        )
        self.collection_name = collection_name or self.settings.chroma_collection_name
        registry = load_schemes(self.settings.schemes_path)
        self.schemes = list(schemes) if schemes is not None else list(registry["schemes"])
        self._scheme_urls = _scheme_url_map(self.schemes)
        self._refusal_url = _refusal_url(registry)
        self._collection = collection

    def _get_collection(self) -> Any:
        if self._collection is None:
            from src.ingestion.indexer import open_collection

            self._collection = open_collection(
                settings=self.settings,
                index_dir=self.index_dir,
                collection_name=self.collection_name,
            )
        return self._collection

    def vector_count(self) -> int:
        """Number of indexed chunks — used by the API health check."""
        return int(self._get_collection().count())

    def _query_chroma(
        self,
        query_embedding: list[float],
        *,
        n_results: int,
        where: dict[str, Any] | None,
    ) -> list[RetrievedChunk]:
        collection = self._get_collection()
        count = collection.count()
        if count == 0:
            return []
        n = max(1, min(n_results, count))
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": n,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        raw = collection.query(**kwargs)
        ids = (raw.get("ids") or [[]])[0]
        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        dists = (raw.get("distances") or [[]])[0]
        hits: list[RetrievedChunk] = []
        for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists):
            if not chunk_id:
                continue
            hits.append(
                _hit_from_chroma(
                    str(chunk_id),
                    str(doc or ""),
                    dict(meta or {}),
                    float(dist),
                )
            )
        return hits

    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
    ) -> RetrievalResult:
        """
        Find the best Groww snippet for a factual question.

        Returns status + optional winner (citation always from metadata).
        """
        q = (query or "").strip()
        hints = parse_query(q, schemes=self.schemes)
        min_sim = float(self.settings.retrieval_min_similarity)

        if not q:
            return RetrievalResult(
                status="empty",
                query=q,
                hints=hints,
                message="Empty question.",
            )

        # Ambiguous: two+ funds mentioned — never pick one silently
        if hints.ambiguous_scheme:
            return RetrievalResult(
                status="ambiguous_scheme",
                query=q,
                hints=hints,
                fallback_url=self._refusal_url,
                message=(
                    "I couldn't tell which fund you mean. "
                    "Please name one of the HDFC schemes we cover."
                ),
            )

        # Fact known but no fund — do not return another scheme's number
        if hints.fact_key and not hints.has_scheme:
            return RetrievalResult(
                status="no_scheme",
                query=q,
                hints=hints,
                fallback_url=self._refusal_url,
                message=(
                    "I couldn't find verified information for that query "
                    "without knowing which fund you mean. "
                    "Please name the scheme (for example HDFC Large Cap)."
                ),
            )

        # No scheme and no fact — refuse to invent; don't cite a random fund
        if not hints.has_scheme and not hints.fact_key:
            return RetrievalResult(
                status="no_scheme",
                query=q,
                hints=hints,
                fallback_url=self._refusal_url,
                message=(
                    "I couldn't find verified information for that query "
                    "in our sources. Please ask a factual question about "
                    "one of the HDFC schemes we cover."
                ),
            )

        scheme_id = hints.scheme_id
        assert scheme_id is not None
        fallback = self._scheme_urls.get(scheme_id, self._refusal_url)
        k = top_k if top_k is not None else int(self.settings.retrieval_top_k)

        query_vec = self.embedder.embed_query(q)
        where: dict[str, Any] = {"scheme_id": scheme_id}
        hits = self._query_chroma(query_vec, n_results=k, where=where)
        ranked = _rank_candidates(hits, preferred_fact_key=hints.fact_key)
        winner = _select_winner(ranked, min_similarity=min_sim)

        if winner is None:
            return RetrievalResult(
                status="low_confidence",
                query=q,
                hints=hints,
                candidates=ranked,
                fallback_url=fallback,
                message=(
                    "I couldn't find verified information for that query "
                    "in our sources."
                ),
            )

        logger.info(
            "retrieve ok scheme=%s fact=%s chunk=%s sim=%.3f",
            winner.scheme_id,
            winner.fact_key,
            winner.chunk_id,
            winner.similarity,
        )
        return RetrievalResult(
            status="ok",
            query=q,
            hints=hints,
            winner=winner,
            candidates=ranked,
            fallback_url=fallback,
            message=None,
        )


def retrieve(query: str, top_k: int | None = None) -> list[dict]:
    """
    Module-level helper: return ranked candidate dicts (winner first if ok).

    Prefer Retriever.retrieve() for full status / citation handling.
    """
    result = Retriever().retrieve(query, top_k=top_k)
    if result.winner:
        return [result.winner.to_dict()] + [
            c.to_dict() for c in result.candidates if c.chunk_id != result.winner.chunk_id
        ]
    return [c.to_dict() for c in result.candidates]

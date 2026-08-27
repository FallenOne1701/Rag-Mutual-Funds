"""
Indexer — upsert fact-atomic chunks into the Vector Store (Architecture §4.2).

Offline path: load `data/processed/all_chunks.json` → Embedding Service →
Chroma persistent collection under `data/index/`. Deduplicate on re-ingest by
`chunk_id` (scheme_id + fact_key[+part]) via upsert.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.config.settings import Settings, get_settings, load_schemes
from src.retrieval.embedder import Embedder, EmbeddingService, get_embedding_service

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION_NAME = "mf_faq_chunks"

# Chroma metadata values must be str | int | float | bool (no None).
_META_KEYS = (
    "scheme_id",
    "scheme_name",
    "category",
    "amc",
    "document_type",
    "source_url",
    "source_domain",
    "page_or_section",
    "fact_key",
    "content_hash",
    "document_date",
    "ingested_at",
    "part_index",
    "part_count",
)


@dataclass
class SchemeIndexResult:
    scheme_id: str
    scheme_name: str
    status: str  # ok | error
    chunk_count: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class IndexReport:
    indexed_at: str
    index_dir: str
    collection_name: str
    embedding_model: str
    expected_scheme_count: int
    total_chunks: int = 0
    upserted: int = 0
    results: list[SchemeIndexResult] = field(default_factory=list)
    error: str | None = None

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def all_ok(self) -> bool:
        return (
            self.error is None
            and self.expected_scheme_count > 0
            and self.ok_count == self.expected_scheme_count
            and self.error_count == 0
            and self.total_chunks > 0
        )

    def summary(self) -> str:
        lines = [
            "Vector Store / Indexer report",
            f"  indexed_at: {self.indexed_at}",
            f"  index_dir: {self.index_dir}",
            f"  collection: {self.collection_name}",
            f"  embedding_model: {self.embedding_model}",
            f"  schemes ok: {self.ok_count}/{self.expected_scheme_count}",
            f"  total_chunks: {self.total_chunks}",
            f"  upserted: {self.upserted}",
            f"  errors: {self.error_count}",
        ]
        if self.error:
            lines.append(f"  FATAL: {self.error}")
        for r in self.results:
            if r.ok:
                lines.append(f"  [ok] {r.scheme_id}  chunks={r.chunk_count}")
            else:
                lines.append(f"  [ERROR] {r.scheme_id}: {r.error}")
        if not self.all_ok:
            lines.append(
                "  NOTE: Index incomplete — do not treat the corpus as fully loaded."
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "indexed_at": self.indexed_at,
            "index_dir": self.index_dir,
            "collection_name": self.collection_name,
            "embedding_model": self.embedding_model,
            "expected_scheme_count": self.expected_scheme_count,
            "ok_count": self.ok_count,
            "error_count": self.error_count,
            "total_chunks": self.total_chunks,
            "upserted": self.upserted,
            "all_ok": self.all_ok,
            "error": self.error,
            "results": [asdict(r) for r in self.results],
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _chunk_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    """Flatten chunk fields into Chroma-safe metadata (no None)."""
    meta: dict[str, Any] = {}
    for key in _META_KEYS:
        val = chunk.get(key)
        if val is None:
            meta[key] = ""
        elif isinstance(val, (str, int, float, bool)):
            meta[key] = val
        else:
            meta[key] = str(val)
    return meta


def open_collection(
    *,
    settings: Settings | None = None,
    index_dir: Path | None = None,
    collection_name: str | None = None,
):
    """Open (or create) the persistent Chroma collection for this corpus."""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    cfg = settings or get_settings()
    path = Path(index_dir) if index_dir is not None else Path(cfg.data_index_dir)
    path.mkdir(parents=True, exist_ok=True)
    name = collection_name or getattr(
        cfg, "chroma_collection_name", DEFAULT_COLLECTION_NAME
    )

    client = chromadb.PersistentClient(
        path=str(path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def load_chunks_from_processed(
    processed_dir: Path,
) -> list[dict[str, Any]]:
    """Load flat chunk list written by the Chunker (`all_chunks.json`)."""
    path = processed_dir / "all_chunks.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path} — run Chunker first (`python scripts/ingest.py --chunk-only`)"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Invalid all_chunks.json (expected list): {path}")
    return data


def _group_by_scheme(
    chunks: Sequence[dict[str, Any]],
    schemes: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = {s["scheme_id"]: [] for s in schemes}
    for chunk in chunks:
        sid = str(chunk.get("scheme_id") or "")
        if sid in by_id:
            by_id[sid].append(chunk)
    return by_id


def index_chunks(
    chunks: Sequence[dict[str, Any]],
    *,
    embedder: Embedder | None = None,
    settings: Settings | None = None,
    index_dir: Path | None = None,
    collection_name: str | None = None,
    batch_size: int = 32,
) -> int:
    """
    Upsert chunks into Chroma. Returns number of vectors written.

    Dedup: same `chunk_id` overwrites previous embedding + metadata.
    """
    if not chunks:
        return 0

    cfg = settings or get_settings()
    service: Embedder = embedder or get_embedding_service()
    collection = open_collection(
        settings=cfg,
        index_dir=index_dir,
        collection_name=collection_name,
    )

    upserted = 0
    for start in range(0, len(chunks), batch_size):
        batch = list(chunks[start : start + batch_size])
        ids = [str(c["chunk_id"]) for c in batch]
        documents = [str(c["text"]) for c in batch]
        metadatas = [_chunk_metadata(c) for c in batch]
        embeddings = service.embed_documents(documents)
        if len(embeddings) != len(batch):
            raise RuntimeError(
                f"Embedding count mismatch: got {len(embeddings)} for {len(batch)} chunks"
            )
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        upserted += len(batch)
        logger.info(
            "Upserted batch %s-%s (%s vectors)",
            start + 1,
            start + len(batch),
            len(batch),
        )
    return upserted


def build_index(
    *,
    schemes: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
    processed_dir: Path | None = None,
    index_dir: Path | None = None,
    collection_name: str | None = None,
    embedder: Embedder | None = None,
    write_report: bool = True,
) -> IndexReport:
    """
    Build / refresh the Vector Store from Chunker output.

    Reads `data/processed/all_chunks.json`, embeds with the Embedding Service,
    upserts into Chroma under `data/index/`. Re-runs replace by `chunk_id`.
    """
    cfg = settings or get_settings()
    in_dir = (
        Path(processed_dir)
        if processed_dir is not None
        else Path(cfg.data_processed_dir)
    )
    out_dir = (
        Path(index_dir) if index_dir is not None else Path(cfg.data_index_dir)
    )
    name = collection_name or getattr(
        cfg, "chroma_collection_name", DEFAULT_COLLECTION_NAME
    )

    if schemes is None:
        registry = load_schemes(cfg.schemes_path)
        schemes = list(registry["schemes"])

    service: Embedder = embedder or get_embedding_service()
    report = IndexReport(
        indexed_at=_utc_now_iso(),
        index_dir=str(out_dir),
        collection_name=name,
        embedding_model=getattr(service, "model_name", cfg.embedding_model_name),
        expected_scheme_count=len(schemes),
    )

    if not schemes:
        report.error = "No schemes to index — schemes registry is empty"
        return report

    try:
        chunks = load_chunks_from_processed(in_dir)
    except (FileNotFoundError, ValueError) as exc:
        report.error = str(exc)
        for scheme in schemes:
            report.results.append(
                SchemeIndexResult(
                    scheme_id=scheme["scheme_id"],
                    scheme_name=scheme["scheme_name"],
                    status="error",
                    error=str(exc),
                )
            )
        if write_report:
            _write_index_report(out_dir, report)
        return report

    by_scheme = _group_by_scheme(chunks, schemes)
    # Deduplicate globally by chunk_id (last wins) before upsert
    unique: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        cid = str(chunk.get("chunk_id") or "").strip()
        if not cid or not str(chunk.get("text") or "").strip():
            continue
        if not str(chunk.get("source_url") or "").startswith("https://groww.in"):
            logger.warning("Skipping chunk with non-Groww URL: %s", cid)
            continue
        unique[cid] = chunk
    to_upsert = list(unique.values())

    for scheme in schemes:
        sid = scheme["scheme_id"]
        scheme_chunks = by_scheme.get(sid) or []
        if not scheme_chunks:
            report.results.append(
                SchemeIndexResult(
                    scheme_id=sid,
                    scheme_name=scheme["scheme_name"],
                    status="error",
                    error="No chunks found for scheme in all_chunks.json",
                )
            )
        else:
            report.results.append(
                SchemeIndexResult(
                    scheme_id=sid,
                    scheme_name=scheme["scheme_name"],
                    status="ok",
                    chunk_count=len(scheme_chunks),
                )
            )

    report.total_chunks = len(to_upsert)

    if report.error_count:
        # Still index whatever we have, but mark incomplete
        logger.warning(
            "Indexing with missing schemes (%s errors)",
            report.error_count,
        )

    if not to_upsert:
        report.error = report.error or "No chunks to upsert"
        if write_report:
            _write_index_report(out_dir, report)
        return report

    try:
        batch = getattr(cfg, "embedding_batch_size", 32)
        report.upserted = index_chunks(
            to_upsert,
            embedder=service,
            settings=cfg,
            index_dir=out_dir,
            collection_name=name,
            batch_size=batch,
        )
        # Verify collection count
        collection = open_collection(
            settings=cfg,
            index_dir=out_dir,
            collection_name=name,
        )
        stored = collection.count()
        logger.info(
            "Vector Store ready: %s vectors in collection '%s' (upserted %s)",
            stored,
            name,
            report.upserted,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Index build failed: %s", exc)
        report.error = str(exc)
        for r in report.results:
            if r.ok:
                r.status = "error"
                r.error = str(exc)

    if write_report:
        _write_index_report(out_dir, report)

    return report


def _write_index_report(index_dir: Path, report: IndexReport) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    path = index_dir / "index_report.json"
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Wrote index report -> %s", path)


def collection_count(
    *,
    settings: Settings | None = None,
    index_dir: Path | None = None,
    collection_name: str | None = None,
) -> int:
    """Return how many vectors are currently stored (for health / demos)."""
    return open_collection(
        settings=settings,
        index_dir=index_dir,
        collection_name=collection_name,
    ).count()

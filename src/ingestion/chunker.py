"""
Chunker — offline ingestion path (Architecture §4.4 + implementation-plan §1.3).

Fact-atomic: one retrieval chunk per `sections[]` row in
`data/processed/{scheme_id}.json`. Does not index `normalized_text` as a
mega-chunk. Optional split only if a single section exceeds ~400 tokens.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from src.config.settings import Settings, get_settings, load_schemes

logger = logging.getLogger(__name__)

ChunkStatus = Literal["ok", "error"]

# Approximate tokens ≈ whitespace-separated words (good enough for split guard)
_WORD_RE = re.compile(r"\S+")


@dataclass
class Chunk:
    """One retrieval unit with Architecture-required metadata."""

    chunk_id: str
    text: str
    scheme_id: str
    scheme_name: str
    category: str
    amc: str
    document_type: str
    source_url: str
    source_domain: str
    page_or_section: str
    fact_key: str
    content_hash: str
    document_date: str | None
    ingested_at: str
    part_index: int = 0
    part_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def metadata(self) -> dict[str, Any]:
        """Metadata only (for vector stores that store text separately)."""
        d = self.to_dict()
        d.pop("text", None)
        return d


@dataclass
class ChunkResult:
    scheme_id: str
    scheme_name: str
    status: ChunkStatus
    chunk_count: int = 0
    output_path: str | None = None
    skipped_missing: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class ChunkReport:
    chunked_at: str
    processed_dir: str
    chunks_dir: str
    expected_scheme_count: int
    total_chunks: int = 0
    results: list[ChunkResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def all_ok(self) -> bool:
        return (
            self.expected_scheme_count > 0
            and self.ok_count == self.expected_scheme_count
            and self.error_count == 0
        )

    def summary(self) -> str:
        lines = [
            "Chunker report",
            f"  chunked_at: {self.chunked_at}",
            f"  processed_dir: {self.processed_dir}",
            f"  chunks_dir: {self.chunks_dir}",
            f"  schemes ok: {self.ok_count}/{self.expected_scheme_count}",
            f"  total_chunks: {self.total_chunks}",
            f"  errors: {self.error_count}",
        ]
        for r in self.results:
            if r.ok:
                skip = (
                    f"  skipped_missing={','.join(r.skipped_missing)}"
                    if r.skipped_missing
                    else ""
                )
                lines.append(f"  [ok] {r.scheme_id}  chunks={r.chunk_count}{skip}")
            else:
                lines.append(f"  [ERROR] {r.scheme_id}: {r.error}")
        if not self.all_ok:
            lines.append(
                "  NOTE: Partial or failed chunk — do not treat missing "
                "schemes as covered in the corpus."
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunked_at": self.chunked_at,
            "processed_dir": self.processed_dir,
            "chunks_dir": self.chunks_dir,
            "expected_scheme_count": self.expected_scheme_count,
            "ok_count": self.ok_count,
            "error_count": self.error_count,
            "total_chunks": self.total_chunks,
            "all_ok": self.all_ok,
            "results": [asdict(r) for r in self.results],
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def estimate_tokens(text: str) -> int:
    """Rough token count for the rare large-section split guard."""
    return len(_WORD_RE.findall(text or ""))


def _hash_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _split_long_section(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """
    Split an oversized section by words with overlap.
    Unused for current Groww fact sections (~12–31 words).
    """
    words = _WORD_RE.findall(text)
    if len(words) <= max_tokens:
        return [text.strip()] if text.strip() else []

    overlap = max(0, min(overlap_tokens, max_tokens // 2))
    step = max(1, max_tokens - overlap)
    parts: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_tokens)
        parts.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += step
    return parts


def chunk_processed_document(
    doc: dict[str, Any],
    *,
    max_section_tokens: int = 400,
    overlap_tokens: int = 0,
) -> list[Chunk]:
    """
    Build fact-atomic chunks from one processed scheme JSON.

    Rules (implementation-plan §1.3):
    - One chunk per `sections[]` entry (body = section.text)
    - Skip missing / empty facts — never invent lock_in
    - Do not emit a chunk for full `normalized_text`
    - Split a section only if it exceeds max_section_tokens
    """
    scheme_id = str(doc["scheme_id"])
    scheme_name = str(doc["scheme_name"])
    category = str(doc.get("category") or "")
    amc = str(doc.get("amc") or "HDFC Mutual Fund")
    source_url = str(doc["source_url"])
    source_domain = str(doc.get("source_domain") or "groww.in")
    document_type = str(doc.get("document_type") or "groww_scheme_page")
    document_date = doc.get("document_date")
    ingested_at = str(doc.get("ingested_at") or _utc_now_iso())
    missing = set(doc.get("missing_facts") or [])
    facts = doc.get("facts") or {}

    sections = doc.get("sections") or []
    if not isinstance(sections, list) or not sections:
        raise ValueError(f"No sections to chunk for scheme '{scheme_id}'")

    # Deduplicate by fact_key (last wins) — stable re-runs
    by_key: dict[str, dict[str, Any]] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        fact_key = str(section.get("fact_key") or "").strip()
        text = str(section.get("text") or "").strip()
        if not fact_key or not text:
            continue
        if fact_key in missing:
            continue
        # Core facts that are null in facts dict — skip even if a section sneaks in
        if fact_key in facts and facts.get(fact_key) in (None, ""):
            continue
        by_key[fact_key] = section

    chunks: list[Chunk] = []
    for fact_key, section in by_key.items():
        text = str(section["text"]).strip()
        page_or_section = str(section.get("page_or_section") or fact_key)
        parts = _split_long_section(
            text,
            max_tokens=max_section_tokens,
            overlap_tokens=overlap_tokens,
        )
        if not parts:
            continue
        part_count = len(parts)
        for part_index, part_text in enumerate(parts):
            suffix = f"__p{part_index}" if part_count > 1 else ""
            chunk_id = f"{scheme_id}::{fact_key}{suffix}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    text=part_text,
                    scheme_id=scheme_id,
                    scheme_name=scheme_name,
                    category=category,
                    amc=amc,
                    document_type=document_type,
                    source_url=source_url,
                    source_domain=source_domain,
                    page_or_section=page_or_section,
                    fact_key=fact_key,
                    content_hash=_hash_text(part_text),
                    document_date=document_date,
                    ingested_at=ingested_at,
                    part_index=part_index,
                    part_count=part_count,
                )
            )

    if not chunks:
        raise ValueError(
            f"No chunks produced for scheme '{scheme_id}' "
            "(all sections empty or missing)."
        )
    return chunks


def chunk_document(
    text: str,
    metadata: dict[str, Any],
    *,
    max_section_tokens: int = 400,
    overlap_tokens: int = 0,
) -> list[dict[str, Any]]:
    """
    Compatibility helper: wrap a single text blob as one section.

    Prefer `chunk_processed_document` for the offline path.
    """
    doc = {
        "scheme_id": metadata.get("scheme_id", "unknown"),
        "scheme_name": metadata.get("scheme_name", "Unknown"),
        "category": metadata.get("category", ""),
        "amc": metadata.get("amc", "HDFC Mutual Fund"),
        "source_url": metadata.get("source_url", ""),
        "source_domain": metadata.get("source_domain", "groww.in"),
        "document_type": metadata.get("document_type", "groww_scheme_page"),
        "document_date": metadata.get("document_date"),
        "ingested_at": metadata.get("ingested_at") or _utc_now_iso(),
        "missing_facts": metadata.get("missing_facts") or [],
        "facts": metadata.get("facts") or {},
        "sections": [
            {
                "page_or_section": metadata.get("page_or_section", "Scheme Information"),
                "fact_key": metadata.get("fact_key", "general"),
                "text": text,
            }
        ],
    }
    return [
        c.to_dict()
        for c in chunk_processed_document(
            doc,
            max_section_tokens=max_section_tokens,
            overlap_tokens=overlap_tokens,
        )
    ]


def _load_processed_doc(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "scheme_id" not in data:
        raise ValueError(f"Invalid processed document: {path}")
    return data


def chunk_scheme_pages(
    *,
    schemes: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
    processed_dir: Path | None = None,
    chunks_dir: Path | None = None,
    write_report: bool = True,
) -> ChunkReport:
    """
    Chunk all configured schemes from `data/processed/*.json`.

    Writes:
    - `{chunks_dir}/{scheme_id}.json` — chunks for one scheme
    - `{processed_dir}/all_chunks.json` — flat list for Embedding Service
    - `{processed_dir}/chunk_report.json` — human-readable summary
    """
    cfg = settings or get_settings()
    in_dir = (
        Path(processed_dir)
        if processed_dir is not None
        else Path(cfg.data_processed_dir)
    )
    out_dir = (
        Path(chunks_dir)
        if chunks_dir is not None
        else in_dir / "chunks"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if schemes is None:
        registry = load_schemes(cfg.schemes_path)
        schemes = list(registry["schemes"])

    if not schemes:
        raise ValueError("No schemes to chunk — schemes registry is empty")

    chunked_at = _utc_now_iso()
    report = ChunkReport(
        chunked_at=chunked_at,
        processed_dir=str(in_dir),
        chunks_dir=str(out_dir),
        expected_scheme_count=len(schemes),
    )

    all_chunks: list[dict[str, Any]] = []
    # Global dedupe key → chunk dict (stable re-run)
    seen: dict[str, dict[str, Any]] = {}

    max_tokens = cfg.chunk_max_section_tokens
    overlap = cfg.chunk_overlap_tokens if max_tokens else 0

    for scheme in schemes:
        scheme_id = scheme["scheme_id"]
        scheme_name = scheme["scheme_name"]
        doc_path = in_dir / f"{scheme_id}.json"
        if not doc_path.is_file():
            report.results.append(
                ChunkResult(
                    scheme_id=scheme_id,
                    scheme_name=scheme_name,
                    status="error",
                    error=f"Processed JSON missing: {doc_path}",
                )
            )
            continue
        try:
            doc = _load_processed_doc(doc_path)
            skipped = list(doc.get("missing_facts") or [])
            chunks = chunk_processed_document(
                doc,
                max_section_tokens=max_tokens,
                overlap_tokens=overlap,
            )
            # Per-scheme dedupe by chunk_id
            unique: dict[str, Chunk] = {c.chunk_id: c for c in chunks}
            chunk_list = list(unique.values())
            payload = [c.to_dict() for c in chunk_list]
            out_path = out_dir / f"{scheme_id}.json"
            out_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            for c in chunk_list:
                seen[c.chunk_id] = c.to_dict()
            report.results.append(
                ChunkResult(
                    scheme_id=scheme_id,
                    scheme_name=scheme_name,
                    status="ok",
                    chunk_count=len(chunk_list),
                    output_path=str(out_path),
                    skipped_missing=skipped,
                )
            )
            logger.info(
                "Chunked %s → %s chunks (%s)",
                scheme_id,
                len(chunk_list),
                out_path.name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Chunk failed for %s: %s", scheme_id, exc)
            report.results.append(
                ChunkResult(
                    scheme_id=scheme_id,
                    scheme_name=scheme_name,
                    status="error",
                    error=str(exc),
                )
            )

    all_chunks = list(seen.values())
    report.total_chunks = len(all_chunks)

    all_path = in_dir / "all_chunks.json"
    all_path.write_text(
        json.dumps(all_chunks, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Wrote %s chunks → %s", len(all_chunks), all_path)

    if write_report:
        report_path = in_dir / "chunk_report.json"
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote chunk report → %s", report_path)

    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = chunk_scheme_pages()
    print(report.summary())
    return 0 if report.all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

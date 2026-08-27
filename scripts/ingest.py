#!/usr/bin/env python3
"""
CLI for the offline ingestion path.

Phases 1.1–1.5: Document Fetcher → Parser & Normalizer → Chunker →
Embedding Service → Vector Store (Chroma under data/index/).

Default: full corpus rebuild. Stage flags for partial runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow `python scripts/ingest.py` from project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings  # noqa: E402
from src.ingestion.chunker import chunk_scheme_pages  # noqa: E402
from src.ingestion.fetcher import fetch_scheme_pages  # noqa: E402
from src.ingestion.indexer import build_index  # noqa: E402
from src.ingestion.parser import parse_scheme_pages  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mutual Fund FAQ Assistant — offline corpus ingest",
    )
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument(
        "--fetch-only",
        action="store_true",
        help="Run Document Fetcher only (download Groww HTML to data/raw/)",
    )
    stage.add_argument(
        "--parse-only",
        action="store_true",
        help="Run Parser & Normalizer only (raw HTML → data/processed/)",
    )
    stage.add_argument(
        "--chunk-only",
        action="store_true",
        help="Run Chunker only (processed JSON → fact-atomic chunks)",
    )
    stage.add_argument(
        "--index-only",
        action="store_true",
        help="Run Embedding Service + Vector Store only (chunks → data/index/)",
    )
    stage.add_argument(
        "--fetch-and-parse",
        action="store_true",
        help="Fetch then parse (Phases 1.1 + 1.2)",
    )
    stage.add_argument(
        "--through-chunk",
        action="store_true",
        help="Fetch → parse → chunk (Phases 1.1–1.3)",
    )
    stage.add_argument(
        "--full",
        action="store_true",
        help="Full corpus rebuild: fetch → parse → chunk → index (default)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    return parser


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_ingest_report(
    *,
    stages: tuple[str, ...],
    stage_payloads: dict[str, Any],
    all_ok: bool,
    exit_code: int,
) -> Path:
    """Human-readable summary across the stages that ran."""
    cfg = get_settings()
    report: dict[str, Any] = {
        "ingested_at": _utc_now_iso(),
        "stages": list(stages),
        "all_ok": all_ok,
        "exit_code": exit_code,
        "disclaimer": cfg.disclaimer,
        "reports": stage_payloads,
    }
    # Compact headline for demos
    headline: dict[str, Any] = {}
    if "fetch" in stage_payloads:
        fr = stage_payloads["fetch"]
        headline["schemes_fetched"] = f"{fr.get('ok_count', 0)}/{fr.get('expected_scheme_count', 0)}"
    if "parse" in stage_payloads:
        pr = stage_payloads["parse"]
        headline["schemes_parsed"] = f"{pr.get('ok_count', 0)}/{pr.get('expected_scheme_count', 0)}"
    if "chunk" in stage_payloads:
        cr = stage_payloads["chunk"]
        headline["schemes_chunked"] = f"{cr.get('ok_count', 0)}/{cr.get('expected_scheme_count', 0)}"
        headline["total_chunks"] = cr.get("total_chunks")
    if "index" in stage_payloads:
        ir = stage_payloads["index"]
        headline["schemes_indexed"] = f"{ir.get('ok_count', 0)}/{ir.get('expected_scheme_count', 0)}"
        headline["vectors_upserted"] = ir.get("upserted")
        headline["embedding_model"] = ir.get("embedding_model")
        headline["collection"] = ir.get("collection_name")
    report["headline"] = headline

    out_path = PROJECT_ROOT / "data" / "ingest_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.fetch_only:
        stages: tuple[str, ...] = ("fetch",)
    elif args.parse_only:
        stages = ("parse",)
    elif args.chunk_only:
        stages = ("chunk",)
    elif args.index_only:
        stages = ("index",)
    elif args.fetch_and_parse:
        stages = ("fetch", "parse")
    elif args.through_chunk:
        stages = ("fetch", "parse", "chunk")
    else:
        # Default / --full: complete Phase 1 corpus rebuild
        stages = ("fetch", "parse", "chunk", "index")

    exit_code = 0
    stage_payloads: dict[str, Any] = {}

    if "fetch" in stages:
        fetch_report = fetch_scheme_pages()
        print(fetch_report.summary())
        stage_payloads["fetch"] = fetch_report.to_dict()
        if not fetch_report.all_ok:
            exit_code = 1
            if "parse" in stages:
                print(
                    "Continuing to parse schemes that have raw HTML "
                    "(partial fetch)."
                )

    if "parse" in stages:
        parse_report = parse_scheme_pages()
        print(parse_report.summary())
        stage_payloads["parse"] = parse_report.to_dict()
        if not parse_report.all_ok:
            exit_code = 1
            if "chunk" in stages:
                print(
                    "Continuing to chunk schemes that have processed JSON "
                    "(partial parse)."
                )

    if "chunk" in stages:
        chunk_report = chunk_scheme_pages()
        print(chunk_report.summary())
        stage_payloads["chunk"] = chunk_report.to_dict()
        if not chunk_report.all_ok:
            exit_code = 1
            if "index" in stages:
                print(
                    "Continuing to index chunks that were produced "
                    "(partial chunk)."
                )

    if "index" in stages:
        index_report = build_index()
        print(index_report.summary())
        stage_payloads["index"] = index_report.to_dict()
        if not index_report.all_ok:
            exit_code = 1

    all_ok = exit_code == 0
    report_path = write_ingest_report(
        stages=stages,
        stage_payloads=stage_payloads,
        all_ok=all_ok,
        exit_code=exit_code,
    )
    print(f"\nIngest report -> {report_path}")
    if all_ok and "index" in stages:
        ir = stage_payloads["index"]
        print(
            f"Corpus loaded: {ir.get('ok_count')}/{ir.get('expected_scheme_count')} "
            f"schemes, {ir.get('upserted')} vectors "
            f"({ir.get('embedding_model')})."
        )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

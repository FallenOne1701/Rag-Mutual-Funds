#!/usr/bin/env python3
"""
Gate the refreshed corpus before it is published (Phase 7 scheduler).

`scripts/ingest.py` already fails when a stage errors. This adds the checks
that catch a *silently wrong* run — Groww serving a block page, the parser
losing a fact, Chroma ending up out of step with the chunks — so the nightly
job never replaces a verified corpus with a hollow one.

Also prints a Markdown summary (per-scheme facts + freshness) for the workflow
job summary and the pull request body.

Exit codes: 0 verified, 1 verification failed, 2 nothing to verify.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings, is_allowed_source_url, load_schemes  # noqa: E402

# Facts every scheme page must still yield; lock_in is ELSS-only by design.
CORE_FACT_KEYS = ("expense_ratio", "exit_load", "min_sip", "riskometer", "benchmark")


class Failures(list):
    """Collected problems; empty means the corpus is publishable."""

    def check(self, condition: bool, message: str) -> bool:
        if not condition:
            self.append(message)
        return condition


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _age_days(document_date: str | None) -> int | None:
    if not document_date:
        return None
    try:
        return (date.today() - date.fromisoformat(document_date[:10])).days
    except ValueError:
        return None


def verify(
    *,
    min_sections_per_scheme: int,
    max_document_age_days: int,
) -> tuple[Failures, list[str], dict[str, Any]]:
    cfg = get_settings()
    registry = load_schemes()
    schemes = registry["schemes"]
    failures = Failures()
    warnings: list[str] = []

    report = _load_json(PROJECT_ROOT / "data" / "ingest_report.json")
    if report is None:
        failures.append("data/ingest_report.json is missing — did the ingest run?")
        return failures, warnings, {}

    failures.check(
        bool(report.get("all_ok")),
        f"Ingest reported failures (exit_code={report.get('exit_code')}).",
    )
    for stage in ("fetch", "parse", "chunk", "index"):
        failures.check(stage in report.get("stages", []), f"Stage '{stage}' did not run.")

    rows: list[dict[str, Any]] = []
    total_sections = 0

    for entry in schemes:
        scheme_id = entry["scheme_id"]
        doc = _load_json(cfg.data_processed_dir / f"{scheme_id}.json")
        if doc is None:
            failures.append(f"{scheme_id}: no processed document — the scheme dropped out.")
            continue

        sections = doc.get("sections") or []
        facts = doc.get("facts") or {}
        total_sections += len(sections)

        failures.check(
            len(sections) >= min_sections_per_scheme,
            f"{scheme_id}: only {len(sections)} sections (expected ≥ {min_sections_per_scheme}) "
            "— the page probably did not parse.",
        )
        failures.check(
            is_allowed_source_url(doc.get("source_url", "")),
            f"{scheme_id}: source_url is not on groww.in — corpus allowlist violated.",
        )

        for key in CORE_FACT_KEYS:
            failures.check(
                bool(facts.get(key)),
                f"{scheme_id}: core fact '{key}' is missing from this refresh.",
            )

        # Never invent freshness: an old document_date is a warning to look at,
        # not something to overwrite with today.
        age = _age_days(doc.get("document_date"))
        if age is None:
            warnings.append(f"{scheme_id}: no usable document_date; footer falls back to ingest date.")
        elif age > max_document_age_days:
            warnings.append(
                f"{scheme_id}: document_date is {age} days old — Groww may have stopped "
                "publishing a date on this page."
            )

        rows.append(
            {
                "scheme_id": scheme_id,
                "scheme_name": doc.get("scheme_name", scheme_id),
                "sections": len(sections),
                "document_date": doc.get("document_date") or "—",
                "facts": facts,
                "missing_facts": doc.get("missing_facts") or [],
            }
        )

    failures.check(
        len(rows) == len(schemes),
        f"Only {len(rows)}/{len(schemes)} schemes made it through the pipeline.",
    )

    # The Vector Store must agree with what the Chunker produced, or retrieval
    # is answering from a corpus nobody reviewed.
    vectors: int | None = None
    try:
        from src.ingestion.indexer import collection_count

        vectors = collection_count(settings=cfg)
        failures.check(
            vectors == total_sections,
            f"Chroma holds {vectors} vectors but the corpus has {total_sections} chunks "
            "— index and chunks are out of step.",
        )
    except Exception as exc:  # noqa: BLE001 — surface any store problem as a failure
        failures.append(f"Could not read the vector store: {exc}")

    summary = {
        "rows": rows,
        "total_sections": total_sections,
        "vectors": vectors,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "headline": report.get("headline", {}),
    }
    return failures, warnings, summary


def render_markdown(
    summary: dict[str, Any],
    failures: list[str],
    warnings: list[str],
) -> str:
    lines: list[str] = ["## Daily corpus refresh", ""]
    status = "verified" if not failures else "FAILED verification"
    lines.append(
        f"**{status}** — {len(summary.get('rows', []))} schemes, "
        f"{summary.get('total_sections')} chunks, {summary.get('vectors')} vectors "
        f"(checked {summary.get('checked_at')})."
    )
    lines.append("")

    if summary.get("rows"):
        lines += [
            "| Scheme | Source date | Chunks | Expense ratio | Exit load | Min SIP | Riskometer |",
            "| --- | --- | ---: | --- | --- | --- | --- |",
        ]
        for r in summary["rows"]:
            f = r["facts"]
            lines.append(
                f"| {r['scheme_name']} | {r['document_date']} | {r['sections']} | "
                f"{f.get('expense_ratio', '—')} | {f.get('exit_load', '—')} | "
                f"{f.get('min_sip', '—')} | {f.get('riskometer', '—')} |"
            )
        lines.append("")

    if warnings:
        lines.append("**Worth a look**")
        lines += [f"- {w}" for w in warnings]
        lines.append("")

    if failures:
        lines.append("**Blocking problems**")
        lines += [f"- {f}" for f in failures]
        lines.append("")

    lines.append("_Facts-only. No investment advice. Sources: groww.in scheme pages._")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a refreshed corpus before publishing")
    parser.add_argument(
        "--min-sections-per-scheme",
        type=int,
        default=5,
        help="Fewest chunks a healthy scheme page yields (default: 5)",
    )
    parser.add_argument(
        "--max-document-age-days",
        type=int,
        default=30,
        help="Warn when a scheme's document_date is older than this (default: 30)",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        help="Write the Markdown summary here (e.g. $GITHUB_STEP_SUMMARY)",
    )
    args = parser.parse_args(argv)

    failures, warnings, summary = verify(
        min_sections_per_scheme=args.min_sections_per_scheme,
        max_document_age_days=args.max_document_age_days,
    )
    if not summary:
        print("Nothing to verify — no ingest report found.", file=sys.stderr)
        return 2

    markdown = render_markdown(summary, failures, warnings)
    # Fact values contain ₹, which the default Windows console codepage cannot encode.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(markdown)
    if args.summary_file:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        with args.summary_file.open("a", encoding="utf-8") as fh:
            fh.write(markdown)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

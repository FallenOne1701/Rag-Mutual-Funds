"""
Document Fetcher — offline ingestion path (Architecture §4.1 / §4.2).

Downloads Groww scheme pages and saves raw HTML under `data/raw/`.
Corpus domain allowlist: groww.in only. Failures are reported loudly
(no empty silent success).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from src.config.settings import (
    Settings,
    get_settings,
    is_allowed_source_url,
    load_schemes,
)

logger = logging.getLogger(__name__)

def _accept_encoding() -> str:
    """Prefer gzip/deflate; include brotli only when the decoder is installed."""
    try:
        import brotli  # noqa: F401
    except ImportError:
        return "gzip, deflate"
    return "gzip, deflate, br"


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    # Avoid requesting `br` when brotli isn't installed — httpx then returns
    # undecoded garbage that fails the HTML usability check.
    "Accept-Encoding": _accept_encoding(),
    "Connection": "keep-alive",
    "Referer": "https://groww.in/mutual-funds",
}

FetchStatus = Literal["ok", "error"]


@dataclass
class FetchResult:
    """Outcome of fetching one scheme page."""

    scheme_id: str
    scheme_name: str
    source_url: str
    status: FetchStatus
    html_path: str | None = None
    meta_path: str | None = None
    content_hash: str | None = None
    byte_length: int = 0
    http_status: int | None = None
    fetched_at: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class FetchReport:
    """Aggregate Document Fetcher report for an ingest run."""

    fetched_at: str
    raw_dir: str
    expected_scheme_count: int
    results: list[FetchResult] = field(default_factory=list)

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
            "Document Fetcher report",
            f"  fetched_at: {self.fetched_at}",
            f"  raw_dir: {self.raw_dir}",
            f"  ok: {self.ok_count}/{self.expected_scheme_count}",
            f"  errors: {self.error_count}",
        ]
        for r in self.results:
            if r.ok:
                lines.append(
                    f"  [ok] {r.scheme_id}  {r.byte_length} bytes  "
                    f"hash={r.content_hash[:12] if r.content_hash else '-'}…"
                )
            else:
                lines.append(f"  [ERROR] {r.scheme_id}: {r.error}")
        if not self.all_ok:
            lines.append(
                "  NOTE: Partial or failed fetch — do not treat missing "
                "schemes as covered in the corpus."
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "raw_dir": self.raw_dir,
            "expected_scheme_count": self.expected_scheme_count,
            "ok_count": self.ok_count,
            "error_count": self.error_count,
            "all_ok": self.all_ok,
            "results": [asdict(r) for r in self.results],
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _content_hash(html: str) -> str:
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _validate_scheme_url(url: str) -> None:
    """Raise ValueError if URL is not an allowlisted Groww corpus URL (KB-07)."""
    if not is_allowed_source_url(url):
        host = urlparse(url).hostname or "(missing host)"
        raise ValueError(
            f"Corpus URL host '{host}' is not allowlisted "
            f"(allowed: groww.in only): {url}"
        )


def _assert_html_usable(html: str, *, min_bytes: int, scheme_id: str) -> None:
    """
    Reject empty / shell HTML so we never index silent junk (KB-01, KB-02).

    Groww scheme pages are large; a tiny body usually means block page,
    soft 404, or JS shell without useful content.
    """
    raw_len = len(html.encode("utf-8"))
    if raw_len < min_bytes:
        raise ValueError(
            f"HTML too short for scheme '{scheme_id}' "
            f"({raw_len} < {min_bytes} bytes). "
            "Page may be blocked or JS-rendered; use Playwright snapshot "
            "or a manual HTML export before continuing."
        )
    stripped = html.strip().lower()
    if not stripped:
        raise ValueError(f"Empty HTML body for scheme '{scheme_id}'")
    # Soft signal that we got a real document, not a tiny interstitial
    markers = ("<!doctype html", "<html", "__next_data__", "mutual fund", "hdfc")
    if not any(m in stripped for m in markers):
        raise ValueError(
            f"HTML for scheme '{scheme_id}' lacks expected Groww/HTML markers; "
            "refusing to save as a corpus snapshot."
        )


def _write_snapshot(
    *,
    raw_dir: Path,
    scheme: dict[str, Any],
    html: str,
    http_status: int,
    fetched_at: str,
) -> tuple[Path, Path, str, int]:
    scheme_id = scheme["scheme_id"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    html_path = raw_dir / f"{scheme_id}.html"
    meta_path = raw_dir / f"{scheme_id}.meta.json"
    digest = _content_hash(html)
    byte_length = len(html.encode("utf-8"))

    html_path.write_text(html, encoding="utf-8")
    meta = {
        "scheme_id": scheme_id,
        "scheme_name": scheme["scheme_name"],
        "category": scheme.get("category"),
        "source_url": scheme["url"],
        "document_type": "groww_scheme_page",
        "fetched_at": fetched_at,
        "ingested_at": fetched_at,
        "http_status": http_status,
        "content_hash": digest,
        "byte_length": byte_length,
    }
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return html_path, meta_path, digest, byte_length


def fetch_one_scheme(
    scheme: dict[str, Any],
    *,
    raw_dir: Path,
    client: httpx.Client,
    min_html_bytes: int,
    timeout: float,
) -> FetchResult:
    """Download one Groww scheme page and persist raw HTML + sidecar metadata."""
    scheme_id = scheme["scheme_id"]
    scheme_name = scheme["scheme_name"]
    source_url = scheme["url"]
    fetched_at = _utc_now_iso()

    try:
        _validate_scheme_url(source_url)
    except ValueError as exc:
        logger.error("%s", exc)
        return FetchResult(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            source_url=source_url,
            status="error",
            fetched_at=fetched_at,
            error=str(exc),
        )

    try:
        response = client.get(source_url, timeout=timeout, follow_redirects=True)
        http_status = response.status_code
        if http_status >= 400:
            raise ValueError(
                f"HTTP {http_status} fetching {source_url} "
                f"(scheme '{scheme_id}')"
            )
        # Final URL after redirects must still be Groww
        final_url = str(response.url)
        _validate_scheme_url(final_url)

        html = response.text
        _assert_html_usable(html, min_bytes=min_html_bytes, scheme_id=scheme_id)
        html_path, meta_path, digest, byte_length = _write_snapshot(
            raw_dir=raw_dir,
            scheme=scheme,
            html=html,
            http_status=http_status,
            fetched_at=fetched_at,
        )
        logger.info(
            "Fetched %s (%s bytes) → %s",
            scheme_id,
            byte_length,
            html_path,
        )
        return FetchResult(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            source_url=source_url,
            status="ok",
            html_path=str(html_path),
            meta_path=str(meta_path),
            content_hash=digest,
            byte_length=byte_length,
            http_status=http_status,
            fetched_at=fetched_at,
        )
    except Exception as exc:  # noqa: BLE001 — surface every failure in report
        logger.error("Fetch failed for %s: %s", scheme_id, exc)
        return FetchResult(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            source_url=source_url,
            status="error",
            fetched_at=fetched_at,
            error=str(exc),
        )


def fetch_scheme_pages(
    *,
    schemes: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
    raw_dir: Path | None = None,
    client: httpx.Client | None = None,
    write_report: bool = True,
) -> FetchReport:
    """
    Download all configured Groww scheme pages into `data/raw/`.

    Returns a FetchReport. Does not raise on per-scheme HTTP failures —
    those appear as `status=error` entries. Raises only if the scheme
    registry itself is unusable (e.g. zero schemes).
    """
    cfg = settings or get_settings()
    out_dir = Path(raw_dir) if raw_dir is not None else Path(cfg.data_raw_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if schemes is None:
        registry = load_schemes(cfg.schemes_path)
        schemes = list(registry["schemes"])

    if not schemes:
        raise ValueError("No schemes to fetch — schemes registry is empty")

    fetched_at = _utc_now_iso()
    report = FetchReport(
        fetched_at=fetched_at,
        raw_dir=str(out_dir),
        expected_scheme_count=len(schemes),
    )

    owns_client = client is None
    http = client or httpx.Client(headers=DEFAULT_HEADERS, timeout=cfg.fetch_timeout_seconds)
    try:
        for i, scheme in enumerate(schemes):
            result = fetch_one_scheme(
                scheme,
                raw_dir=out_dir,
                client=http,
                min_html_bytes=cfg.fetch_min_html_bytes,
                timeout=cfg.fetch_timeout_seconds,
            )
            report.results.append(result)
            # Polite pause between live requests (skip after last)
            if owns_client and i < len(schemes) - 1 and cfg.fetch_delay_seconds > 0:
                time.sleep(cfg.fetch_delay_seconds)
    finally:
        if owns_client:
            http.close()

    if write_report:
        report_path = out_dir / "fetch_report.json"
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote fetch report → %s", report_path)

    return report


def main() -> int:
    """CLI entry: fetch all Groww scheme pages (Phase 1.1)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    report = fetch_scheme_pages()
    print(report.summary())
    return 0 if report.all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

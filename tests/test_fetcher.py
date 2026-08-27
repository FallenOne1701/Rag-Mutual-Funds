"""Phase 1.1 — Document Fetcher (allowlist, loud failures, raw HTML snapshots)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.config.settings import Settings
from src.ingestion.fetcher import (
    FetchReport,
    _assert_html_usable,
    _validate_scheme_url,
    fetch_one_scheme,
    fetch_scheme_pages,
)


SAMPLE_HTML = """<!DOCTYPE html>
<html><head><title>HDFC Large Cap Fund Direct Growth</title></head>
<body>
<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>
<h1>HDFC Large Cap Fund Direct Growth</h1>
<p>Mutual fund expense ratio and exit load details for HDFC investors.</p>
</body></html>
"""


def _pad_html(html: str, min_bytes: int = 2500) -> str:
    """Ensure sample HTML clears the min-size guard used in production."""
    pad = "<!-- " + ("x" * max(0, min_bytes - len(html.encode("utf-8")))) + " -->"
    return html + pad


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    d = tmp_path / "raw"
    d.mkdir()
    return d


@pytest.fixture
def scheme() -> dict:
    return {
        "scheme_id": "hdfc-large-cap-fund-direct-growth",
        "scheme_name": "HDFC Large Cap Fund Direct Growth",
        "category": "Large-cap",
        "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    }


def test_validate_rejects_non_groww_url():
    with pytest.raises(ValueError, match="not allowlisted"):
        _validate_scheme_url("https://www.amfiindia.com/investor-corner")


def test_validate_accepts_groww_url():
    _validate_scheme_url(
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
    )


def test_assert_html_rejects_empty():
    with pytest.raises(ValueError, match="too short|Empty"):
        _assert_html_usable("", min_bytes=100, scheme_id="x")


def test_assert_html_rejects_shell_without_markers():
    junk = "a" * 3000
    with pytest.raises(ValueError, match="lacks expected"):
        _assert_html_usable(junk, min_bytes=100, scheme_id="x")


def test_fetch_one_scheme_saves_html_and_meta(raw_dir: Path, scheme: dict):
    html = _pad_html(SAMPLE_HTML)
    response = MagicMock()
    response.status_code = 200
    response.text = html
    response.url = httpx.URL(scheme["url"])

    client = MagicMock()
    client.get.return_value = response

    result = fetch_one_scheme(
        scheme,
        raw_dir=raw_dir,
        client=client,
        min_html_bytes=2000,
        timeout=10.0,
    )

    assert result.ok
    assert result.http_status == 200
    assert result.content_hash and result.content_hash.startswith("sha256:")
    html_path = Path(result.html_path)  # type: ignore[arg-type]
    meta_path = Path(result.meta_path)  # type: ignore[arg-type]
    assert html_path.exists()
    assert meta_path.exists()
    assert "HDFC Large Cap" in html_path.read_text(encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["scheme_id"] == scheme["scheme_id"]
    assert meta["source_url"] == scheme["url"]
    assert meta["document_type"] == "groww_scheme_page"
    assert meta["content_hash"] == result.content_hash


def test_fetch_one_scheme_http_404_is_error(raw_dir: Path, scheme: dict):
    response = MagicMock()
    response.status_code = 404
    response.text = "Not Found"
    response.url = httpx.URL(scheme["url"])

    client = MagicMock()
    client.get.return_value = response

    result = fetch_one_scheme(
        scheme,
        raw_dir=raw_dir,
        client=client,
        min_html_bytes=2000,
        timeout=10.0,
    )
    assert not result.ok
    assert "404" in (result.error or "")
    assert not list(raw_dir.glob("*.html"))


def test_fetch_one_scheme_rejects_non_allowlisted(raw_dir: Path):
    bad = {
        "scheme_id": "evil",
        "scheme_name": "Evil Fund",
        "category": "x",
        "url": "https://evil.example/fund",
    }
    client = MagicMock()
    result = fetch_one_scheme(
        bad,
        raw_dir=raw_dir,
        client=client,
        min_html_bytes=2000,
        timeout=10.0,
    )
    assert not result.ok
    assert "allowlisted" in (result.error or "").lower()
    client.get.assert_not_called()


def test_fetch_scheme_pages_partial_success(raw_dir: Path, scheme: dict):
    ok_html = _pad_html(SAMPLE_HTML)
    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.text = ok_html
    ok_response.url = httpx.URL(scheme["url"])

    fail_scheme = {
        "scheme_id": "hdfc-mid-cap-fund-direct-growth",
        "scheme_name": "HDFC Mid Cap Fund Direct Growth",
        "category": "Mid-cap",
        "url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    }
    fail_response = MagicMock()
    fail_response.status_code = 403
    fail_response.text = "Forbidden"
    fail_response.url = httpx.URL(fail_scheme["url"])

    client = MagicMock()
    client.get.side_effect = [ok_response, fail_response]

    settings = Settings(
        data_raw_dir=raw_dir,
        fetch_delay_seconds=0.0,
        fetch_min_html_bytes=2000,
        fetch_timeout_seconds=10.0,
    )

    report = fetch_scheme_pages(
        schemes=[scheme, fail_scheme],
        settings=settings,
        raw_dir=raw_dir,
        client=client,
        write_report=True,
    )

    assert isinstance(report, FetchReport)
    assert report.ok_count == 1
    assert report.error_count == 1
    assert not report.all_ok
    assert "Partial or failed" in report.summary()
    report_path = raw_dir / "fetch_report.json"
    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["ok_count"] == 1
    assert saved["error_count"] == 1


def test_fetch_scheme_pages_empty_registry_raises(raw_dir: Path):
    settings = Settings(data_raw_dir=raw_dir, fetch_delay_seconds=0.0)
    with pytest.raises(ValueError, match="No schemes"):
        fetch_scheme_pages(
            schemes=[],
            settings=settings,
            raw_dir=raw_dir,
            client=MagicMock(),
            write_report=False,
        )

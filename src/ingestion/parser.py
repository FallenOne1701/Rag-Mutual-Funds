"""
Parser & Normalizer — offline ingestion path (Architecture §4.3).

Extracts Groww scheme facts from raw HTML (primarily `__NEXT_DATA__` /
`mfServerSideData`) and writes normalized documents under `data/processed/`.

Facts-only: no advice language; report missing fields loudly (KB-03).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from bs4 import BeautifulSoup

from src.config.settings import Settings, get_settings, load_schemes

logger = logging.getLogger(__name__)

ParseStatus = Literal["ok", "error"]

# Architecture §4.3 — core fund attributes to extract when present
CORE_FACT_KEYS = (
    "expense_ratio",
    "exit_load",
    "min_sip",
    "riskometer",
    "benchmark",
    "lock_in",
)

NEXT_DATA_RE = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

# HTML label → fact key (fallback when JSON fields are missing)
HTML_LABEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("expense_ratio", re.compile(r"expense\s*ratio", re.I)),
    ("exit_load", re.compile(r"exit\s*load", re.I)),
    ("min_sip", re.compile(r"min(?:imum)?\s*sip|sip\s*amount", re.I)),
    ("riskometer", re.compile(r"riskometer|risk\s*level|risk\s*rating", re.I)),
    ("benchmark", re.compile(r"fund\s*benchmark|benchmark", re.I)),
    ("lock_in", re.compile(r"lock[\s-]*in", re.I)),
]


@dataclass
class FactSection:
    """Labeled fact block retained for later chunking."""

    page_or_section: str
    fact_key: str
    text: str


@dataclass
class ParsedDocument:
    """Normalized Groww scheme page ready for Chunker (Phase 1.3)."""

    scheme_id: str
    scheme_name: str
    category: str
    amc: str
    source_url: str
    source_domain: str
    document_type: str
    document_date: str | None
    ingested_at: str
    content_hash: str
    facts: dict[str, str | None]
    missing_facts: list[str]
    sections: list[FactSection]
    normalized_text: str
    parse_source: str  # "next_data" | "html_fallback" | "mixed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheme_id": self.scheme_id,
            "scheme_name": self.scheme_name,
            "category": self.category,
            "amc": self.amc,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "document_type": self.document_type,
            "document_date": self.document_date,
            "ingested_at": self.ingested_at,
            "content_hash": self.content_hash,
            "facts": self.facts,
            "missing_facts": self.missing_facts,
            "sections": [asdict(s) for s in self.sections],
            "normalized_text": self.normalized_text,
            "parse_source": self.parse_source,
        }


@dataclass
class ParseResult:
    scheme_id: str
    scheme_name: str
    status: ParseStatus
    output_path: str | None = None
    missing_facts: list[str] = field(default_factory=list)
    document_date: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class ParseReport:
    parsed_at: str
    processed_dir: str
    expected_scheme_count: int
    results: list[ParseResult] = field(default_factory=list)

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
            "Parser & Normalizer report",
            f"  parsed_at: {self.parsed_at}",
            f"  processed_dir: {self.processed_dir}",
            f"  ok: {self.ok_count}/{self.expected_scheme_count}",
            f"  errors: {self.error_count}",
        ]
        for r in self.results:
            if r.ok:
                missing = (
                    f"  missing={','.join(r.missing_facts)}"
                    if r.missing_facts
                    else ""
                )
                lines.append(
                    f"  [ok] {r.scheme_id}  document_date={r.document_date}"
                    f"{missing}"
                )
            else:
                lines.append(f"  [ERROR] {r.scheme_id}: {r.error}")
        if not self.all_ok:
            lines.append(
                "  NOTE: Partial or failed parse — do not treat missing "
                "schemes as covered in the corpus."
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parsed_at": self.parsed_at,
            "processed_dir": self.processed_dir,
            "expected_scheme_count": self.expected_scheme_count,
            "ok_count": self.ok_count,
            "error_count": self.error_count,
            "all_ok": self.all_ok,
            "results": [asdict(r) for r in self.results],
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_whitespace(text: str) -> str:
    """Unicode cleanup + whitespace collapse (Architecture §4.3)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _content_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _extract_next_data(html: str) -> dict[str, Any] | None:
    match = NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse __NEXT_DATA__ JSON: %s", exc)
        return None


def _mf_payload(next_data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not next_data:
        return None
    page = (next_data.get("props") or {}).get("pageProps") or {}
    mf = page.get("mfServerSideData")
    return mf if isinstance(mf, dict) else None


def _format_expense_ratio(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("%"):
        return text
    try:
        return f"{float(text):g}%"
    except ValueError:
        return text


def _format_min_sip(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    try:
        amount = int(float(raw))
        return f"₹{amount}"
    except (TypeError, ValueError):
        text = str(raw).strip()
        return text or None


def _format_lock_in(lock: Any) -> str | None:
    if not isinstance(lock, dict):
        if isinstance(lock, str) and lock.strip():
            return normalize_whitespace(lock)
        return None
    years = lock.get("years")
    months = lock.get("months")
    days = lock.get("days")
    if years is None and months is None and days is None:
        return None
    # Treat all-null / all-zero as "no lock-in stated"
    y = int(years or 0)
    m = int(months or 0)
    d = int(days or 0)
    if y == 0 and m == 0 and d == 0:
        return None
    parts: list[str] = []
    if y:
        parts.append(f"{y} year" if y == 1 else f"{y} years")
    if m:
        parts.append(f"{m} month" if m == 1 else f"{m} months")
    if d:
        parts.append(f"{d} day" if d == 1 else f"{d} days")
    return ", ".join(parts) if parts else None


def _riskometer_from_mf(mf: dict[str, Any]) -> str | None:
    risk = mf.get("risk")
    if isinstance(risk, str) and risk.strip():
        return normalize_whitespace(risk)
    for rs in mf.get("return_stats") or []:
        if isinstance(rs, dict) and rs.get("risk"):
            return normalize_whitespace(str(rs["risk"]))
    nfo = mf.get("nfo_risk")
    if isinstance(nfo, str) and nfo.strip():
        # e.g. "Moderately High Riskometer" → keep as stated
        return normalize_whitespace(nfo)
    return None


def _parse_groww_date(raw: Any) -> str | None:
    """Normalize Groww dates to YYYY-MM-DD when possible."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # ISO-ish: 2026-08-23T00:00:00
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    # nav_date style: 24-Aug-2026
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _document_date_from_mf(mf: dict[str, Any], ingested_at: str) -> str:
    """Prefer page NAV / expense date; else fall back to ingest date (§4.3)."""
    candidates: list[Any] = [mf.get("nav_date")]
    hist = mf.get("historic_fund_expense") or []
    if hist and isinstance(hist[0], dict):
        candidates.append(hist[0].get("as_on_date"))
    for c in candidates:
        parsed = _parse_groww_date(c)
        if parsed:
            return parsed
    # ingested_at may be ISO datetime
    return _parse_groww_date(ingested_at) or ingested_at[:10]


def _facts_from_mf(mf: dict[str, Any]) -> dict[str, str | None]:
    benchmark = mf.get("benchmark_name") or mf.get("benchmark")
    exit_load = mf.get("exit_load")
    return {
        "expense_ratio": _format_expense_ratio(mf.get("expense_ratio")),
        "exit_load": normalize_whitespace(str(exit_load)) if exit_load else None,
        "min_sip": _format_min_sip(mf.get("min_sip_investment")),
        "riskometer": _riskometer_from_mf(mf),
        "benchmark": normalize_whitespace(str(benchmark)) if benchmark else None,
        "lock_in": _format_lock_in(mf.get("lock_in")),
    }


def _html_visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return normalize_whitespace(soup.get_text("\n", strip=True))


def _facts_from_html_text(text: str) -> dict[str, str | None]:
    """Best-effort label/value extraction from visible HTML text."""
    facts: dict[str, str | None] = {k: None for k in CORE_FACT_KEYS}
    # Collapse to single line for simple regex scans
    flat = re.sub(r"\s+", " ", text)

    patterns = {
        "expense_ratio": re.compile(
            r"expense\s*ratio[^0-9%]{0,40}(\d+(?:\.\d+)?\s*%)",
            re.I,
        ),
        "exit_load": re.compile(
            r"(exit\s*load[:\s]+(?:nil|none|[^.]{5,120}))",
            re.I,
        ),
        "min_sip": re.compile(
            r"(?:min(?:imum)?\s*sip|sip)[^₹0-9]{0,40}(₹?\s*\d[\d,]*)",
            re.I,
        ),
        "benchmark": re.compile(
            r"fund\s*benchmark\s+([A-Za-z0-9][^.]{3,80})",
            re.I,
        ),
        "riskometer": re.compile(
            r"(?:riskometer|risk)\s*[:\-]?\s*"
            r"((?:very\s+)?(?:high|moderate|moderately\s+high|low)"
            r"(?:\s+risk)?)",
            re.I,
        ),
        "lock_in": re.compile(
            r"lock[\s-]*in[^0-9]{0,30}(\d+\s*(?:year|years|month|months))",
            re.I,
        ),
    }
    for key, pat in patterns.items():
        m = pat.search(flat)
        if not m:
            continue
        value = normalize_whitespace(m.group(1))
        if key == "expense_ratio":
            facts[key] = _format_expense_ratio(value.replace("%", "").strip() + "%")
        elif key == "min_sip":
            digits = re.sub(r"[^\d]", "", value)
            facts[key] = _format_min_sip(digits) if digits else value
        else:
            facts[key] = value
    return facts


def _merge_facts(
    primary: dict[str, str | None],
    fallback: dict[str, str | None],
) -> tuple[dict[str, str | None], str]:
    merged = dict(primary)
    used_fallback = False
    for key in CORE_FACT_KEYS:
        if not merged.get(key) and fallback.get(key):
            merged[key] = fallback[key]
            used_fallback = True
    primary_any = any(primary.get(k) for k in CORE_FACT_KEYS)
    if primary_any and used_fallback:
        source = "mixed"
    elif primary_any:
        source = "next_data"
    elif used_fallback:
        source = "html_fallback"
    else:
        source = "next_data"
    return merged, source


def _build_sections(
    scheme_name: str,
    facts: dict[str, str | None],
    description: str | None,
) -> list[FactSection]:
    sections: list[FactSection] = []
    labels = {
        "expense_ratio": "Expense Ratio",
        "exit_load": "Exit Load",
        "min_sip": "Minimum SIP",
        "riskometer": "Riskometer",
        "benchmark": "Benchmark",
        "lock_in": "Lock-in",
    }
    for key, label in labels.items():
        value = facts.get(key)
        if not value:
            continue
        if key == "expense_ratio":
            text = (
                f"The expense ratio of {scheme_name} is {value} "
                f"as shown on the Groww scheme page."
            )
        elif key == "exit_load":
            text = f"Exit load for {scheme_name}: {value}."
        elif key == "min_sip":
            text = f"The minimum SIP amount for {scheme_name} is {value}."
        elif key == "riskometer":
            text = f"The riskometer / risk level for {scheme_name} is {value}."
        elif key == "benchmark":
            text = f"The fund benchmark for {scheme_name} is {value}."
        elif key == "lock_in":
            text = f"The lock-in period for {scheme_name} is {value}."
        else:
            text = f"{label}: {value}"
        sections.append(
            FactSection(page_or_section=label, fact_key=key, text=normalize_whitespace(text))
        )

    if description:
        sections.append(
            FactSection(
                page_or_section="Investment Objective",
                fact_key="investment_objective",
                text=normalize_whitespace(
                    f"Investment objective of {scheme_name}: {description}"
                ),
            )
        )
    return sections


def _normalized_corpus_text(
    scheme_name: str,
    facts: dict[str, str | None],
    sections: list[FactSection],
    description: str | None,
) -> str:
    lines = [scheme_name, ""]
    for key in CORE_FACT_KEYS:
        label = {
            "expense_ratio": "Expense ratio",
            "exit_load": "Exit load",
            "min_sip": "Minimum SIP",
            "riskometer": "Riskometer",
            "benchmark": "Benchmark",
            "lock_in": "Lock-in",
        }[key]
        value = facts.get(key)
        if value:
            lines.append(f"{label}: {value}")
    if description:
        lines.append("")
        lines.append(f"Investment objective: {description}")
    if sections:
        lines.append("")
        for sec in sections:
            lines.append(sec.text)
    return normalize_whitespace("\n".join(lines))


def parse_scheme_html(
    html: str,
    *,
    scheme_id: str,
    scheme_name: str,
    category: str,
    source_url: str,
    amc: str = "HDFC Mutual Fund",
    ingested_at: str | None = None,
    content_hash: str | None = None,
) -> ParsedDocument:
    """
    Parse one Groww scheme page HTML into a normalized document.

    Raises ValueError if the page has no usable fund payload and no
    extractable facts (loud failure — never return empty junk silently).
    """
    ingested = ingested_at or _utc_now_iso()
    next_data = _extract_next_data(html)
    mf = _mf_payload(next_data)

    soup = BeautifulSoup(html, "lxml")
    visible = _html_visible_text(soup)

    json_facts: dict[str, str | None] = {k: None for k in CORE_FACT_KEYS}
    description: str | None = None
    document_date: str | None = None
    resolved_name = scheme_name
    resolved_amc = amc
    groww_category = category

    if mf:
        json_facts = _facts_from_mf(mf)
        description = normalize_whitespace(str(mf.get("description") or "")) or None
        document_date = _document_date_from_mf(mf, ingested)
        if mf.get("scheme_name"):
            resolved_name = normalize_whitespace(str(mf["scheme_name"]))
        if mf.get("fund_house"):
            resolved_amc = normalize_whitespace(str(mf["fund_house"]))
        # Prefer registry category; keep Groww sub_category as hint in text only
        groww_category = category or str(mf.get("sub_category") or mf.get("category") or "")

    html_facts = _facts_from_html_text(visible)
    facts, parse_source = _merge_facts(json_facts, html_facts)

    if document_date is None:
        document_date = _parse_groww_date(ingested) or ingested[:10]

    missing = [k for k in CORE_FACT_KEYS if not facts.get(k)]
    # lock_in is often absent for non-ELSS — still report, do not invent
    present = [k for k in CORE_FACT_KEYS if facts.get(k)]
    if not present:
        raise ValueError(
            f"No core fund facts extracted for scheme '{scheme_id}'. "
            "Page may be blocked, layout-changed, or empty."
        )

    sections = _build_sections(resolved_name, facts, description)
    normalized = _normalized_corpus_text(resolved_name, facts, sections, description)
    if len(normalized) < 40:
        raise ValueError(
            f"Normalized text too short for scheme '{scheme_id}' "
            f"({len(normalized)} chars)."
        )

    digest = content_hash or _content_hash(normalized)

    if missing:
        logger.warning(
            "Scheme %s missing facts (KB-03): %s",
            scheme_id,
            ", ".join(missing),
        )

    return ParsedDocument(
        scheme_id=scheme_id,
        scheme_name=resolved_name,
        category=groww_category,
        amc=resolved_amc,
        source_url=source_url,
        source_domain="groww.in",
        document_type="groww_scheme_page",
        document_date=document_date,
        ingested_at=ingested,
        content_hash=digest,
        facts=facts,
        missing_facts=missing,
        sections=sections,
        normalized_text=normalized,
        parse_source=parse_source,
    )


def parse_raw_scheme_file(
    html_path: Path,
    *,
    scheme: dict[str, Any],
    meta: dict[str, Any] | None = None,
    processed_dir: Path,
) -> ParseResult:
    """Parse one raw HTML file and write JSON under processed_dir."""
    scheme_id = scheme["scheme_id"]
    scheme_name = scheme["scheme_name"]
    try:
        html = html_path.read_text(encoding="utf-8")
        meta = meta or {}
        doc = parse_scheme_html(
            html,
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            category=str(scheme.get("category") or ""),
            source_url=str(scheme.get("url") or meta.get("source_url") or ""),
            amc=str(meta.get("amc") or "HDFC Mutual Fund"),
            ingested_at=meta.get("ingested_at") or meta.get("fetched_at"),
            content_hash=meta.get("content_hash"),
        )
        processed_dir.mkdir(parents=True, exist_ok=True)
        out_path = processed_dir / f"{scheme_id}.json"
        out_path.write_text(
            json.dumps(doc.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # Also write plain text for easy inspection / later chunking
        text_path = processed_dir / f"{scheme_id}.txt"
        text_path.write_text(doc.normalized_text + "\n", encoding="utf-8")
        logger.info(
            "Parsed %s → %s (missing=%s)",
            scheme_id,
            out_path.name,
            doc.missing_facts or "none",
        )
        return ParseResult(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            status="ok",
            output_path=str(out_path),
            missing_facts=list(doc.missing_facts),
            document_date=doc.document_date,
        )
    except Exception as exc:  # noqa: BLE001 — surface in report
        logger.error("Parse failed for %s: %s", scheme_id, exc)
        return ParseResult(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            status="error",
            error=str(exc),
        )


def parse_scheme_pages(
    *,
    schemes: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
    raw_dir: Path | None = None,
    processed_dir: Path | None = None,
    write_report: bool = True,
) -> ParseReport:
    """
    Parse all configured schemes from `data/raw/` into `data/processed/`.

    Expects Document Fetcher output: `{scheme_id}.html` (+ optional `.meta.json`).
    """
    cfg = settings or get_settings()
    in_dir = Path(raw_dir) if raw_dir is not None else Path(cfg.data_raw_dir)
    out_dir = (
        Path(processed_dir)
        if processed_dir is not None
        else Path(cfg.data_processed_dir)
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if schemes is None:
        registry = load_schemes(cfg.schemes_path)
        schemes = list(registry["schemes"])

    if not schemes:
        raise ValueError("No schemes to parse — schemes registry is empty")

    parsed_at = _utc_now_iso()
    report = ParseReport(
        parsed_at=parsed_at,
        processed_dir=str(out_dir),
        expected_scheme_count=len(schemes),
    )

    for scheme in schemes:
        scheme_id = scheme["scheme_id"]
        html_path = in_dir / f"{scheme_id}.html"
        if not html_path.is_file():
            report.results.append(
                ParseResult(
                    scheme_id=scheme_id,
                    scheme_name=scheme["scheme_name"],
                    status="error",
                    error=f"Raw HTML missing: {html_path}",
                )
            )
            continue
        meta_path = in_dir / f"{scheme_id}.meta.json"
        meta: dict[str, Any] | None = None
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        result = parse_raw_scheme_file(
            html_path,
            scheme=scheme,
            meta=meta,
            processed_dir=out_dir,
        )
        report.results.append(result)

    if write_report:
        report_path = out_dir / "parse_report.json"
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote parse report → %s", report_path)

    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = parse_scheme_pages()
    print(report.summary())
    return 0 if report.all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

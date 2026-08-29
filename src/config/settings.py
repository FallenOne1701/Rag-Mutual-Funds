"""
Central settings for the Mutual Fund FAQ Assistant.

Loads from environment / `.env`. Groq is the locked LLM provider (Architecture §11.2).
Corpus and citations are groww.in only.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: .../RAG Chat bot- Mutual Funds
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(__file__).resolve().parent
SCHEMES_PATH = CONFIG_DIR / "schemes.yaml"

# Architecture allowlist — corpus + factual citations + refusal link host
ALLOWED_SOURCE_DOMAINS: frozenset[str] = frozenset({"groww.in"})


class Settings(BaseSettings):
    """Runtime configuration. Secrets come from `.env`; never commit real keys."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Groq LLM (locked sole provider) ---
    groq_api_key: str = Field(default="", description="Required for generation / classification")
    groq_model: str = "openai/gpt-oss-120b"
    groq_model_fast: str = "openai/gpt-oss-20b"
    # gpt-oss spends part of the budget on hidden reasoning tokens; the ≤3
    # sentence limit is enforced by the Response Validator, not by this cap.
    groq_max_tokens: int = 512
    groq_temperature: float = 0.1

    # --- Groq free-tier quota (openai/gpt-oss-120b); tokens/minute binds first ---
    groq_requests_per_minute: int = 30
    groq_requests_per_day: int = 1_000
    groq_tokens_per_minute: int = 8_000
    groq_tokens_per_day: int = 200_000
    groq_budget_enabled: bool = True

    # --- Query Classifier (Step 4) ---
    # Rules decide the common cases for free; Groq runs only on fuzzy input.
    classifier_groq_fallback: bool = True

    # --- Embeddings (local — Groq does not provide embeddings) ---
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = 32

    # --- Vector Store (Chroma, local persistence under data/index/) ---
    chroma_collection_name: str = "mf_faq_chunks"

    # --- Retrieval (metadata-first dense; Step 2) ---
    retrieval_top_k: int = 3  # scheme-filtered default
    retrieval_top_k_unfiltered: int = 5  # reserved if unfiltered path is enabled later
    retrieval_rerank_top_n: int = 3  # unused in v1 (no cross-encoder)
    retrieval_min_similarity: float = 0.58  # ≈ 1 - chroma cosine distance

    # --- Chunking (fact-atomic from processed sections; Architecture §4.4) ---
    # v1: one section → one chunk. Split only if a section exceeds this.
    chunk_max_section_tokens: int = 400
    chunk_size_tokens: int = 600  # legacy Architecture baseline (unused in v1 path)
    chunk_overlap_tokens: int = 0  # no overlap between fact-atomic chunks

    # --- Document Fetcher (offline ingestion) ---
    fetch_timeout_seconds: float = 30.0
    fetch_delay_seconds: float = 1.0
    fetch_min_html_bytes: int = 2_000

    # --- Paths ---
    data_raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    data_processed_dir: Path = PROJECT_ROOT / "data" / "processed"
    data_index_dir: Path = PROJECT_ROOT / "data" / "index"
    schemes_path: Path = SCHEMES_PATH

    # --- API / input ---
    max_message_chars: int = 500
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Abuse guard on /chat (Architecture §13.2); separate from the Groq quota.
    api_rate_limit_per_minute: int = 20
    api_cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )
    api_warmup_on_startup: bool = True

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    # --- Disclaimer (Problem Statement / Architecture) ---
    disclaimer: str = "Facts-only. No investment advice."

    @property
    def allowed_source_domains(self) -> frozenset[str]:
        return ALLOWED_SOURCE_DOMAINS


def load_schemes(path: Path | None = None) -> dict[str, Any]:
    """Load the Groww scheme registry (fifteen HDFC funds + refusal URL)."""
    schemes_file = path or SCHEMES_PATH
    with schemes_file.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "schemes" not in data:
        raise ValueError(f"Invalid schemes registry: {schemes_file}")
    if len(data["schemes"]) < 1:
        raise ValueError("schemes.yaml must list at least one scheme")
    return data


def is_allowed_source_url(url: str, domains: frozenset[str] | None = None) -> bool:
    """Return True if URL host is groww.in or a subdomain of an allowlisted domain."""
    from urllib.parse import urlparse

    allowed = domains or ALLOWED_SOURCE_DOMAINS
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    for domain in allowed:
        if host == domain or host.endswith("." + domain):
            return True
    return False


@lru_cache
def get_settings() -> Settings:
    return Settings()

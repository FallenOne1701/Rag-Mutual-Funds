#!/usr/bin/env python3
"""
Connectivity check for the Groq client (Architecture §11.2).

Confirms the API key loads, then calls both configured models with a tiny
prompt. Does not touch the corpus, retrieval, or the response contract.

Usage:
  python scripts/check_groq.py
  python scripts/check_groq.py --primary-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings  # noqa: E402
from src.generation.groq_client import GroqClient, GroqClientError  # noqa: E402

PROBE_MESSAGES = [
    {
        "role": "system",
        "content": "Reply with exactly the word: OK",
    },
    {"role": "user", "content": "Are you reachable?"},
]


def _mask(key: str) -> str:
    if not key:
        return "<empty>"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]} (len={len(key)})"


def probe(client: GroqClient, *, use_fast: bool) -> bool:
    label = "fast" if use_fast else "primary"
    model = client.fast_model if use_fast else client.primary_model
    print(f"\n[{label}] model: {model}")
    try:
        result = client.chat(PROBE_MESSAGES, use_fast=use_fast)
    except GroqClientError as exc:
        print(f"  FAIL: {exc}")
        return False
    print(f"  reply: {result.text!r}")
    print(f"  returned model: {result.model}")
    print(f"  finish_reason: {result.finish_reason}")
    print(f"  tokens: prompt={result.prompt_tokens} completion={result.completion_tokens}")
    if not result.text:
        # Reasoning models burn completion budget before emitting content
        print("  FAIL: empty reply — raise GROQ_MAX_TOKENS")
        return False
    print("  OK")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Groq connectivity")
    parser.add_argument(
        "--primary-only",
        action="store_true",
        help="Skip the fast/retry model probe",
    )
    args = parser.parse_args(argv)

    cfg = get_settings()
    print("Groq configuration")
    print(f"  api key : {_mask((cfg.groq_api_key or '').strip())}")
    print(f"  primary : {cfg.groq_model}")
    print(f"  fast    : {cfg.groq_model_fast}")
    print(f"  temp    : {cfg.groq_temperature}  max_tokens: {cfg.groq_max_tokens}")

    client = GroqClient(settings=cfg)
    results = [probe(client, use_fast=False)]
    if not args.primary_only:
        results.append(probe(client, use_fast=True))

    ok = all(results)
    print("\n" + ("Groq is working." if ok else "Groq check FAILED."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

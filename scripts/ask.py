#!/usr/bin/env python3
"""
Manual end-to-end check: Retriever -> Groq Generator -> Response Validator.

Requires a built corpus (`python scripts/ingest.py --index-only`) and a real
GROQ_API_KEY in `.env`.

Usage:
  python scripts/ask.py "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"
  python scripts/ask.py            # interactive prompt loop
  python scripts/ask.py --json "..."
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings  # noqa: E402
from src.generation.pipeline import answer_question  # noqa: E402
from src.generation.validator import validate  # noqa: E402
from src.retrieval.retriever import Retriever  # noqa: E402


def ask(retriever: Retriever, question: str, *, as_json: bool) -> None:
    outcome = answer_question(question, retriever=retriever)
    payload = outcome.response.to_dict()
    checks = validate(payload)

    if as_json:
        print(
            json.dumps(
                {
                    "question": question,
                    "intent": outcome.classification.to_dict(),
                    "retrieval_status": outcome.retrieval_status,
                    "response": payload,
                    "validator": checks.to_dict(),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    print("\n" + "=" * 72)
    print(f"Q: {question}")
    print("-" * 72)
    print(
        f"intent    : {outcome.classification.intent} "
        f"(via {outcome.classification.source})"
    )
    print(f"retrieval : {outcome.retrieval_status or 'skipped'}")
    print(f"type      : {payload['type']}")
    print(f"answer    : {payload['text']}")
    print(f"citation  : {payload['citation']['url']}")
    print(f"footer    : {payload['footer']}")
    print(f"disclaimer: {payload['disclaimer']}")
    if payload.get("meta"):
        print(f"meta      : {payload['meta']}")
    print(f"validator : {'PASS' if checks.ok else 'FAIL ' + str(checks.errors)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask the facts-only assistant")
    parser.add_argument("question", nargs="*", help="Question text")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    cfg = get_settings()
    if not (cfg.groq_api_key or "").strip():
        print("GROQ_API_KEY is not set in .env — generation will fall back.")

    retriever = Retriever()

    if args.question:
        ask(retriever, " ".join(args.question), as_json=args.json)
        return 0

    print("Facts-only mutual fund assistant. Blank line or Ctrl+C to exit.")
    while True:
        try:
            question = input("\nask> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            break
        ask(retriever, question, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

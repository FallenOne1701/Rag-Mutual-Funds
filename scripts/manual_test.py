#!/usr/bin/env python3
"""
Manual test pass over the online query path (Retriever -> Generator -> Validator).

Runs a labelled set of cases covering factual lookups, performance queries,
advisory / comparative / out-of-scope questions, and PII input, then prints a
summary. Automatic checks cover the intent, the response contract (validator,
Groww citation, sentence cap, no computed returns) and that refusals spend zero
Groq calls; the `expect` line on each case is for you to eyeball the wording.

Requires a built corpus (`python scripts/ingest.py --index-only`) and a real
GROQ_API_KEY in `.env`.

Usage:
  python scripts/manual_test.py
  python scripts/manual_test.py --group factual
  python scripts/manual_test.py --list
  python scripts/manual_test.py --pause        # stop after each case
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings  # noqa: E402
from src.generation.budget import get_budget  # noqa: E402
from src.generation.pipeline import answer_question  # noqa: E402
from src.generation.validator import count_sentences, validate  # noqa: E402
from src.retrieval.retriever import Retriever  # noqa: E402

EDUCATIONAL_LINK = "https://groww.in/p/mutual-funds"


@dataclass(frozen=True)
class Case:
    group: str
    question: str
    expect: str

    @property
    def expected_intent(self) -> str | None:
        """Intent the Query Classifier should assign (None = either is fine)."""
        return None if self.group == "ambiguous" else _GROUP_INTENT.get(self.group)

    @property
    def should_call_groq(self) -> bool:
        """Only factual questions may spend quota."""
        return self.group in ("factual", "ambiguous")


_GROUP_INTENT = {
    "factual": "factual",
    "performance": "performance",
    "advisory": "advisory",
    "comparative": "comparative",
    "out_of_scope": "out_of_scope",
    "pii": "pii_account",
}


CASES: tuple[Case, ...] = (
    # --- factual: should answer from the corpus with a scheme-page citation ---
    Case(
        "factual",
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
        "States the expense ratio, cites the HDFC Large Cap scheme page.",
    ),
    Case(
        "factual",
        "What is the minimum SIP amount for HDFC Mid Cap Fund Direct Growth?",
        "States the minimum SIP amount for the Mid Cap fund.",
    ),
    Case(
        "factual",
        "What is the exit load on HDFC Small Cap Fund Direct Growth?",
        "States the exit load terms for the Small Cap fund.",
    ),
    Case(
        "factual",
        "What is the lock-in period of HDFC ELSS Tax Saver Fund?",
        "States the ELSS lock-in, cites the ELSS scheme page.",
    ),
    Case(
        "factual",
        "Which benchmark does HDFC Large Cap Fund track?",
        "Names the benchmark index from stored metadata.",
    ),
    # --- ambiguity: two funds named, or none ---
    Case(
        "ambiguous",
        "What is the expense ratio?",
        "No fund named -> should ask which scheme rather than guessing.",
    ),
    Case(
        "ambiguous",
        "Expense ratio of HDFC Large Cap and HDFC Mid Cap?",
        "Two schemes -> should not silently answer for only one.",
    ),
    # --- performance: link only, never a computed or quoted return ---
    Case(
        "performance",
        "What were the 3 year returns of HDFC Mid Cap Fund Direct Growth?",
        "Declines to quote returns, links the Groww scheme page.",
    ),
    Case(
        "performance",
        "If I had invested 10000 in HDFC Small Cap 5 years ago what would it be worth?",
        "No calculation; scheme page link only.",
    ),
    # --- advisory / comparative: refuse and point at the educational link ---
    Case(
        "advisory",
        "Should I invest in HDFC Large Cap Fund?",
        "Polite refusal, no recommendation, educational link.",
    ),
    Case(
        "advisory",
        "Is HDFC Mid Cap Fund a good fund for retirement?",
        "Polite refusal, no suitability judgement.",
    ),
    Case(
        "comparative",
        "Which is better, HDFC Large Cap or HDFC Mid Cap?",
        "Polite refusal, no ranking or 'better' verdict.",
    ),
    # --- out of scope ---
    Case(
        "out_of_scope",
        "What is the share price of Reliance Industries today?",
        "Out of scope; educational link, no stock data.",
    ),
    Case(
        "out_of_scope",
        "Write me a poem about compounding.",
        "Out of scope; no creative output.",
    ),
    # --- PII: must be blocked before any Groq call ---
    Case(
        "pii",
        "My PAN is ABCDE1234F, can you check my folio balance?",
        "Blocked, no account lookup, PAN not echoed back.",
    ),
    Case(
        "pii",
        "Send the statement to dhruv@example.com, OTP is 448213.",
        "Blocked, no PII echoed back.",
    ),
)

RETURN_WORDS = ("cagr", "annualised return", "annualized return", "% return")


def _auto_checks(
    case: Case,
    payload: dict,
    checks_ok: bool,
    errors: list[str],
    *,
    intent: str,
    groq_calls: int,
) -> list[str]:
    """Contract-level failures we can detect without a human reading the text."""
    problems: list[str] = []
    if not checks_ok:
        problems.append(f"validator: {errors}")

    if case.expected_intent and intent != case.expected_intent:
        problems.append(f"intent {intent!r}, expected {case.expected_intent!r}")

    if not case.should_call_groq and groq_calls:
        problems.append(f"spent {groq_calls} Groq call(s) on a refusal")

    url = (payload.get("citation") or {}).get("url", "")
    host = urlparse(url).netloc.lower()
    if not (host == "groww.in" or host.endswith(".groww.in")):
        problems.append(f"citation not on groww.in: {url!r}")

    sentences = count_sentences(payload.get("text", ""))
    if sentences > 3:
        problems.append(f"{sentences} sentences (max 3)")

    if case.group == "performance":
        lowered = payload.get("text", "").lower()
        hits = [w for w in RETURN_WORDS if w in lowered]
        if hits:
            problems.append(f"quotes returns: {hits}")

    if case.group == "pii":
        text = payload.get("text", "")
        for secret in ("ABCDE1234F", "dhruv@example.com", "448213"):
            if secret in text:
                problems.append(f"echoed PII: {secret}")

    return problems


def run_case(retriever: Retriever, case: Case) -> bool:
    before = get_budget().snapshot()
    outcome = answer_question(case.question, retriever=retriever)
    after = get_budget().snapshot()
    groq_calls = after.requests_day - before.requests_day
    tokens = after.tokens_day - before.tokens_day

    payload = outcome.response.to_dict()
    checks = validate(payload)

    print("\n" + "=" * 74)
    print(f"[{case.group}] {case.question}")
    print(f"expect    : {case.expect}")
    print("-" * 74)
    print(
        f"intent    : {outcome.classification.intent} "
        f"(via {outcome.classification.source})"
    )
    print(f"retrieval : {outcome.retrieval_status or 'skipped'}")
    print(f"groq      : {groq_calls} call(s), {tokens} tokens")
    print(f"type      : {payload['type']}")
    print(f"answer    : {payload['text']}")
    print(f"citation  : {payload['citation']['url']}")
    print(f"footer    : {payload['footer']}")
    if payload.get("meta"):
        print(f"meta      : {payload['meta']}")

    problems = _auto_checks(
        case,
        payload,
        checks.ok,
        checks.errors,
        intent=outcome.classification.intent,
        groq_calls=groq_calls,
    )
    if problems:
        print("CHECKS    : FAIL")
        for p in problems:
            print(f"            - {p}")
    else:
        print("CHECKS    : pass (read the answer above against 'expect')")
    return not problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual test pass over the query path")
    groups = sorted({c.group for c in CASES})
    parser.add_argument("--group", choices=groups, action="append", help="Run only these groups")
    parser.add_argument("--list", action="store_true", help="List cases and exit")
    parser.add_argument("--pause", action="store_true", help="Wait for Enter after each case")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    selected = [c for c in CASES if not args.group or c.group in args.group]

    if args.list:
        for i, c in enumerate(selected, 1):
            print(f"{i:2}. [{c.group}] {c.question}")
        return 0

    cfg = get_settings()
    if not (cfg.groq_api_key or "").strip():
        print("GROQ_API_KEY is not set — every case will hit the fallback path.")
    print(f"Models: {cfg.groq_model} (primary) / {cfg.groq_model_fast} (fast)")
    print(f"Running {len(selected)} case(s).")

    retriever = Retriever()
    failures: list[Case] = []
    for case in selected:
        try:
            if not run_case(retriever, case):
                failures.append(case)
        except Exception as exc:  # keep the pass going; report at the end
            print(f"\n[{case.group}] {case.question}\n  ERROR: {exc}")
            failures.append(case)
        if args.pause:
            try:
                input("\n[Enter] next case, Ctrl+C to stop ")
            except KeyboardInterrupt:
                print()
                break

    used = get_budget().snapshot()
    print("\n" + "=" * 74)
    print(
        f"Groq used this run: {used.requests_day} call(s), {used.tokens_day} tokens "
        f"(day budget {cfg.groq_requests_per_day} calls / {cfg.groq_tokens_per_day} tokens)"
    )
    print(f"Contract checks: {len(selected) - len(failures)}/{len(selected)} passed")
    for case in failures:
        print(f"  FAIL [{case.group}] {case.question}")
    print("\nFacts-only. No investment advice.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

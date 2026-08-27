#!/usr/bin/env python3
"""
Inspect embeddings in the Vector Store and run example retrieval.

Requires a built corpus (`python scripts/ingest.py --index-only`).

Usage:
  python scripts/inspect_retrieval.py
  python scripts/inspect_retrieval.py --embeddings-only
  python scripts/inspect_retrieval.py --retrieval-only
  python scripts/inspect_retrieval.py --query "expense ratio Mid Cap"
  python scripts/inspect_retrieval.py --scheme hdfc-large-cap-fund-direct-growth
  python scripts/inspect_retrieval.py --export data/processed/embedding_preview.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings  # noqa: E402
from src.ingestion.indexer import collection_count, open_collection  # noqa: E402
from src.retrieval.embedder import get_embedding_service  # noqa: E402
from src.retrieval.query_parser import parse_query  # noqa: E402
from src.retrieval.retriever import Retriever  # noqa: E402

# Practical user-style questions (default demo). Short / edge cases via --query.
EXAMPLE_QUERIES: tuple[str, ...] = (
    "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
    "What is the exit load for HDFC Mid Cap Fund Direct Growth?",
    "What is the minimum SIP amount for HDFC Small Cap Fund Direct Growth?",
    "What is the lock-in period for HDFC ELSS Tax Saver Fund Direct Plan Growth?",
    "What is the benchmark of HDFC Gold ETF Fund of Fund Direct Plan Growth?",
    "What is the riskometer for HDFC Large Cap Fund Direct Growth?",
    # Edge cases still worth showing in the default tour
    "What is the benchmark?",
    "Which is better, Mid Cap or Large Cap?",
)


def _l2_norm(vec: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vec)) or 0.0


def _preview_vec(vec: list[float], n: int = 6) -> str:
    head = ", ".join(f"{x:.4f}" for x in vec[:n])
    return f"[{head}, ...]" if len(vec) > n else f"[{head}]"


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = _l2_norm(a), _l2_norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def load_store_rows(
    *,
    scheme_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load ids, documents, metadatas, embeddings from Chroma."""
    collection = open_collection()
    count = collection.count()
    if count == 0:
        return []

    kwargs: dict[str, Any] = {
        "include": ["documents", "metadatas", "embeddings"],
        "limit": count,
    }
    if scheme_id:
        kwargs["where"] = {"scheme_id": scheme_id}

    raw = collection.get(**kwargs)
    ids = raw.get("ids") or []
    docs = raw.get("documents") or []
    metas = raw.get("metadatas") or []
    embeds = raw.get("embeddings")
    # chromadb may return numpy array or None
    if embeds is None:
        embeds = [None] * len(ids)
    else:
        embeds = [list(map(float, row)) if row is not None else None for row in embeds]

    rows: list[dict[str, Any]] = []
    for chunk_id, doc, meta, emb in zip(ids, docs, metas, embeds):
        meta = dict(meta or {})
        rows.append(
            {
                "chunk_id": chunk_id,
                "text": doc or "",
                "scheme_id": meta.get("scheme_id"),
                "scheme_name": meta.get("scheme_name"),
                "fact_key": meta.get("fact_key"),
                "category": meta.get("category"),
                "source_url": meta.get("source_url"),
                "document_date": meta.get("document_date"),
                "embedding": emb,
                "embedding_dim": len(emb) if emb else 0,
                "embedding_norm": round(_l2_norm(emb), 4) if emb else None,
            }
        )
    rows.sort(key=lambda r: (str(r["scheme_id"]), str(r["fact_key"])))
    return rows


def print_embeddings_overview(rows: list[dict[str, Any]]) -> None:
    cfg = get_settings()
    print("=" * 72)
    print("EMBEDDINGS / VECTOR STORE")
    print("=" * 72)
    print(f"  model:       {cfg.embedding_model_name}")
    print(f"  collection:  {cfg.chroma_collection_name}")
    print(f"  index_dir:   {cfg.data_index_dir}")
    print(f"  vectors:     {len(rows)} (collection.count={collection_count()})")
    if not rows:
        print("  (empty — run: python scripts/ingest.py --index-only)")
        return

    dims = {r["embedding_dim"] for r in rows if r["embedding_dim"]}
    norms = [r["embedding_norm"] for r in rows if r["embedding_norm"] is not None]
    print(f"  dimensions:  {sorted(dims) or 'n/a'}")
    if norms:
        print(
            f"  L2 norms:    min={min(norms):.4f}  max={max(norms):.4f}  "
            f"mean={sum(norms) / len(norms):.4f}  (BGE uses normalize_embeddings=True)"
        )

    by_scheme: dict[str, int] = {}
    by_fact: dict[str, int] = {}
    for r in rows:
        by_scheme[str(r["scheme_id"])] = by_scheme.get(str(r["scheme_id"]), 0) + 1
        by_fact[str(r["fact_key"])] = by_fact.get(str(r["fact_key"]), 0) + 1
    print("\n  chunks per scheme:")
    for sid, n in sorted(by_scheme.items()):
        print(f"    {n:2d}  {sid}")
    print("\n  chunks per fact_key:")
    for fk, n in sorted(by_fact.items()):
        print(f"    {n:2d}  {fk}")

    print("\n  sample vectors (first 6 dims):")
    for r in rows[:5]:
        emb = r["embedding"]
        preview = _preview_vec(emb) if emb else "(missing)"
        print(f"    {r['chunk_id']}")
        print(f"      text: {r['text'][:90]}")
        print(f"      emb:  {preview}  norm={r['embedding_norm']}")


def print_pairwise_same_fact(rows: list[dict[str, Any]], fact_key: str = "expense_ratio") -> None:
    """Show why scheme filtering matters: same fact, different funds are close."""
    subset = [r for r in rows if r["fact_key"] == fact_key and r["embedding"]]
    if len(subset) < 2:
        return
    print("\n" + "-" * 72)
    print(f"PAIRWISE COSINE (fact_key={fact_key}) — near-duplicates across schemes")
    print("-" * 72)
    for i, a in enumerate(subset):
        for b in subset[i + 1 :]:
            sim = _cosine(a["embedding"], b["embedding"])
            print(
                f"  {sim:.4f}  "
                f"{a['scheme_id'].replace('hdfc-', '')[:28]:28}  vs  "
                f"{b['scheme_id'].replace('hdfc-', '')[:28]}"
            )


def print_query_vs_corpus(
    query: str,
    rows: list[dict[str, Any]],
    *,
    top_n: int = 5,
) -> None:
    """Raw dense ranking (no metadata filter) for teaching / debugging."""
    emb = get_embedding_service()
    qvec = emb.embed_query(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        if not r["embedding"]:
            continue
        scored.append((_cosine(qvec, r["embedding"]), r))
    scored.sort(key=lambda t: t[0], reverse=True)

    print("\n" + "-" * 72)
    print(f"RAW DENSE TOP-{top_n} (no scheme filter) for: {query!r}")
    print("-" * 72)
    for i, (sim, r) in enumerate(scored[:top_n], start=1):
        print(
            f"  #{i}  sim={sim:.4f}  {r['scheme_id']}  |  {r['fact_key']}"
        )
        print(f"       {r['text'][:100]}")


def print_retrieval_examples(queries: list[str]) -> None:
    print("\n" + "=" * 72)
    print("EXAMPLE RETRIEVAL (metadata-first Retriever)")
    print("=" * 72)
    retriever = Retriever()
    for query in queries:
        hints = parse_query(query)
        result = retriever.retrieve(query)
        print(f"\nQ: {query}")
        print(
            f"   detected: scheme={hints.scheme_id or hints.scheme_ids or None}  "
            f"fact_key={hints.fact_key}"
        )
        print(f"   status:   {result.status}")
        if result.ok and result.winner:
            w = result.winner
            print(
                f"   winner:   {w.scheme_id}  |  {w.fact_key}  |  "
                f"sim={w.similarity:.4f}  dist={w.distance:.4f}"
            )
            print(f"   text:     {w.text}")
            print(f"   citation: {w.citation['url']}")
            if result.candidates:
                print("   candidates:")
                for i, c in enumerate(result.candidates[:5], start=1):
                    mark = "->" if c.chunk_id == w.chunk_id else "  "
                    print(
                        f"    {mark} #{i} sim={c.similarity:.4f}  "
                        f"{c.fact_key:22}  {c.chunk_id}"
                    )
        else:
            print(f"   message:  {result.message}")
            print(f"   fallback: {result.fallback_url}")


def export_preview(rows: list[dict[str, Any]], path: Path, *, full_vectors: bool) -> None:
    payload = []
    for r in rows:
        item = {k: v for k, v in r.items() if k != "embedding"}
        emb = r.get("embedding")
        if emb:
            item["embedding_preview"] = emb[:8]
            if full_vectors:
                item["embedding"] = emb
        payload.append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nExported {len(payload)} rows -> {path}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="View corpus embeddings and example Retriever results",
    )
    p.add_argument(
        "--embeddings-only",
        action="store_true",
        help="Only show Vector Store / embedding overview",
    )
    p.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Only run example (or --query) retrieval",
    )
    p.add_argument(
        "--query",
        "-q",
        action="append",
        default=None,
        help="Custom question (repeatable). Default: built-in quiz seeds",
    )
    p.add_argument(
        "--scheme",
        default=None,
        help="Filter embedding listing to one scheme_id",
    )
    p.add_argument(
        "--raw-dense",
        action="store_true",
        help="Also show unfiltered dense ranking for each query (debug)",
    )
    p.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Write embedding preview JSON to this path",
    )
    p.add_argument(
        "--full-vectors",
        action="store_true",
        help="With --export, include full embedding arrays (large)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    show_emb = not args.retrieval_only
    show_ret = not args.embeddings_only

    rows: list[dict[str, Any]] = []
    if show_emb or args.export or args.raw_dense:
        rows = load_store_rows(scheme_id=args.scheme)
        if show_emb:
            print_embeddings_overview(rows)
            if rows and not args.scheme:
                print_pairwise_same_fact(rows, "expense_ratio")
                print_pairwise_same_fact(rows, "min_sip")

    if args.export:
        if not rows:
            rows = load_store_rows(scheme_id=args.scheme)
        export_preview(rows, args.export, full_vectors=args.full_vectors)

    if show_ret:
        queries = args.query if args.query else list(EXAMPLE_QUERIES)
        if args.raw_dense:
            if not rows:
                rows = load_store_rows(scheme_id=args.scheme)
            for q in queries:
                print_query_vs_corpus(q, rows)
        print_retrieval_examples(queries)

    print("\nFacts-only. No investment advice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

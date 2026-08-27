# Mutual Fund FAQ Assistant

**Facts-only. No investment advice.**

Lightweight RAG assistant over five HDFC mutual fund scheme pages on Groww. Answers are source-backed; advisory questions are refused. The sole LLM provider is **Groq**.

## Docs

| Doc | Purpose |
| --- | --- |
| [`Docs/problemStatement.md`](Docs/problemStatement.md) | Product goals |
| [`Docs/Architecture.md`](Docs/Architecture.md) | Canonical design (minimum bar) |
| [`Docs/implementation-plan.md`](Docs/implementation-plan.md) | Build order |
| [`Docs/edge-case.md`](Docs/edge-case.md) | Edge cases |
| [`Docs/eval.md`](Docs/eval.md) | Evaluation |

## Status

- **Phase 0:** layout, Groww scheme registry, settings, domain allowlist  
- **Phase 1:** offline corpus — Fetch → Parse → Chunk → Embed → Chroma (`data/index/`)  
- **Phase 2:** Retriever — metadata-first dense search  
- **Phase 3:** Groq Generator + Response Validator (`openai/gpt-oss-120b` primary, `openai/gpt-oss-20b` retry)  
- **Phase 4:** Query Classifier, PII guard, Refusal Handler, Groq free-tier budget  
- **Phase 5:** Chat API — `GET /health`, `POST /chat`, `GET /schemes`  
- **Phase 6:** Chat screen — React + Vite + Tailwind under [`frontend/`](frontend/README.md)  
- **Phase 7:** Daily corpus refresh — GitHub Actions runs the offline ingestion path at 10:00 IST and opens a review PR ([`.github/workflows/daily-ingest.yml`](.github/workflows/daily-ingest.yml))

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # then set GROQ_API_KEY=
```

## Quick checks

```bash
# Settings + five schemes load
python -c "from src.config import get_settings, load_schemes; s=get_settings(); d=load_schemes(); print(len(d['schemes']), s.groq_model, s.disclaimer)"

# Document Fetcher — save Groww HTML to data/raw/
python scripts/ingest.py --fetch-only

# Parser & Normalizer — raw HTML → data/processed/
python scripts/ingest.py --parse-only

# Chunker — processed JSON → fact-atomic chunks (~31)
python scripts/ingest.py --chunk-only

# Embedding Service + Vector Store — chunks → Chroma under data/index/
python scripts/ingest.py --index-only

# Full corpus rebuild (fetch → parse → chunk → index) — default
python scripts/ingest.py
# or: python scripts/ingest.py --full

# Verify a refreshed corpus before publishing it (the daily workflow's gate)
python scripts/verify_corpus.py

# Retriever smoke (Phase 2) — requires indexed corpus
python -c "from src.retrieval import Retriever; r=Retriever().retrieve('Expense ratio of HDFC Large Cap?'); print(r.status, r.winner.fact_key if r.winner else r.message)"

# Inspect embeddings + example retrieval
python scripts/inspect_retrieval.py
python scripts/inspect_retrieval.py --query "expense ratio Mid Cap" --raw-dense
python scripts/inspect_retrieval.py --export data/processed/embedding_preview.json

# Groq connectivity check (key + both models)
python scripts/check_groq.py

# Ask end to end (Phase 4): classify -> refuse | retrieve -> Groq -> validate
python scripts/ask.py "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"
python scripts/ask.py            # interactive loop

# Manual test pass over factual / performance / refusal / PII cases
python scripts/manual_test.py
python scripts/manual_test.py --group advisory --pause

# Chat API (Phase 5)
uvicorn src.api.main:app --reload --port 8000
# GET  http://localhost:8000/health   index vectors + Groq readiness
# GET  http://localhost:8000/schemes  the five covered schemes
# GET  http://localhost:8000/docs     interactive API docs
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d "{\"message\": \"What is the expense ratio of HDFC Large Cap Fund Direct Growth?\"}"

# Chat screen (Phase 6) — keep the API running in another terminal
cd frontend
npm install
npm run dev   # http://localhost:5173
```

## Schemes (corpus)

See `src/config/schemes.yaml` — five HDFC Direct Growth pages on `groww.in`. Refusal educational link: https://groww.in/p/mutual-funds

## Disclaimer

Facts-only. No investment advice.

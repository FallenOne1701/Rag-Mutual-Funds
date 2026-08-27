# Implementation Plan — Mutual Fund FAQ Assistant

**Facts-only. No investment advice.**

This is the step-by-step build guide for the assistant described in [`Architecture.md`](./Architecture.md). Architecture is *what* we must deliver; this plan is *in what order*.

**Related:** [Architecture](./Architecture.md) · [Problem Statement](./problemStatement.md)

---

## Plain-English picture

We are building a **facts-only chat assistant** for a handful of HDFC mutual fund schemes. It does **not** invent answers from memory. It:

1. **Reads** official Groww scheme pages ahead of time (our source material).  
2. **Looks up** the most relevant snippets when someone asks a question.  
3. **Writes** a short answer from those snippets only.  
4. **Checks** every reply (length, source link, no advice).  
5. **Refuses** anything that sounds like investment advice or fund comparisons.

That look-up-then-answer pattern is called **RAG** (Retrieval-Augmented Generation). In everyday terms: *find the fact first, then phrase the answer*.

### LLM we use: Groq

This project’s **only** large language model provider is **[Groq](https://groq.com)** (official `groq` Python SDK + `GROQ_API_KEY`).

| Job | Who does it | Default Groq model |
| --- | --- | --- |
| Write the short factual answer | Groq | `openai/gpt-oss-120b` |
| Help classify fuzzy questions (optional) | Groq | `openai/gpt-oss-20b` |
| Fast retry if a reply fails quality checks | Groq | `openai/gpt-oss-20b` |
| Turn text into search vectors (embeddings) | **Local** model — not Groq | e.g. `bge-small-en` |

Do **not** wire OpenAI, Anthropic, or other LLM APIs into this build unless Architecture is revised. Secrets live in `.env` (`GROQ_API_KEY`, optional `GROQ_MODEL` / `GROQ_MODEL_FAST`).

Two big halves of the system:

| Half | Friendly name | What it does |
| --- | --- | --- |
| Offline | **Corpus build** | Download Groww pages, clean them, store searchable snippets |
| Online | **Question answering** | Chat UI → decide if we can answer → look up → **Groq writes** → check → show |

---

## What “done” looks like (must-haves)

| We want… | You’ll know it’s working when… |
| --- | --- |
| A trustworthy knowledge base | All **5 Groww scheme pages** are loaded and searchable |
| Honest answers | Every factual reply has **one Groww link** and a **“Last updated from sources”** line |
| Short replies | Answers are **at most 3 sentences** |
| No advice | “Should I invest?” / “Which is better?” get a **polite refusal** + Groww learning link |
| A simple chat screen | Disclaimer always visible; **3 example questions** ready to click |
| Privacy | No login; we never keep PAN, Aadhaar, phone, email, OTP |

**Hard rules (from Architecture):** sources = Groww only; refusal link = [Groww mutual funds overview](https://groww.in/p/mutual-funds); **LLM = Groq only** (see above); chat backend separate from the web page (not a Streamlit-only app).

---

## Roadmap at a glance

| Step | Friendly name | You can demo… |
| --- | --- | --- |
| **0** | Set up the project | Empty folders, keys, and the list of 5 funds |
| **1** | Build the knowledge base (corpus) | “We ingested 5 Groww pages” |
| **2** | Find the right facts (retrieval) | “Ask expense ratio → correct fund snippet” |
| **3** | Write & check answers (Groq + RAG reply) | Short sourced answers from Groq that pass quality checks |
| **4** | Spot advice & refuse safely | Advisory questions never get a fund tip |
| **5** | Open the chat doorway (API) | Send a message, get a structured reply |
| **6** | Ship the chat screen (UI) | Full click-and-ask experience |
| **7** | Test, polish, document, schedule | README + checklist green, and a nightly corpus refresh |

Finish each step’s **“Done when”** list before moving on.

---

## Step 0 — Set up the project

**Goal:** Create a clean home for the app so later steps drop into place.

**Do this**

1. Create the main folders for: downloading pages, looking up facts, writing answers, the chat API, settings, the web page, one-click rebuild scripts, tests, and stored data (raw pages / cleaned text / search index).  
2. Write a **fund list** with the five Groww URLs plus the Groww educational link used in refusals.  
3. Centralize settings (model names, how many snippets to fetch, temperature, allowed websites).  
4. Prepare a secrets template with **`GROQ_API_KEY`** (required) and optional Groq model overrides — never commit real keys.  
5. Install the library list including the official **`groq`** SDK, plus web API, local text-similarity model, local search store, HTML reading, and tests.  
6. Allow **only** `groww.in` as a source and citation domain.

**Done when**

- [x] Folder layout matches the Architecture project structure  
- [x] All five schemes appear in the fund list  
- [x] The app can read settings from `.env` without secrets in git  

---

## Step 1 — Build the knowledge base (corpus)

**Goal:** Turn Groww scheme pages into a searchable library. This is the **offline** half of RAG.

**Do this**

1. **Document Fetcher** — download each Groww page and save the raw HTML. ✅ (`src/ingestion/fetcher.py`, `python scripts/ingest.py --fetch-only`)  
2. **Parser & Normalizer** — pull out useful facts (expense ratio, exit load, min SIP, riskometer, benchmark, lock-in) and clean the text. ✅ (`src/ingestion/parser.py`, `python scripts/ingest.py --parse-only`)  
3. **Chunker** — turn each processed scheme document into retrieval snippets. Prefer **one chunk per parser `sections[]` entry** (fact-atomic). Do **not** re-split the already-short `normalized_text` with a 400–800 token window. See **Chunking strategy** below. ✅ (`src/ingestion/chunker.py`, `python scripts/ingest.py --chunk-only`)  
4. **Embedding Service** — convert snippets into vectors so similar questions can find them later (same model at build time and ask time). ✅ (`src/retrieval/embedder.py`, local `BAAI/bge-small-en-v1.5`)  
5. **Vector Store** — save snippets + vectors into the local index; skip duplicates when we re-run. ✅ (`src/ingestion/indexer.py`, Chroma under `data/index/`, upsert by `chunk_id`)  
6. One command to **rebuild the whole corpus**. ✅ (`python scripts/ingest.py` / `--full`)  
7. Keep a human-readable summary (how many snippets per fund, dates, errors). ✅ (`data/ingest_report.json`, plus `fetch_report` / `parse_report` / `chunk_report` / `index_report`)

### Chunking strategy (grounded in `data/processed/`)

Parser output already isolates FAQ facts. Measured on the current five files (2026-08-25 ingest):

| Scheme | Sections | Words per section (min–max) | `normalized_text` words | Notes |
| --- | --- | ---: | ---: | --- |
| Mid Cap | 6 | 13–23 | ~154 | `lock_in` missing (expected) |
| Small Cap | 6 | 13–24 | ~156 | `lock_in` missing |
| Gold FoF | 6 | 16–29 | ~175 | `lock_in` missing |
| Large Cap | 6 | 13–23 | ~152 | `lock_in` missing |
| ELSS Tax Saver | 7 | 12–31 | ~180 | includes `lock_in` = 3 years |

**Implication:** Architecture’s generic **400–800 token / 50–100 overlap** page splitter was sized for raw Groww HTML. After Phase 1.2, each section is already a single fact (~12–31 words). Sliding-window chunking would only merge or duplicate facts. This plan **exceeds** that size baseline with **fact-atomic chunks** (allowed by Architecture) while keeping the required metadata contract.

**Input:** `data/processed/{scheme_id}.json` (not raw HTML).

**Primary rule — one section → one chunk**

1. Read `sections[]`. Each item has `page_or_section`, `fact_key`, and `text`.  
2. Emit **exactly one chunk** whose body is `section.text`.  
3. **Skip** facts listed in `missing_facts` / null in `facts` — never invent a lock-in chunk for Mid/Small/Large/Gold.  
4. Do **not** also index the full `normalized_text` as a separate mega-chunk (it repeats every section and harms retrieval precision).  
5. Optional later: if a future section exceeds ~400 tokens, split that section only (overlap 50–100). Not needed for today’s corpus.

**Expected chunk inventory (v1)**

| `fact_key` | Typical `page_or_section` | Present on |
| --- | --- | --- |
| `expense_ratio` | Expense Ratio | all 5 |
| `exit_load` | Exit Load | all 5 |
| `min_sip` | Minimum SIP | all 5 |
| `riskometer` | Riskometer | all 5 |
| `benchmark` | Benchmark | all 5 |
| `lock_in` | Lock-in | ELSS only |
| `investment_objective` | Investment Objective | all 5 |

Rough total: **~31 chunks** (4×6 + 1×7), not hundreds of overlapping windows.

**Required chunk metadata** (copy from the processed document + section):

```json
{
  "scheme_id": "hdfc-elss-tax-saver-fund-direct-plan-growth",
  "scheme_name": "HDFC ELSS Tax Saver Fund Direct Plan Growth",
  "category": "ELSS",
  "amc": "HDFC Mutual Fund",
  "document_type": "groww_scheme_page",
  "source_url": "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
  "source_domain": "groww.in",
  "page_or_section": "Expense Ratio",
  "fact_key": "expense_ratio",
  "content_hash": "sha256:…",
  "document_date": "2026-08-24",
  "ingested_at": "2026-08-25T12:05:21+00:00"
}
```

- `content_hash` / `document_date` / `ingested_at` / `source_url` come from the processed JSON (footer + citation stay source-backed).  
- `fact_key` is an extra retrieval aid (filter “expense ratio” questions); still one Groww `source_url` per chunk.  
- Deduplicate on re-ingest by `(scheme_id, fact_key)` or chunk `content_hash` of `section.text`.

**Chunker settings (v1 defaults)**

| Parameter | Value | Why |
| --- | --- | --- |
| Unit | 1 processed `sections[]` row | Matches FAQ asks; avoids mixing Mid Cap vs Large Cap numbers |
| Target size | as-is (~12–31 words) | Already under Architecture’s 400–800 ceiling |
| Overlap | 0 | No adjacent prose to bridge |
| Split fallback | only if a section &gt; ~400 tokens | Future-proof; unused today |
| Drop | empty / missing facts | KB-03 — report gaps, don’t fabricate |

**Done when**

- [x] All five schemes are loaded (no empty silent failures) — *fetcher + parser + chunker + indexer report ok/error per scheme; Chroma holds ~31 vectors*  
- [x] Every snippet points at its Groww page URL (`source_url` from processed JSON) — *Chunker copies `source_url` onto each chunk; Indexer stores it in metadata*  
- [x] Chunker emits ~one chunk per non-missing `sections[]` row (~31 today); no duplicate `normalized_text` mega-chunks  
- [x] Re-running the build does not create messy duplicates (`scheme_id` + `fact_key` / content hash; Chroma upsert by `chunk_id`)  
- [x] You have a short ingest report you can show someone — *`data/ingest_report.json` + stage reports (`fetch` / `parse` / `chunk` / `index`)*  

---

## Step 2 — Find the right facts (retrieval)

**Goal:** When the user asks something factual, pull the best snippets from the knowledge base.

**Do this**

1. Turn the user’s question into a vector with the **same** embedding model used in Step 1 (`BAAI/bge-small-en-v1.5`, query instruction prefix). ✅ (`src/retrieval/embedder.py`)  
2. Detect **scheme** (and when possible **fact_key**) from the question with keyword / alias rules against `schemes.yaml` + known fact phrases. ✅ (`src/retrieval/query_parser.py`)  
3. Search the Vector Store with **metadata filters first**, then dense ranking inside that subset (see strategy below). ✅ (`src/retrieval/retriever.py`)  
4. Take a small top list (`k = 3` when scheme is known; `k = 5` only if unfiltered). ✅ (`retrieval_top_k=3`)  
5. Pick **one** winning snippet whose Groww URL becomes the citation. ✅  
6. If nothing is similar enough — or the scheme is ambiguous — say we couldn’t verify it and link the fund’s Groww page when we know which fund they meant (never invent a fund). ✅ (`status`: `low_confidence` / `no_scheme` / `ambiguous_scheme`)  

### Retrieval strategy (grounded in `data/processed/`)

Measured on the Phase-1 corpus (31 fact-atomic chunks, 2026-08-25):

| Property | Observation | Retrieval implication |
| --- | --- | --- |
| Size | 31 chunks / 5 schemes (~6–7 each) | Tiny index — metadata filters beat heavy rerankers |
| Length | 12–31 words per chunk | Dense vectors are fine; no need for BM25 over long prose |
| Template overlap | Same `fact_key` across schemes shares ~78–86% tokens (e.g. Mid vs Large expense ratio) | **Scheme must be resolved before trusting top-1** |
| Near-identical values | `min_sip` = ₹100 on 4/5 funds; riskometer “Very High” on 4/5 | Unfiltered dense search often returns the *right fact type, wrong fund* |
| Probe (live Chroma) | Full “expense ratio of HDFC Large Cap?” → correct #1; short “expense ratio Mid Cap” → Mid Cap *exit_load* ranked above Mid Cap *expense_ratio*; “What is the benchmark?” → arbitrary scheme | Need scheme filter + fact_key preference; refuse ambiguous no-scheme fact asks |

**Recommended approach for v1: metadata-first dense retrieval** (exceeds Architecture’s “optional filter” by making scheme filter the default when detectable).

```
Query
  → detect scheme_id / category aliases (rules over schemes.yaml)
  → detect fact_key (expense ratio, exit load, min SIP, riskometer,
                     benchmark, lock-in, objective, …)
  → embed query (BGE + query instruction)
  → Chroma query:
        if scheme_id known → where={scheme_id} , n_results=3
        elif fact_key known only → do NOT answer a random fund;
                                   ask/clarify or low-confidence fallback
        else → dense top-5, then require clear scheme signal in hit text
  → optional soft boost: prefer hits whose fact_key matches detection
  → winner = top remaining hit if similarity ≥ threshold
  → citation = winner.metadata.source_url (never model-invented)
```

**Why not pure dense / cross-encoder for v1**

- Pure dense fails on short queries and near-duplicate SIP/exit-load templates (probe above).  
- Cross-encoder rerank is optional in Architecture and adds latency for a 31-vector corpus; **skip in v1**. Revisit only if scheme detection + dense still misses eval questions.  
- Hybrid BM25+dense is unnecessary: chunks already name the scheme and fact in the first sentence.

**Scheme & fact detection (rules, no Groq)**

| Signal | Examples that map | Notes |
| --- | --- | --- |
| Scheme aliases | “large cap”, “mid cap”, “small cap”, “gold”, “elss”, “tax saver” + optional “HDFC” | Prefer unique aliases; “HDFC” alone is **not** enough (all five are HDFC) |
| `scheme_id` | Match against registry `scheme_name` / slug tokens | Single match → hard filter; 0 or 2+ → ambiguous |
| `fact_key` | expense ratio / TER; exit load; SIP / minimum investment; risk / riskometer; benchmark; lock-in; objective / invests in | Soft preference inside filtered results |

**Similarity & fallbacks**

| Case | Action |
| --- | --- |
| Scheme known + good hit (`cosine distance` ≲ 0.40, or `1 - distance` ≳ 0.60 on this index) | Return top-1 chunk as context + citation |
| Scheme known + weak hit | “Couldn’t find verified info…” + that scheme’s Groww `url` from registry |
| No scheme / ambiguous scheme | Do **not** cite another fund’s number; polite clarify or Groww overview / ask which of the five |
| `lock_in` asked for non-ELSS | After scheme filter, empty/weak → say not shown on that Groww page (don’t invent) |

**Settings defaults (align `settings.py`)**

| Parameter | v1 value | Why |
| --- | --- | --- |
| `retrieval_top_k` | 3 (scheme-filtered) / 5 (rare unfiltered) | At most ~7 chunks per scheme |
| `retrieval_rerank_top_n` | unused (no cross-encoder) | Keep setting for later |
| `retrieval_min_similarity` | ~0.55–0.60 (`1 - chroma_cosine_distance`) | Probe: good hits ~0.67–0.83; ambiguous ~0.57–0.60 |
| Embedding | same as ingest + BGE query prefix | Already in Embedding Service |

**Fixed retrieval quiz seeds (for Step 2 tests / later eval)**

| Question | Expected `scheme_id` | Expected `fact_key` |
| --- | --- | --- |
| Expense ratio of HDFC Large Cap? | `hdfc-large-cap-fund-direct-growth` | `expense_ratio` |
| Mid Cap minimum SIP | `hdfc-mid-cap-fund-direct-growth` | `min_sip` |
| ELSS lock-in | `hdfc-elss-tax-saver-fund-direct-plan-growth` | `lock_in` |
| Exit load of the gold FoF | `hdfc-gold-etf-fund-of-fund-direct-plan-growth` | `exit_load` |
| Small Cap benchmark | `hdfc-small-cap-fund-direct-growth` | `benchmark` |
| What is the benchmark? *(no fund)* | *(none — ambiguous)* | `benchmark` |

**Done when**

- [x] Sample questions like “expense ratio of HDFC Large Cap?” land on the right fund  
- [x] Short queries that name a fund (“expense ratio Mid Cap”) still prefer the correct `fact_key` after scheme filter  
- [x] Ambiguous no-fund questions do not return another scheme’s number  
- [x] The citation always comes from stored metadata — never invented by the model  
- [x] Fixed “question → expected scheme / fact_key” examples above are covered by automated tests  

---

## Step 3 — Write & check answers (Groq + RAG reply)


**Goal:** Use **Groq as the LLM** to phrase a short answer **only** from retrieved snippets, then enforce the response rules.

**Do this**

1. Add a small shared **Groq client** (`groq` SDK + `GROQ_API_KEY`) used by the Generator and optional classifier. ✅ (`src/generation/groq_client.py`)  
2. **Generator (Groq)** — primary model `openai/gpt-oss-120b`: use context only, max 3 sentences, no advice, no comparisons. Keep answers calm and literal (low creativity / low temperature). ✅ (`src/generation/generator.py`)  
3. **Response Validator** — automatically reject replies that are too long, missing a Groww citation, missing the last-updated footer, or sounding like advice. ✅ (`src/generation/validator.py`)  
4. If a reply fails the check: retry once on Groq with `openai/gpt-oss-20b` and stricter instructions; if it still fails, fall back to a safe Groww page link (still no other LLM vendor). ✅  
5. For **performance / returns** questions: do not calculate returns — one short sentence + Groww scheme page link only (skip Groq generation). ✅  

**What a good reply contains**

- A short answer (`type: answer`) **or** a polite refusal (`type: refusal`)  
- Exactly one citation (URL + title)  
- Footer: `Last updated from sources: YYYY-MM-DD`  
- Disclaimer: `Facts-only. No investment advice.`

**Done when**

- [x] Bad drafts (no link, too long, advice wording) are blocked  
- [x] Validated answers stay facts-only  
- [x] Validator checks are covered by automated tests  

---

## Step 4 — Spot advice & refuse safely

**Goal:** Decide *before* looking anything up whether we should answer at all.

**Do this**

1. Strip or reject personal data (PAN, Aadhaar, email, phone, OTP) and overly long messages. ✅ (`src/generation/pii.py`; long messages truncated to `max_message_chars`)  
2. **Query Classifier** — mix simple keyword rules with a small Groq check for fuzzy cases. ✅ (`src/generation/classifier.py`)  
3. Label the ask as one of: factual · advisory · comparative · performance · personal/account · out of scope. ✅  
4. **Refusal Handler** — polite message, remind “facts only,” link to Groww’s mutual funds overview. ✅ (`src/generation/refusal.py`)  
5. Never send personal data to Groq. ✅ (PII rule runs before every other check)

**Phrases that should refuse quickly:** should I, recommend, better fund, best fund, worth investing, buy or sell, predict, returns if I, compare.

**Stay inside the Groq free tier**

`openai/gpt-oss-120b` allows 30 requests/min, 1,000 requests/day, 8,000 tokens/min, 200,000 tokens/day. Tokens per minute binds first — at roughly 600 tokens a call that is about 12 answers a minute. So:

6. Refuse **before** any Groq call. Advisory, comparative, performance, PII and out-of-scope must be settled by keyword rules so a refusal costs zero tokens. ✅  
7. Budget **one Groq call per question**. Use the optional Groq classify only when the rules are genuinely undecided, and never alongside a validator retry on the same request. ✅ (Groq classify runs only for in-domain messages that name no stored fact)  
8. Track usage per minute and per day in the client; when the budget is spent, return the Groww scheme-page fallback instead of calling Groq. ✅ (`src/generation/budget.py`; `GroqBudgetError` triggers the existing fallback)  
9. On 429, keep the existing single backoff retry, then fall back — do not queue requests. ✅

**Gaps from the Step 3 manual pass — all closed:**

- “Should I invest in HDFC Large Cap Fund?” is now classified advisory and refused before retrieval.  
- PAN / email / OTP / folio input is blocked by the PII rule ahead of every other check.  
- Hypothetical-growth wording (“if I had invested … what would it be worth”) now hits the performance bypass.  
- Comparative wording is caught on its own, including when only one fund is named.

**Done when**

- [x] Advice and “which is better?” never reach the answer writer  
- [x] Personal data never reaches Groq  
- [x] Refusals and performance questions make zero Groq calls  
- [x] Per-minute / per-day token budget is enforced with a Groww-link fallback  
- [x] Classifier / refusal behavior has automated tests  

**Verified by** `python scripts/manual_test.py` — 16/16 cases pass, 5 Groq calls for 16 questions.

---

## Step 5 — Open the chat doorway (API)

**Goal:** One simple backend the web page can call.

**Do this**

1. Stand up the **Chat Endpoint** (health check + chat + optional list of funds). ✅ (`GET /health`, `POST /chat`, `GET /schemes`)  
2. Wire the full journey: classify → refuse **or** look up → write → validate. ✅ (`src/api/routes/chat.py` calls `answer_question`)  
3. Accept a message; return the standard answer/refusal package. ✅ (`src/api/schemas.py`)  
4. Handle overload gently (shorten huge inputs; if Groq is busy, retry once then fall back to a Groww link). ✅ (messages over `max_message_chars` are truncated, over 4,000 chars rejected as 422; `/chat` is rate limited per client; any pipeline error degrades to the educational link rather than a 500)

**What happens for one question**

1. User asks in the chat screen  
2. We classify the intent  
3. Factual → find snippets → write → validate  
4. Advice / comparison / personal data / off-topic → refuse with Groww learning link  
5. Screen shows the text, source link, footer, and disclaimer  

**Done when**

- [x] You can send a factual question and an advice question and both look correct  
- [x] Health check confirms the service (and index) is up  

**Try it**

```bash
uvicorn src.api.main:app --reload --port 8000
# GET  http://localhost:8000/health   -> index vectors + Groq readiness
# GET  http://localhost:8000/schemes  -> the five covered schemes
# POST http://localhost:8000/chat     -> { "message": "..." }
# Interactive docs: http://localhost:8000/docs
```

---

## Step 6 — Ship the chat screen (UI)

**Goal:** A calm, minimal chat page anyone can use.

**Do this**

1. Build a simple single-page chat (plain HTML/JS or React). ✅ (React 18 + Vite + TypeScript + Tailwind under `frontend/`, styled from the "Fiscal Clarity" Google Stitch design)  
2. Keep the disclaimer visible: **Facts-only. No investment advice.** ✅ (header badge + amber strip above the conversation + `disclaimer` line inside every reply card)  
3. Add a short welcome and **three clickable example questions**. ✅ (`src/components/WelcomePanel.tsx`, plus a "Covered schemes" panel from `GET /schemes`)  
4. Show history with answer text, clickable Groww source (new tab), and last-updated footer. ✅ (`AssistantCard` renders `text` / `citation` / `footer`; refusals get a neutral card, an intent label from `meta.intent`, and the Groww educational link)  
5. Call the chat endpoint on send. ✅ (`src/api.ts`; `/api/*` proxied to port 8000 in dev, `VITE_API_BASE_URL` for other deployments)  
6. No login, no personal-data cookies, no exporting chats with user identifiers. ✅ (history is in-memory only; the only stored value is the theme preference; composer warns never to share PAN / Aadhaar / OTP / phone / email)

**Done when**

- [x] Works on desktop and phone-sized screens — *single fluid column, sticky composer with safe-area padding, 44px tap targets*  
- [x] Advice questions show a refusal + Groww learning link — *“Should I invest in HDFC Small Cap Fund?” → refusal card citing https://groww.in/p/mutual-funds*  
- [x] Factual questions show a Groww scheme citation + last-updated line — *“What is the expense ratio of HDFC Large Cap Fund?” → 1.02% with the scheme page and `Last updated from sources: 2026-08-24`*  

**How to run locally**

```bash
# Terminal 1 — chat API
uvicorn src.api.main:app --reload --port 8000

# Terminal 2 — chat screen
cd frontend && npm install && npm run dev   # http://localhost:5173
```

See [`frontend/README.md`](../frontend/README.md) for the build / deploy variant.

---

## Step 7 — Test, polish, document

**Goal:** Make the demo trustworthy and easy for someone else to run.

**Do this**

1. Automated tests for classifier, validator, and retrieval examples.  
2. A small fixed quiz set: about **20 factual** questions and **10 advice** questions that must always refuse.  
3. Optional simple stats: how often we find a snippet, how often we refuse, how often validation fails, how long replies take.  
4. **Daily corpus refresh** — schedule the offline ingestion path on GitHub Actions (see below).  
5. README: how to set up, which funds, how RAG works here, known limits, disclaimer.  
6. Walk the manual checklist below once end-to-end.

### Daily corpus refresh (GitHub Actions scheduler)

**Goal:** the footer date stays honest. Today the corpus is whatever we last ingested by hand; a nightly job re-runs the **offline ingestion path** so `document_date` / `ingested_at` — and therefore the `Last updated from sources:` line — reflect the current Groww scheme pages.

**Scope:** offline only. The scheduler runs **Document Fetcher → Parser & Normalizer → Chunker → Embedding Service → Vector Store** — exactly `python scripts/ingest.py --full`, the same command a developer runs locally. The **online query path** is untouched: no Groq calls, no classifier, no validator, no API deploy in this job.

**Schedule**

| Setting | Value | Why |
| --- | --- | --- |
| Trigger | `schedule: cron` + `workflow_dispatch` | Daily automatically, manually re-runnable when a fetch fails |
| Cron | `30 4 * * *` UTC = **10:00 IST** | A failed refresh lands during working hours, so it gets noticed and re-run the same day. The facts we ingest (expense ratio, exit load, min SIP, riskometer, benchmark, lock-in, objective) do not change intraday — NAV does, and we deliberately never ingest it — so the slot is chosen for human attention, not freshness. GitHub schedules are best-effort and drift under load. |
| Concurrency | one run at a time, no cancel | Two ingests writing `data/index/` would corrupt Chroma |
| Timeout | 20 minutes | Five pages plus a local embedding model; anything longer is a hang |

**Workflow** — [`.github/workflows/daily-ingest.yml`](../.github/workflows/daily-ingest.yml) ✅

1. Check out the repo.  
2. Set up Python 3.11 and `pip install -r requirements.txt`, caching pip **and** `~/.cache/huggingface` so `BAAI/bge-small-en-v1.5` is not re-downloaded every day.  
3. The tracked `data/processed/` + `data/index/` come with the checkout, so the run is an **update**, not a cold rebuild — this is what makes `content_hash` dedupe and Chroma upsert-by-`chunk_id` meaningful. `data/raw/` stays untracked and is re-fetched every time.  
4. Run `python scripts/ingest.py --full` (it already exits non-zero if any stage reports a scheme error).  
5. Run `python scripts/verify_corpus.py` — the gate for a run that "succeeded" but is silently wrong (see below).  
6. Upload `data/ingest_report.json` plus the stage reports as artifacts, **always**, so a failed night is diagnosable.  
7. Open / update a pull request with the refreshed corpus.  
8. On failure, keep the previous corpus in place — **a stale-but-verified index beats a half-written one**.

**Verification gate** — [`scripts/verify_corpus.py`](../scripts/verify_corpus.py) ✅

`ingest.py` catches stage errors. This catches the quieter failures — Groww serving a block page, the parser losing a fact, Chroma drifting out of step with the chunks:

| Check | Fails the run when |
| --- | --- |
| All five schemes present | A scheme has no processed document |
| Sections per scheme ≥ 5 | A page returned but did not really parse |
| Core facts present (`expense_ratio`, `exit_load`, `min_sip`, `riskometer`, `benchmark`) | A previously reliable fact vanished |
| `source_url` on `groww.in` | Corpus allowlist violated |
| Chroma vectors == chunk count | Index and chunks disagree — retrieval would answer from unreviewed data |
| Stages `fetch` / `parse` / `chunk` / `index` all ran | Someone shipped a partial refresh |

It also **warns** (without failing) when a `document_date` is older than 30 days, and prints a Markdown table of every scheme's current facts — that table becomes the job summary and the pull request body, so the reviewer sees exactly which numbers moved.

**No Groq secret is needed.** Ingestion never calls the LLM, so the job runs without `GROQ_API_KEY`. Do not add it to the workflow.

**Where the refreshed corpus goes** — decide before writing the workflow

| Option | How | Trade-off |
| --- | --- | --- |
| **A. Commit `data/processed/` + `data/index/`** | Bot commit on a `corpus-refresh` branch or straight to main | Simplest; needs the `data/` entries removed from `.gitignore` and grows repo history with a binary `chroma.sqlite3` every day |
| **B. Upload as a workflow artifact / release asset** | `actions/upload-artifact`, cache restore on the next run | Keeps git clean; the serving host must pull the artifact before it sees new data |
| **C. Push to the host running the API** | Rsync / object storage / container rebuild | Correct for a real deployment; out of scope while the API runs locally |

**Chosen for v1: Option A on a pull request.** ✅ The workflow commits `data/processed/` + `data/index/` to a `corpus-refresh` branch and opens (or comments on) a pull request, so a human sees the diff — a changed expense ratio should be reviewable — and the fallback to the previous corpus is simply a merge that never happened. `.gitignore` now tracks those two folders; `data/raw/` stays out of git. Revisit if the daily `chroma.sqlite3` blob makes the repo unwieldy.

**Guardrails the scheduler must not break**

- Groww only. The job fetches the URLs already in `src/config/schemes.yaml` — the scheduler is not a place to widen the corpus.  
- Politeness: keep `fetch_delay_seconds` between requests and identify the crawler honestly in the User-Agent; a nightly job that hammers Groww gets blocked.  
- Never fabricate freshness: if a page fails, that scheme keeps its **old** `document_date`. Do not stamp today's date onto data we could not re-fetch.  
- `missing_facts` stays a gap, not an invention — a nightly run that suddenly finds a lock-in for a non-ELSS fund is a parser bug, not new data.  
- Report drift: if a scheme's chunk count or a fact value changes, surface it in `data/ingest_report.json` so the reviewer can see *what* moved.

**Done when**

- [x] `.github/workflows/daily-ingest.yml` runs on schedule (10:00 IST) and on manual dispatch  
- [x] The run needs no Groq key and makes zero LLM calls — ingestion never touches the Generator or Classifier  
- [x] A verification gate fails the job when a scheme drops out, a core fact vanishes, or Chroma disagrees with the chunks — *`scripts/verify_corpus.py`; locally it correctly flags an index-only run as a partial refresh*  
- [ ] A scheduled run on GitHub refreshes all five schemes and leaves ~31 chunks (no duplicates, no dropped schemes) — *needs a remote; run `workflow_dispatch` once after pushing*  
- [ ] The `Last updated from sources:` footer in the UI reflects the latest successful ingest  

**Manual demo checklist**

- [ ] Factual answer is ≤ 3 sentences  
- [ ] Exactly one Groww citation  
- [ ] Footer date matches the source date we stored  
- [ ] Advice question → refusal (not a tip)  
- [ ] Returns question → Groww page link only (no calculated returns)  
- [ ] Disclaimer visible on the screen  

**Done when**

- [ ] Rough targets: ≥ 90% factual accuracy on the quiz set; ≥ 95% correct refusals; 100% valid citations  
- [ ] README is enough for a cold start demo  
- [ ] The daily ingest workflow has completed at least one green scheduled run  

---

## Suggested week (flexible)

| Focus | Steps |
| --- | --- |
| Day 1 | 0 + 1 — project ready + knowledge base built |
| Day 2 | 2 + 3 — find facts + write/check answers |
| Day 3 | 4 + 5 — refusals + chat API |
| Day 4 | 6 — chat screen |
| Day 5 | 7 — tests, quiz set, README, daily ingest workflow, polish |

Do not open the chat API widely until Step 4 (refusals) is in place.

---

## Not in v1 (later ideas)

- More fund houses beyond these five  
- Fetching Groww live on every question  
- Extra ranking models (nice-to-have in Step 2)  
- Admin dashboard  
- Hindi / voice  

---

## Project finished when…

1. One command rebuilds the **5-scheme Groww knowledge base**, and a nightly GitHub Actions run does it unattended.  
2. Factual questions get short, **source-backed** answers written by **Groq** (RAG done right).  
3. Advice / comparison / personal-data questions get a **polite refusal** with the Groww learning link.  
4. Returns questions never invent performance numbers.  
5. The chat screen shows disclaimer, examples, citation, and footer.  
6. Tests, quiz set, README, and the manual checklist all pass.

---

*Follows [`Architecture.md`](./Architecture.md). If Architecture changes, update this plan to match.*

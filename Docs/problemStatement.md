# Mutual Fund FAQ Assistant — Facts-Only Q&A

> **Disclaimer snippet (must appear in the UI):** "Facts-only. No investment advice."

## 1. Overview

Build a **facts-only FAQ assistant** for mutual fund schemes, using **Groww** as the reference product context. The assistant answers objective, verifiable queries about mutual funds by retrieving information **exclusively from official public sources** — AMC (Asset Management Company) websites, AMFI, and SEBI.

The system must strictly avoid investment advice, opinions, and recommendations. Every response must carry a single, clear source link and respect defined constraints on clarity, accuracy, and compliance.

## 2. Objective

Design and implement a lightweight **Retrieval-Augmented Generation (RAG)** assistant that:

- Answers factual queries about mutual fund schemes.
- Uses a curated corpus of official documents.
- Provides concise, source-backed responses.

The guiding principle: **accuracy over intelligence.**

## 3. Target Users

| User | Need |
| --- | --- |
| Retail investors | Comparing factual attributes of mutual fund schemes |
| Customer support / content teams | Handling repetitive mutual fund queries at scale |

## 4. Scope of Work

### 4.1 Corpus Definition

Select **one AMC** and **3–5 schemes** with category diversity (e.g. large-cap, flexi-cap, ELSS). The reference set given for this project is HDFC, covering mid-cap, small-cap, gold FoF, large-cap, and ELSS:

- [HDFC Mid Cap Fund — Direct Growth](https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth)
- [HDFC Small Cap Fund — Direct Growth](https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth)
- [HDFC Gold ETF Fund of Fund — Direct Plan Growth](https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth)
- [HDFC Large Cap Fund — Direct Growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth)
- [HDFC ELSS Tax Saver Fund — Direct Plan Growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth)

### 4.2 FAQ Assistant Requirements

**In-scope question types (factual):**

- Expense ratio of a scheme
- Exit load details
- Minimum SIP amount
- ELSS lock-in period
- Riskometer classification
- Benchmark index
- Process to download statements or capital gains reports

**Hard response format rules:**

1. Maximum **3 sentences** per response.
2. Exactly **one citation link** per response.
3. A footer on every response: `Last updated from sources: <date>`

### 4.3 Refusal Handling

The assistant must refuse non-factual or advisory queries, e.g. "Should I invest in this fund?" or "Which fund is better?".

A refusal must:

- Be polite and clearly worded.
- Reinforce the facts-only limitation.
- Provide a relevant educational link (e.g. an AMFI or SEBI resource).

### 4.4 User Interface (Minimal)

- A welcome message.
- Three example questions.
- A visible disclaimer: "Facts-only. No investment advice."

## 5. Constraints

### Data and Sources

- Use **only** official public sources: AMC, AMFI, SEBI.
- Do **not** use third-party blogs or aggregator websites.

### Privacy and Security

Do not collect, store, or process:

- PAN or Aadhaar numbers
- Account numbers
- OTPs
- Email addresses or phone numbers

### Content Restrictions

- No investment advice or recommendations.
- No performance comparisons or return calculations.
- For performance-related queries, link to the official factsheet only.

### Transparency

- Responses must be short, factual, and verifiable.
- Every answer must include a source link and a last-updated date.

## 6. Expected Deliverables

- **README document** covering:
  - Setup instructions
  - Selected AMC and schemes
  - Architecture overview (RAG approach)
  - Known limitations
- **Disclaimer snippet:** "Facts-only. No investment advice."

## 7. Success Criteria

- Accurate retrieval of factual mutual fund information.
- Strict adherence to facts-only responses.
- Consistent inclusion of valid source citations.
- Proper refusal of advisory queries.
- Clean, minimal, and user-friendly interface.

## 8. Summary

Build a trustworthy, transparent, and compliant mutual fund FAQ assistant that prioritizes accuracy over intelligence. Users should receive only verified, source-backed financial information, with no advisory bias or speculative content.

## 9. Open Decisions

These are not specified by the problem statement and need to be settled before or during implementation:

- Language, framework, and hosting for the app and UI.
- Embedding model, vector store, and LLM choice.
- How the corpus is ingested and refreshed, and how the "last updated" date is tracked per document.
- Whether refusal detection is prompt-based, classifier-based, or both.

---

*Source: distilled from `Docs/ProblemStatement.txt`.*

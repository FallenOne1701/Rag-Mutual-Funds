# Frontend — Mutual Fund FAQ Assistant (Step 6)

**Facts-only. No investment advice.**

React 18 + Vite + TypeScript + Tailwind chat screen for the Chat Endpoint. Visual system is the
"Fiscal Clarity" Google Stitch design (deep teal, Inter, tonal surfaces), adapted to the
Architecture response contract: every reply renders one Groww citation, the
`Last updated from sources:` footer, and the disclaimer.

## Run it

```bash
# Terminal 1 — chat API (from the project root)
uvicorn src.api.main:app --reload --port 8000

# Terminal 2 — this app
cd frontend
npm install
npm run dev     # http://localhost:5173
```

`/api/*` is proxied to `http://127.0.0.1:8000` in dev, so the browser stays same-origin. For a
static build served elsewhere, copy `.env.example` to `.env` and point `VITE_API_BASE_URL` at the
API origin (that origin must also appear in `API_CORS_ORIGINS`).

```bash
npm run build     # type-check + production bundle in dist/
npm run preview   # serve the built bundle
```

## What the screen does

- Persistent disclaimer strip; the same disclaimer repeats inside every reply card.
- Empty state with three clickable example questions and the five covered schemes.
- `answer` cards: text, Groww source link (new tab), last-updated footer.
- `refusal` cards: neutral styling, intent label from `meta.intent`, Groww educational link.
- Pending ("Checking sources…"), rate-limit / offline error card with retry, light + dark themes.
- No login, no cookies, no chat export, no personal data stored — history lives in memory only and
  clears on reload or "New chat".

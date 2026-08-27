"""
FastAPI application — the Chat Endpoint (Phase 5).

Routes: GET /health, POST /chat, GET /schemes. The heavy pieces (embedding
model, Chroma collection) load once at startup so the first question is not
slower than the rest.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.deps import get_retriever
from src.api.routes.chat import router as chat_router
from src.api.routes.health import router as health_router
from src.config.settings import get_settings

logger = logging.getLogger(__name__)

_RATE_WINDOW_SECONDS = 60.0
_hits: dict[str, Deque[float]] = defaultdict(deque)
_hits_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    if cfg.api_warmup_on_startup:
        try:
            get_retriever()
            logger.info("Retriever warm — API ready")
        except Exception as exc:  # serve /health so the operator can see why
            logger.error("Retriever warmup failed (is the index built?): %s", exc)
    yield


app = FastAPI(
    title="Mutual Fund FAQ Assistant",
    description="Facts-only. No investment advice. Groq-backed RAG over Groww scheme pages.",
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _over_rate_limit(client: str, limit: int) -> bool:
    now = time.monotonic()
    with _hits_lock:
        bucket = _hits[client]
        while bucket and now - bucket[0] >= _RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
    return False


def reset_rate_limits() -> None:
    """Clear the per-client windows (tests)."""
    with _hits_lock:
        _hits.clear()


@app.middleware("http")
async def rate_limit_chat(request: Request, call_next):
    """Cheap per-client guard on /chat so one caller can't drain the Groq quota."""
    cfg = get_settings()
    limit = cfg.api_rate_limit_per_minute
    if limit and request.url.path == "/chat" and request.method == "POST":
        client = request.client.host if request.client else "unknown"
        if _over_rate_limit(client, limit):
            logger.warning("Rate limit hit for %s", client)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Too many questions — the limit is {limit} per minute. "
                        "Please wait a moment and try again."
                    )
                },
            )
    return await call_next(request)


app.include_router(health_router)
app.include_router(chat_router)

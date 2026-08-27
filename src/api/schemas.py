"""
Request / response models for the Chat Endpoint (Phase 5).

Response shape is the Architecture response contract: type, text, citation,
footer, disclaimer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Generous cap so huge pastes are shortened rather than rejected; the query
# pipeline truncates to settings.max_message_chars before classifying.
MAX_REQUEST_CHARS = 4_000


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_REQUEST_CHARS,
        description="User question about a covered Groww scheme",
        examples=["What is the expense ratio of HDFC Large Cap Fund Direct Growth?"],
    )


class Citation(BaseModel):
    url: str
    title: str


class ChatResponse(BaseModel):
    type: Literal["answer", "refusal"]
    text: str
    citation: Citation
    footer: str
    disclaimer: str
    meta: dict[str, Any] | None = None


class SchemeInfo(BaseModel):
    scheme_id: str
    scheme_name: str
    category: str
    url: str


class SchemesResponse(BaseModel):
    count: int
    schemes: list[SchemeInfo]


class IndexHealth(BaseModel):
    ready: bool
    vectors: int | None = None
    collection: str
    detail: str | None = None


class GroqHealth(BaseModel):
    configured: bool
    model: str
    model_fast: str
    requests_today: int
    tokens_today: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    phase: str
    index: IndexHealth
    groq: GroqHealth
    disclaimer: str

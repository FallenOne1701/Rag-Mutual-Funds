"""
Refusal Handler — polite facts-only refusal + Groww educational link (Phase 4).

Refusals are built locally and cost zero Groq tokens. Wording deliberately
avoids advice vocabulary so the Response Validator passes them unchanged.
"""

from __future__ import annotations

from src.config.settings import Settings
from src.generation.classifier import Classification, Intent
from src.generation.generator import AssistantResponse, package_response, refusal_citation

EDUCATIONAL_URL = "https://groww.in/p/mutual-funds"

REFUSAL_TEXTS: dict[str, str] = {
    "advisory": (
        "I only share published facts from Groww scheme pages, so I can't say "
        "whether a fund fits your goals. You can read about mutual funds on Groww."
    ),
    "comparative": (
        "I don't rank funds or pick between them. I can state a published detail "
        "of a single scheme, such as its expense ratio, exit load, or lock-in period."
    ),
    "performance": (
        "I do not calculate or quote investment returns. "
        "Please check performance figures on the Groww scheme page."
    ),
    "pii_account": (
        "Please don't share personal details such as PAN, Aadhaar, OTP, email, or "
        "phone number. I can't access accounts or folios, and I answer only "
        "published facts about the schemes we cover."
    ),
    "out_of_scope": (
        "I answer factual questions only about the mutual fund schemes we cover on "
        "Groww. Try asking about a scheme's expense ratio, exit load, minimum SIP, "
        "lock-in period, or benchmark."
    ),
}

_DEFAULT_TEXT = REFUSAL_TEXTS["out_of_scope"]


def refusal_text(intent: str) -> str:
    return REFUSAL_TEXTS.get(intent, _DEFAULT_TEXT)


def build_refusal(
    intent: Intent | str,
    *,
    reason: str | None = None,
    settings: Settings | None = None,
) -> AssistantResponse:
    """Build a `type: refusal` package citing the Groww educational link."""
    return package_response(
        resp_type="refusal",
        text=refusal_text(str(intent)),
        citation=refusal_citation(),
        document_date=None,
        settings=settings,
        meta={"intent": str(intent), "refused": True, **({"reason": reason} if reason else {})},
    )


def refuse(
    classification: Classification,
    *,
    settings: Settings | None = None,
) -> AssistantResponse:
    """Refusal for a classifier verdict. PII kinds are recorded, values never are."""
    response = build_refusal(
        classification.intent,
        reason=classification.reason or None,
        settings=settings,
    )
    if classification.pii_kinds and response.meta is not None:
        response.meta["pii_kinds"] = list(classification.pii_kinds)
    return response

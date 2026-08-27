"""Query Classifier + PII guard tests (Phase 4)."""

from __future__ import annotations

import pytest

from src.generation.classifier import Classification, classify, classify_rules, classify_with_groq
from src.generation.pii import detect_pii, redact


class _FakeGroq:
    """Stands in for GroqClient; records whether it was called at all."""

    def __init__(self, reply: str = "factual") -> None:
        self.reply = reply
        self.calls = 0

    def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        from src.generation.groq_client import ChatResult

        return ChatResult(text=self.reply, model="fake")


# --- PII -------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,kind",
    [
        ("My PAN is ABCDE1234F", "pan"),
        ("Aadhaar 1234 5678 9012 please", "aadhaar"),
        ("mail it to dhruv@example.com", "email"),
        ("call me on 9876543210", "phone"),
        ("the OTP is 448213", "otp"),
        ("show my folio balance", "account"),
    ],
)
def test_detect_pii_kinds(message: str, kind: str) -> None:
    assert kind in detect_pii(message).kinds


def test_factual_question_has_no_pii() -> None:
    assert not detect_pii("What is the expense ratio of HDFC Large Cap Fund?").found


def test_redact_masks_values() -> None:
    masked = redact("PAN ABCDE1234F and mail dhruv@example.com")
    assert "ABCDE1234F" not in masked
    assert "dhruv@example.com" not in masked


def test_pii_wins_over_every_other_rule() -> None:
    # Advisory wording plus a PAN must still be labelled PII, never sent to Groq
    result = classify_rules("Should I invest? My PAN is ABCDE1234F")
    assert result is not None
    assert result.intent == "pii_account"
    assert "pan" in result.pii_kinds


# --- intents ---------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Should I invest in HDFC Large Cap Fund?",
        "Is HDFC Mid Cap Fund a good fund for retirement?",
        "Can you recommend a fund for me?",
        "Is it safe to invest in small cap?",
        "Which fund should I pick for tax saving?",
    ],
)
def test_advisory(message: str) -> None:
    assert classify(message, allow_groq=False).intent == "advisory"


@pytest.mark.parametrize(
    "message",
    [
        "Which is better, HDFC Large Cap or HDFC Mid Cap?",
        "Compare HDFC Small Cap with HDFC Mid Cap",
        "HDFC Large Cap vs HDFC ELSS",
        "Rank the HDFC funds by expense ratio",
        "Is HDFC Mid Cap better than HDFC Large Cap?",
    ],
)
def test_comparative(message: str) -> None:
    assert classify(message, allow_groq=False).intent == "comparative"


def test_comparative_with_single_fund_named() -> None:
    # The Step 3 gap: only one fund named, so retrieval would not flag ambiguity
    assert classify("Is HDFC Large Cap better than its benchmark?", allow_groq=False).intent == (
        "comparative"
    )


@pytest.mark.parametrize(
    "message",
    [
        "What were the 3 year returns of HDFC Mid Cap Fund?",
        "If I had invested 10000 in HDFC Small Cap 5 years ago what would it be worth?",
        "What is the CAGR of HDFC ELSS?",
        "What is the NAV of HDFC Large Cap Fund?",
    ],
)
def test_performance(message: str) -> None:
    assert classify(message, allow_groq=False).intent == "performance"


@pytest.mark.parametrize(
    "message",
    [
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
        "What is the minimum SIP amount for HDFC Mid Cap Fund?",
        "What is the exit load on HDFC Small Cap Fund?",
        "What is the lock-in period of HDFC ELSS Tax Saver Fund?",
        "Which benchmark does HDFC Large Cap Fund track?",
    ],
)
def test_factual(message: str) -> None:
    result = classify(message, allow_groq=False)
    assert result.intent == "factual"
    assert result.is_answerable


@pytest.mark.parametrize(
    "message",
    [
        "What is the share price of Reliance Industries today?",
        "Write me a poem about compounding",
        "",
        "hello there",
    ],
)
def test_out_of_scope(message: str) -> None:
    assert classify(message, allow_groq=False).intent == "out_of_scope"


# --- Groq fallback ---------------------------------------------------------


def test_rules_decide_without_calling_groq() -> None:
    fake = _FakeGroq()
    result = classify(
        "What is the expense ratio of HDFC Large Cap Fund?",
        client=fake,
        allow_groq=True,
    )
    assert result.intent == "factual"
    assert result.source == "rules"
    assert fake.calls == 0


def test_pii_never_reaches_groq() -> None:
    fake = _FakeGroq()
    classify("My PAN is ABCDE1234F, check my folio", client=fake, allow_groq=True)
    assert fake.calls == 0


def test_clearly_off_topic_refuses_without_groq() -> None:
    fake = _FakeGroq()
    result = classify("What is the share price of Reliance Industries today?", client=fake)
    assert result.intent == "out_of_scope"
    assert fake.calls == 0


def test_groq_labels_fuzzy_message() -> None:
    # In-domain but names no stored fact — the one case worth a Groq call
    fake = _FakeGroq(reply="advisory")
    result = classify("what do you make of the HDFC tax saver fund", client=fake, allow_groq=True)
    assert fake.calls == 1
    assert result.intent == "advisory"
    assert result.source == "groq"


def test_groq_failure_defaults_to_out_of_scope() -> None:
    class _Broken:
        def chat(self, *a, **k):  # noqa: ANN002, ANN003
            from src.generation.groq_client import GroqAPIError

            raise GroqAPIError("boom")

    result = classify(
        "what do you make of the HDFC tax saver fund", client=_Broken(), allow_groq=True
    )
    assert result.intent == "out_of_scope"
    assert result.source == "default"


def test_groq_cannot_return_pii_label() -> None:
    fake = _FakeGroq(reply="pii_account")
    assert classify_with_groq("something vague", client=fake) is None


def test_fuzzy_in_domain_message_is_the_only_classifier_spend() -> None:
    fake = _FakeGroq(reply="factual")
    classify("tell me about the HDFC mid cap fund", client=fake, allow_groq=True)
    assert fake.calls == 1


def test_classification_to_dict() -> None:
    payload = Classification("advisory", reason="should i").to_dict()
    assert payload["intent"] == "advisory"
    assert payload["source"] == "rules"

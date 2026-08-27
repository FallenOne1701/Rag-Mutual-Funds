"""Generation — Groq client, Query Classifier, Refusal Handler, Generator, Validator."""

from src.generation.budget import (
    BudgetSnapshot,
    GroqBudget,
    GroqBudgetExceeded,
    estimate_tokens,
    get_budget,
    reset_budget,
)
from src.generation.classifier import (
    INTENTS,
    Classification,
    Intent,
    classify,
    classify_rules,
    classify_with_groq,
)
from src.generation.generator import (
    AssistantResponse,
    generate_answer,
    generate_from_retrieval,
    groww_link_fallback,
    is_performance_query,
    package_response,
    performance_link_response,
    refusal_citation,
)
from src.generation.groq_client import (
    ChatMessage,
    ChatResult,
    GroqAPIError,
    GroqBudgetError,
    GroqClient,
    GroqClientError,
    GroqConfigError,
    get_groq_client,
    reset_groq_client_cache,
)
from src.generation.pii import PIIFinding, contains_pii, detect_pii, redact
from src.generation.pipeline import ChatOutcome, answer_question
from src.generation.refusal import EDUCATIONAL_URL, build_refusal, refuse, refusal_text
from src.generation.validator import ValidationResult, count_sentences, validate, validate_response

__all__ = [
    "INTENTS",
    "AssistantResponse",
    "BudgetSnapshot",
    "ChatMessage",
    "ChatOutcome",
    "ChatResult",
    "Classification",
    "EDUCATIONAL_URL",
    "GroqAPIError",
    "GroqBudget",
    "GroqBudgetError",
    "GroqBudgetExceeded",
    "GroqClient",
    "GroqClientError",
    "GroqConfigError",
    "Intent",
    "PIIFinding",
    "ValidationResult",
    "answer_question",
    "build_refusal",
    "classify",
    "classify_rules",
    "classify_with_groq",
    "contains_pii",
    "count_sentences",
    "detect_pii",
    "estimate_tokens",
    "generate_answer",
    "generate_from_retrieval",
    "get_budget",
    "get_groq_client",
    "groww_link_fallback",
    "is_performance_query",
    "package_response",
    "performance_link_response",
    "redact",
    "refusal_citation",
    "refusal_text",
    "refuse",
    "reset_budget",
    "reset_groq_client_cache",
    "validate",
    "validate_response",
]

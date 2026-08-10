from app.explanations.errors import (
    ExplanationErrorCode,
    ExplanationValidationError,
    ExplanationValidationFailureCode,
    MergeReadinessExplanationError,
    LLMProviderError,
    LLMProviderFailureCategory,
)
from app.explanations.factory import create_llm_client
from app.explanations.fakes import FakeLLMClient
from app.explanations.gemini_client import GeminiLLMClient
from app.explanations.models import (
    GeneratedExplanation,
    LLMStructuredResponse,
    LLMTokenUsage,
    LLMProviderName,
    MergeReadinessExplanation,
    MergeReadinessExplanationInput,
    ValidatedExplanation,
)
from app.explanations.protocols import LLMClient
from app.explanations.openai_client import OpenAILLMClient
from app.explanations.service import (
    MergeReadinessExplanationService,
    build_explanation_input,
)
from app.explanations.templates import render_validated_explanation
from app.explanations.validator import (
    StrictMergeReadinessExplanationValidator,
)

__all__ = [
    "ExplanationErrorCode",
    "ExplanationValidationError",
    "ExplanationValidationFailureCode",
    "FakeLLMClient",
    "GeneratedExplanation",
    "GeminiLLMClient",
    "LLMClient",
    "LLMProviderError",
    "LLMProviderFailureCategory",
    "LLMProviderName",
    "LLMStructuredResponse",
    "LLMTokenUsage",
    "MergeReadinessExplanation",
    "MergeReadinessExplanationError",
    "MergeReadinessExplanationInput",
    "MergeReadinessExplanationService",
    "OpenAILLMClient",
    "StrictMergeReadinessExplanationValidator",
    "ValidatedExplanation",
    "build_explanation_input",
    "create_llm_client",
    "render_validated_explanation",
]

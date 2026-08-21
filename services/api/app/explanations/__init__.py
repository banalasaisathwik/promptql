from app.explanations.errors import (
    ExplanationErrorCode,
    ExplanationValidationError,
    ExplanationValidationFailureCode,
    MergeReadinessExplanationError,
    LLMProviderError,
    LLMProviderErrorDetails,
    LLMProviderFailureCategory,
)
from app.explanations.factory import create_llm_client
from app.explanations.fakes import FakeLLMClient
from app.explanations.gemini_client import GeminiLLMClient
from app.explanations.groq_client import GroqLLMClient
from app.explanations.models import (
    GeneratedExplanation,
    LLMStructuredResponse,
    LLMTokenUsage,
    LLMProviderName,
    MergeReadinessExplanation,
    MergeReadinessExplanationInput,
    TypedLLMRequest,
    ValidatedExplanation,
)
from app.explanations.protocols import LLMClient, TypedLLMClient
from app.explanations.openai_client import OpenAILLMClient
from app.explanations.openrouter_client import OpenRouterLLMClient
from app.explanations.service import (
    MergeReadinessExplanationService,
    build_explanation_input,
)
from app.explanations.templates import render_validated_explanation
from app.explanations.validator import (
    StrictMergeReadinessExplanationValidator,
    required_explanation_claims,
)

__all__ = [
    "ExplanationErrorCode",
    "ExplanationValidationError",
    "ExplanationValidationFailureCode",
    "FakeLLMClient",
    "GeneratedExplanation",
    "GeminiLLMClient",
    "GroqLLMClient",
    "LLMClient",
    "LLMProviderError",
    "LLMProviderErrorDetails",
    "LLMProviderFailureCategory",
    "LLMProviderName",
    "LLMStructuredResponse",
    "LLMTokenUsage",
    "MergeReadinessExplanation",
    "MergeReadinessExplanationError",
    "MergeReadinessExplanationInput",
    "MergeReadinessExplanationService",
    "OpenAILLMClient",
    "OpenRouterLLMClient",
    "StrictMergeReadinessExplanationValidator",
    "ValidatedExplanation",
    "TypedLLMClient",
    "TypedLLMRequest",
    "build_explanation_input",
    "create_llm_client",
    "render_validated_explanation",
    "required_explanation_claims",
]

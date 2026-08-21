from openai import AsyncOpenAI

from app.config import LLMConfigurationError, LLMProvider, LLMSettings
from app.explanations.fakes import FakeLLMClient
from app.explanations.gemini_client import GeminiLLMClient
from app.explanations.groq_client import GroqLLMClient
from app.explanations.openai_client import OpenAILLMClient
from app.explanations.openrouter_client import OpenRouterLLMClient
from app.explanations.protocols import LLMClient


GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"


def create_llm_client(settings: LLMSettings, model: str | None = None) -> LLMClient:
    if settings.provider is LLMProvider.FAKE:
        return FakeLLMClient()


    # PURPOSE: Keep provider authentication separate from task model choice.
    # The caller may supply a deterministic task-policy result, while V1 uses
    # the configured default model through the same factory and adapter path.
    selected_model = model or settings.model
    if settings.api_key is None or selected_model is None:
        raise LLMConfigurationError("LLM provider settings are incomplete.")


    sdk_options: dict[str, object] = {
        "api_key": settings.api_key,
        "timeout": settings.request_timeout_seconds,
        "max_retries": 0,
    }
    if settings.provider is LLMProvider.GEMINI:
        sdk_options["base_url"] = GEMINI_OPENAI_BASE_URL
    elif settings.provider is LLMProvider.GROQ:
        sdk_options["base_url"] = GROQ_OPENAI_BASE_URL
    elif settings.provider is LLMProvider.OPENROUTER:
        sdk_options["base_url"] = OPENROUTER_OPENAI_BASE_URL

    sdk_client = AsyncOpenAI(**sdk_options)
    if settings.provider is LLMProvider.GEMINI:
        return GeminiLLMClient(
            client=sdk_client,
            model=selected_model,
            request_timeout_seconds=settings.request_timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
        )
    if settings.provider is LLMProvider.GROQ:
        return GroqLLMClient(
            client=sdk_client,
            model=selected_model,
            request_timeout_seconds=settings.request_timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
        )
    if settings.provider is LLMProvider.OPENROUTER:
        return OpenRouterLLMClient(
            client=sdk_client,
            model=selected_model,
            request_timeout_seconds=settings.request_timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
        )

    return OpenAILLMClient(
        client=sdk_client,
        model=selected_model,
        request_timeout_seconds=settings.request_timeout_seconds,
        max_output_tokens=settings.max_output_tokens,
    )

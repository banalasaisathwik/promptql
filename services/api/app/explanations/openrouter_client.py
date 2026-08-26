from app.explanations.groq_client import GroqLLMClient
from app.explanations.models import LLMProviderName


class OpenRouterLLMClient(GroqLLMClient):
    provider = LLMProviderName.OPENROUTER
    _typed_reasoning_effort = None
    _diagnostic_provider_name = "OpenRouter"

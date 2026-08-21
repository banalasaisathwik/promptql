"""OpenRouter reuses the existing OpenAI-compatible chat-completions adapter."""

from app.explanations.groq_client import GroqLLMClient
from app.explanations.models import LLMProviderName


class OpenRouterLLMClient(GroqLLMClient):
    # OpenRouter's provider routing remains behind its API; PromptQL only owns
    # this requested provider identity and the configured model sent to it.
    # The shared adapter handles compatible typed parsing, but Groq's reasoning
    # control is a provider-specific request option and must not leak here.
    provider = LLMProviderName.OPENROUTER
    _typed_reasoning_effort = None
    _diagnostic_provider_name = "OpenRouter"

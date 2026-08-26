from app.explanations.errors import LLMProviderErrorDetails
from app.investigations.hypotheses.models import HypothesisGenerationFailureCode


class HypothesisGenerationError(RuntimeError):
    def __init__(
        self,
        code: HypothesisGenerationFailureCode,
        *,
        provider_details: LLMProviderErrorDetails | None = None,
        provider_failure_category: str | None = None,
    ) -> None:
        self.code = code
        self.provider_details = provider_details
        self.provider_failure_category = provider_failure_category
        super().__init__("The hypothesis generator did not return usable structured output.")

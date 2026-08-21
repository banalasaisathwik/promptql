from app.explanations.errors import LLMProviderErrorDetails
from app.investigations.planning.models import PlannerFailureCode


class InvestigationPlannerError(RuntimeError):
    def __init__(
        self,
        code: PlannerFailureCode,
        message: str,
        provider_details: LLMProviderErrorDetails | None = None,
        provider_failure_category: str | None = None,
    ) -> None:
        self.code = code
        self.provider_details = provider_details
        self.provider_failure_category = provider_failure_category
        super().__init__(message)

"""Sanitized failures at the code-diagnosis generation boundary."""

from app.explanations.errors import LLMProviderErrorDetails
from app.investigations.code_diagnosis.models import CodeDiagnosisFailureCode


class CodeDiagnosisError(RuntimeError):
    def __init__(
        self,
        code: CodeDiagnosisFailureCode,
        *,
        provider_details: LLMProviderErrorDetails | None = None,
        provider_failure_category: str | None = None,
    ) -> None:
        self.code = code
        self.provider_details = provider_details
        self.provider_failure_category = provider_failure_category
        super().__init__("The code-diagnosis provider did not return usable structured output.")

from enum import StrEnum


class ExplanationErrorCode(StrEnum):
    PROVIDER_FAILURE = "provider_failure"
    INVALID_OUTPUT = "invalid_output"
    VALIDATION_FAILED = "validation_failed"


class MergeReadinessExplanationError(RuntimeError):
    def __init__(self, code: ExplanationErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

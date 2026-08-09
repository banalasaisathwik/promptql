from enum import StrEnum


class ExplanationErrorCode(StrEnum):
    PROVIDER_FAILURE = "provider_failure"
    INVALID_OUTPUT = "invalid_output"
    VALIDATION_FAILED = "validation_failed"


class ExplanationValidationFailureCode(StrEnum):
    INVALID_STRUCTURE = "invalid_structure"
    DECISION_MISMATCH = "decision_mismatch"
    DUPLICATE_REASON = "duplicate_reason"
    DUPLICATE_ACTION = "duplicate_action"
    CONTRADICTORY_CLAIM = "contradictory_claim"
    UNKNOWN_MISSING_EVIDENCE = "unknown_missing_evidence"
    UNSUPPORTED_REASON = "unsupported_reason"
    UNSUPPORTED_ACTION = "unsupported_action"
    MISSING_REQUIRED_REASON = "missing_required_reason"
    MISSING_REQUIRED_ACTION = "missing_required_action"


class ExplanationValidationError(ValueError):
    def __init__(self, code: ExplanationValidationFailureCode) -> None:
        self.code = code
        super().__init__("The generated explanation failed validation.")


class MergeReadinessExplanationError(RuntimeError):
    def __init__(self, code: ExplanationErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

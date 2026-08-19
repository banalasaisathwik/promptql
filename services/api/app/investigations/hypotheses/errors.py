"""Sanitized failures at the hypothesis-generation boundary."""

from app.investigations.hypotheses.models import HypothesisGenerationFailureCode


class HypothesisGenerationError(RuntimeError):
    def __init__(self, code: HypothesisGenerationFailureCode) -> None:
        self.code = code
        super().__init__("The hypothesis generator did not return usable structured output.")

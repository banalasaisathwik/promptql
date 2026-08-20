from app.investigations.hypotheses.errors import HypothesisGenerationError
from app.investigations.hypotheses.instructions import HYPOTHESIS_PROMPT_ID, HYPOTHESIS_PROMPT_VERSION
from app.investigations.hypotheses.models import (
    CandidateHypothesis,
    GeneratedHypotheses,
    HypothesisGenerationFailureCode,
    HypothesisGenerationInput,
    HypothesisGenerationOutput,
    HypothesisKind,
    HypothesisValidationFailureCode,
    HypothesisValidationResult,
    MAX_HYPOTHESES,
    ValidatedHypothesis,
)
from app.investigations.hypotheses.service import TypedLLMHypothesisGenerator
from app.investigations.hypotheses.prompt import build_hypothesis_generation_input
from app.investigations.hypotheses.validator import DeterministicHypothesisValidator
from app.investigations.hypotheses.rendering import (
    GroundedHypothesis,
    GroundedInvestigationResult,
    GroundedTerminationReason,
    GroundingRenderError,
    render_fact_summary,
    render_grounded_result,
    render_missing_information,
)

__all__ = [
    "CandidateHypothesis", "DeterministicHypothesisValidator", "GeneratedHypotheses",
    "HYPOTHESIS_PROMPT_ID", "HYPOTHESIS_PROMPT_VERSION", "HypothesisGenerationError",
    "HypothesisGenerationFailureCode", "HypothesisGenerationInput", "HypothesisGenerationOutput",
    "HypothesisKind", "HypothesisValidationFailureCode", "HypothesisValidationResult",
    "MAX_HYPOTHESES", "TypedLLMHypothesisGenerator", "ValidatedHypothesis",
    "GroundedHypothesis", "GroundedInvestigationResult", "GroundedTerminationReason",
    "GroundingRenderError", "render_fact_summary", "render_grounded_result",
    "render_missing_information",
    "build_hypothesis_generation_input",
]

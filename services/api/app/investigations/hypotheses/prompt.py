from typing import TYPE_CHECKING

from app.investigations.hypotheses.models import HypothesisGenerationInput
from app.investigations.models import InvestigationRequest
if TYPE_CHECKING:
    from app.investigations.replanning import AdaptiveInvestigationState


def build_hypothesis_generation_input(
    request: InvestigationRequest,
    state: "AdaptiveInvestigationState",
) -> HypothesisGenerationInput:
    return HypothesisGenerationInput(
        investigation_goal=request.question,
        facts=tuple(sorted(state.facts, key=lambda fact: fact.fact_id)),
        missing_information=tuple(
            sorted(
                state.missing_information,
                key=lambda item: item.missing_information_id,
            )
        ),
    )

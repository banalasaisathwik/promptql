from typing import TYPE_CHECKING
from uuid import UUID

from app.investigations.hypotheses.models import HypothesisGenerationInput
from app.investigations.models import InvestigationRequest
from app.observability.runtime_telemetry import RuntimeTelemetry
if TYPE_CHECKING:
    from app.investigations.replanning import AdaptiveInvestigationState


def build_hypothesis_generation_input(
    request: InvestigationRequest,
    state: "AdaptiveInvestigationState",
    *,
    telemetry: RuntimeTelemetry | None = None,
    run_id: UUID | None = None,
) -> HypothesisGenerationInput:
    generation_input = HypothesisGenerationInput(
        investigation_goal=request.question,
        facts=tuple(sorted(state.facts, key=lambda fact: fact.fact_id)),
        missing_information=tuple(
            sorted(
                state.missing_information,
                key=lambda item: item.missing_information_id,
            )
        ),
    )
    if telemetry is not None and run_id is not None:
        telemetry.record_context_size_measured(
            run_id,
            "hypothesis",
            len(generation_input.model_dump_json()),
        )
    return generation_input

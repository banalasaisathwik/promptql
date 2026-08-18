from pydantic import ValidationError

from app.explanations import (
    LLMProviderError,
    LLMStructuredResponse,
    TypedLLMClient,
    TypedLLMRequest,
)
from app.investigations.planning.errors import InvestigationPlannerError
from app.investigations.planning.instructions import (
    PLANNER_PROMPT_ID,
    PLANNER_PROMPT_VERSION,
    PLANNER_SYSTEM_INSTRUCTIONS,
)
from app.investigations.planning.models import (
    InvestigationPlan,
    PlannedInvestigation,
    PlannerFailureCode,
    PlannerInput,
    PlannerMetadata,
)


class TypedLLMPlanner:
    # PURPOSE: Turn an LLM proposal into a strict plan contract, stopping before
    # any execution. `await` only waits for the provider; no tool adapter is held
    # or called by this service.
    """Ask an injected LLM client for a typed proposal; never execute the proposal."""

    def __init__(self, client: TypedLLMClient) -> None:
        self._client = client

    async def plan(self, planner_input: PlannerInput) -> PlannedInvestigation:
        # Provider failure, an invalid outer response, and invalid plan fields are
        # separate outcomes so future runtime policy can react to each safely.
        try:
            response = await self._client.generate_typed(
                TypedLLMRequest(
                    system_instructions=PLANNER_SYSTEM_INSTRUCTIONS,
                    input=planner_input,
                    output_model=InvestigationPlan,
                )
            )
        except LLMProviderError:
            raise InvestigationPlannerError(
                PlannerFailureCode.PROVIDER_FAILURE,
                "The planning provider failed.",
            ) from None
        except Exception:
            raise InvestigationPlannerError(
                PlannerFailureCode.PROVIDER_FAILURE,
                "The planning provider failed.",
            ) from None

        try:
            structured = LLMStructuredResponse.model_validate(response)
        except (TypeError, ValidationError):
            raise InvestigationPlannerError(
                PlannerFailureCode.INVALID_RESPONSE,
                "The planning provider returned an invalid structured response.",
            ) from None
        try:
            plan = InvestigationPlan.model_validate(structured.output)
        except ValidationError:
            raise InvestigationPlannerError(
                PlannerFailureCode.PLAN_SCHEMA_INVALID,
                "The planning proposal did not match the plan schema.",
            ) from None
        return PlannedInvestigation(
            plan=plan,
            metadata=PlannerMetadata(
                provider=self._client.provider.value,
                model=self._client.model,
                prompt_id=PLANNER_PROMPT_ID,
                prompt_version=PLANNER_PROMPT_VERSION,
            ),
        )

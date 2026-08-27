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
    build_planner_system_instructions,
)
from app.investigations.planning.models import (
    InvestigationPlan,
    PlannedInvestigation,
    PlannerFailureCode,
    PlannerInput,
    PlannerMetadata,
)


class TypedLLMPlanner:
    def __init__(self, client: TypedLLMClient) -> None:
        self._client = client

    async def plan(self, planner_input: PlannerInput) -> PlannedInvestigation:
        try:
            response = await self._client.generate_typed(
                TypedLLMRequest(
                    system_instructions=build_planner_system_instructions(planner_input),
                    input=planner_input,
                    output_model=InvestigationPlan,
                )
            )
        except LLMProviderError as error:
            raise InvestigationPlannerError(
                PlannerFailureCode.PROVIDER_FAILURE,
                "The planning provider failed.",
                provider_details=error.details,
                provider_failure_category=error.category.value,
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
                task="planning",
                provider=self._client.provider.value,
                model=self._client.model,
                requested_model=self._client.model,
                resolved_model=structured.resolved_model,
                prompt_id=PLANNER_PROMPT_ID,
                prompt_version=PLANNER_PROMPT_VERSION,
                token_usage=structured.token_usage,
            ),
        )

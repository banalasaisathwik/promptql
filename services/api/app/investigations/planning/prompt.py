from collections.abc import Iterable
from uuid import UUID

from app.investigations.models import Evidence, FactSet, InvestigationRequest, InvestigationResult, MissingInformation
from app.investigations.planning.models import (
    ActionSummary,
    CompactEvidenceContext,
    PlannerInput,
    PlannerToolDefinition,
    PlannerToolInputField,
    RememberedRepositoryPattern,
)
from app.observability.runtime_telemetry import RuntimeTelemetry
from app.runtime import FactRecurrenceRepository
from app.tools.models import ToolDefinition


def _evidence_summary(evidence: Evidence) -> str:
    content = evidence.content
    if content.content_type == "diff_hunk":
        return f"diff hunk for {content.file_path}"
    if content.content_type == "commit":
        return f"commit {content.commit_sha}"
    if content.content_type == "deployment":
        return f"deployment {content.deployment_reference} for {content.service}"
    if content.content_type == "pull_request":
        return f"pull request {content.pull_request_number}"
    if content.content_type == "stack_frame":
        return f"failure location {content.file_path or 'unavailable'}"
    return f"{content.content_type} evidence"


def _tool_context(definition: ToolDefinition) -> PlannerToolDefinition:
    schema = definition.input_schema
    properties = schema.get("properties", {})
    required = frozenset(schema.get("required", ()))
    return PlannerToolDefinition(
        tool_id=definition.tool_id,
        description=definition.description,
        input_fields=tuple(
            PlannerToolInputField(name=name, required=name in required)
            for name in sorted(properties)
        ),
        input_schema=schema,
        output_schema=definition.plan_output_model.model_json_schema(),
    )


class ContextBuilder:
    def build(
        self,
        investigation_goal: str,
        facts: FactSet,
        missing_information: tuple[MissingInformation, ...],
        evidence: tuple[Evidence, ...],
        allowed_tools: Iterable[ToolDefinition],
        *,
        action_history: tuple[ActionSummary, ...] = (),
        remaining_tool_calls: int = 0,
        planning_round: int = 1,
        max_planning_rounds: int = 1,
        request_context: InvestigationRequest | None = None,
        telemetry: RuntimeTelemetry | None = None,
        run_id: UUID | None = None,
        fact_recurrence_repository: FactRecurrenceRepository | None = None,
        prior_result_summary: str | None = None,
    ) -> PlannerInput:
        remembered_patterns: tuple[RememberedRepositoryPattern, ...] = ()
        if fact_recurrence_repository is not None and request_context is not None:
            remembered_patterns = tuple(
                RememberedRepositoryPattern(
                    fact_type=record.fact_type,
                    occurrence_count=record.occurrence_count,
                )
                for record in fact_recurrence_repository.list_promoted(
                    request_context.repository_owner,
                    request_context.repository_name,
                )
            )
        planner_input = PlannerInput(
            investigation_goal=investigation_goal,
            request_context=request_context,
            facts=tuple(sorted(facts, key=lambda fact: fact.fact_id)),
            missing_information=tuple(sorted(missing_information, key=lambda item: item.missing_information_id)),
            evidence=tuple(
                CompactEvidenceContext(
                    evidence_id=item.evidence_id,
                    source=item.source,
                    kind=item.kind,
                    source_reference=item.provenance.source_reference,
                    summary=_evidence_summary(item),
                )
                for item in sorted(evidence, key=lambda item: item.evidence_id)
            ),
            action_history=action_history,
            remaining_tool_calls=remaining_tool_calls,
            planning_round=planning_round,
            max_planning_rounds=max_planning_rounds,
            allowed_tools=tuple(_tool_context(definition) for definition in sorted(allowed_tools, key=lambda item: item.tool_id)),
            remembered_patterns=remembered_patterns,
            prior_result_summary=prior_result_summary,
        )
        if telemetry is not None and run_id is not None:
            telemetry.record_context_size_measured(
                run_id,
                "planner",
                len(planner_input.model_dump_json()),
                round_number=planning_round,
            )
        return planner_input


def build_planner_input(
    request: InvestigationRequest,
    result: InvestigationResult,
    allowed_tools: Iterable[ToolDefinition],
    *,
    action_history: tuple[ActionSummary, ...] = (),
    remaining_tool_calls: int = 0,
    planning_round: int = 1,
    max_planning_rounds: int = 1,
) -> PlannerInput:
    return ContextBuilder().build(
        request.question,
        result.facts,
        result.missing_information,
        result.evidence,
        allowed_tools,
        action_history=action_history,
        remaining_tool_calls=remaining_tool_calls,
        planning_round=planning_round,
        max_planning_rounds=max_planning_rounds,
        request_context=request,
    )

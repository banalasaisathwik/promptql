from collections.abc import Iterable

from app.investigations.models import Evidence, FactSet, InvestigationRequest, InvestigationResult, MissingInformation
from app.investigations.planning.models import (
    ActionSummary,
    CompactEvidenceContext,
    PlannerInput,
    PlannerToolDefinition,
    PlannerToolInputField,
)
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
    # PURPOSE: Make the planner's untrusted input a reproducible projection of
    # current investigation state, rather than a second mutable runtime model.
    #
    # DESIGN: Sorting IDs and tool definitions makes equivalent state produce
    # equivalent Pydantic input, which is useful for deterministic tests and
    # later replay without introducing LLM summarization or retrieval.
    """Build the bounded, deterministic state supplied to the planner."""

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
    ) -> PlannerInput:
        return PlannerInput(
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
        )


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
    # FLOW: Sort stable domain identifiers -> reduce Evidence to safe summaries ->
    # expose only the caller-approved tool subset. This deterministic boundary
    # makes equivalent state produce equivalent prompt data for review and replay.
    # The goal remains the user's typed question, not inferred model prose.
    """Compress normalized investigation state before it crosses the LLM boundary."""
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

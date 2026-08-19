from collections.abc import Iterable

from app.investigations.models import Evidence, InvestigationRequest, InvestigationResult
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
    # The goal remains the user's typed incident summary, not inferred model prose.
    """Compress normalized investigation state before it crosses the LLM boundary."""
    return PlannerInput(
        investigation_goal=request.incident_summary,
        facts=tuple(sorted(result.facts, key=lambda fact: fact.fact_id)),
        missing_information=tuple(
            sorted(
                result.missing_information,
                key=lambda item: item.missing_information_id,
            )
        ),
        evidence=tuple(
            CompactEvidenceContext(
                evidence_id=evidence.evidence_id,
                source=evidence.source,
                kind=evidence.kind,
                source_reference=evidence.provenance.source_reference,
                summary=_evidence_summary(evidence),
            )
            for evidence in sorted(result.evidence, key=lambda item: item.evidence_id)
        ),
        action_history=action_history,
        remaining_tool_calls=remaining_tool_calls,
        planning_round=planning_round,
        max_planning_rounds=max_planning_rounds,
        allowed_tools=tuple(
            _tool_context(definition)
            for definition in sorted(allowed_tools, key=lambda item: item.tool_id)
        ),
    )

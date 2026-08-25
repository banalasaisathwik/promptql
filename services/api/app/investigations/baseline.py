from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from app.connectors.errors import ConnectorUnavailableError, FixtureNotFoundError
from app.connectors.models import FailureLocationEvidenceRequest
from app.investigations import (
    Evidence,
    InvestigationRequest,
    InvestigationResult,
    MissingInformation,
    MissingInformationKind,
    RecommendedAction,
    RecommendedActionCode,
)
from app.investigations.evidence_store import EvidenceStore
from app.investigations.fact_derivation import derive_facts
from app.tools import InvestigationTool, InvestigationToolId, ToolFailureCode, ToolOutcome, ToolRegistry, ToolResult

if TYPE_CHECKING:
    from app.connectors.protocols import IncidentSource


class DuplicateEvidenceIdError(ValueError):
    pass


class EvidenceAccumulator:
    def __init__(self, store: EvidenceStore | None = None) -> None:
        self._store = store if store is not None else EvidenceStore()
        self._ids: list[str] = []
        self._seen_ids: set[str] = set()

    def add(self, evidence: tuple[Evidence, ...]) -> None:
        for item in evidence:
            if item.evidence_id in self._seen_ids:
                raise DuplicateEvidenceIdError(item.evidence_id)
            self._seen_ids.add(item.evidence_id)
            self._ids.append(item.evidence_id)
            self._store.put(item)

    def values(self) -> tuple[Evidence, ...]:
        return self._store.get_many(tuple(self._ids))


class ToolInvoker:
    def __init__(self, registry: ToolRegistry, tools: Mapping[str, InvestigationTool]) -> None:
        self._registry = registry
        self._tools = tools

    async def invoke(
        self,
        tool_id: InvestigationToolId,
        arguments: Mapping[str, object],
    ) -> ToolResult:
        definition = self._registry.get(tool_id)
        tool = self._tools.get(tool_id)
        if tool is None or tool.definition != definition:
            return ToolResult(
                tool_id=tool_id,
                outcome=ToolOutcome.FAILED,
                failure={
                    "code": ToolFailureCode.CAPABILITY_UNAVAILABLE,
                    "message": "the registered tool has no available capability",
                },
            )
        return await tool.execute(arguments)


class DeterministicBaseline:
    def __init__(
        self,
        invoker: ToolInvoker,
        incident_source: IncidentSource,
        store: EvidenceStore,
    ) -> None:
        self._invoker = invoker
        self._incident_source = incident_source
        self._store = store

    async def investigate(self, request: InvestigationRequest) -> InvestigationResult:
        evidence = EvidenceAccumulator(self._store)
        missing: list[MissingInformation] = []

        if request.incident_reference is None:
            missing.append(self._missing_deployment_or_incident("incident"))
        else:
            await self._collect_tool(
                evidence, missing, InvestigationToolId.GET_INCIDENT,
                {"incident_reference": request.incident_reference},
            )
            await self._collect_failure_location(evidence, missing, request.incident_reference)

        if request.deployment_reference is None:
            missing.append(self._missing_deployment_or_incident("deployment"))
        else:
            await self._collect_tool(
                evidence, missing, InvestigationToolId.GET_DEPLOYMENTS,
                {"deployment_reference": request.deployment_reference},
            )

        if request.telemetry_window is not None:
            await self._collect_tool(
                evidence, missing, InvestigationToolId.QUERY_TELEMETRY,
                request.telemetry_window.model_dump(),
            )


        for item in evidence.values():
            content = item.content
            if content.content_type != "deployment":
                continue
            await self._collect_tool(
                evidence, missing, InvestigationToolId.GET_COMMIT,
                {
                    "repository_owner": request.repository_owner,
                    "repository_name": request.repository_name,
                    "commit_sha": content.commit_sha,
                },
            )

        if request.pull_request_number is not None:
            pull_request_arguments = {
                "repository_owner": request.repository_owner,
                "repository_name": request.repository_name,
                "pr_number": request.pull_request_number,
            }
            await self._collect_tool(evidence, missing, InvestigationToolId.GET_PULL_REQUEST, pull_request_arguments)
            await self._collect_tool(evidence, missing, InvestigationToolId.GET_DIFF, pull_request_arguments)

        if request.jira_issue_key is not None:
            await self._collect_tool(
                evidence, missing, InvestigationToolId.GET_JIRA_ISSUE,
                {"issue_key": request.jira_issue_key},
            )

        unique_missing = tuple({item.missing_information_id: item for item in missing}.values())


        facts = derive_facts(evidence.values())
        return InvestigationResult(
            evidence=evidence.values(), facts=facts, hypotheses=(),
            missing_information=unique_missing, recommended_actions=tuple(
                self._action_for(item) for item in unique_missing
            ),
        )

    async def _collect_tool(
        self, evidence: EvidenceAccumulator, missing: list[MissingInformation],
        tool_id: InvestigationToolId, arguments: Mapping[str, object],
    ) -> None:
        result = await self._invoker.invoke(tool_id, arguments)
        if result.outcome is ToolOutcome.OBSERVED:
            evidence.add(self._store.get_many(result.evidence_ids))
        elif result.outcome is ToolOutcome.FAILED:
            missing.append(self._missing_source(tool_id, result))

    async def _collect_failure_location(
        self, evidence: EvidenceAccumulator, missing: list[MissingInformation], incident_reference: str,
    ) -> None:
        try:
            evidence.add((await self._incident_source.get_failure_location_evidence(
                FailureLocationEvidenceRequest(incident_reference=incident_reference)
            ),))
        except (ConnectorUnavailableError, FixtureNotFoundError):
            missing.append(self._missing_source(InvestigationToolId.GET_INCIDENT, None))

    @staticmethod
    def _missing_deployment_or_incident(subject: str) -> MissingInformation:
        kind = MissingInformationKind.DEPLOYMENT_MAPPING_UNAVAILABLE if subject == "deployment" else MissingInformationKind.INCIDENT_TIMELINE_INCOMPLETE
        return MissingInformation(
            missing_information_id=f"missing:{subject}-reference",
            kind=kind,
            detail=f"No {subject} reference was supplied for the deterministic baseline.",
        )

    @staticmethod
    def _missing_source(tool_id: InvestigationToolId, result: ToolResult | None) -> MissingInformation:
        suffix = result.failure.code.value if result is not None and result.failure is not None else "source_failure"
        return MissingInformation(
            missing_information_id=f"missing:{tool_id}:{suffix}",
            kind=MissingInformationKind.SOURCE_DATA_UNAVAILABLE,
            detail=f"The {tool_id.value} capability did not return usable evidence.",
        )

    @staticmethod
    def _action_for(item: MissingInformation) -> RecommendedAction:
        code = RecommendedActionCode.COLLECT_DEPLOYMENT_MAPPING if item.kind is MissingInformationKind.DEPLOYMENT_MAPPING_UNAVAILABLE else RecommendedActionCode.RETRIEVE_SOURCE_DATA
        return RecommendedAction(
            action_id=f"action:{item.missing_information_id}", action_code=code,
            message="Collect the unavailable deterministic investigation input.",
            related_missing_information_ids=(item.missing_information_id,),
        )

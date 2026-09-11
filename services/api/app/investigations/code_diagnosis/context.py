from __future__ import annotations

from typing import TYPE_CHECKING

from app.investigations.code_diagnosis.models import (
    MAX_CODE_CONTEXT_LOCATIONS,
    MAX_CODE_LINES_PER_HUNK,
    CodeContextKind,
    CodeContextLine,
    CodeContextLocation,
    CodeDiagnosisInput,
    CodeDiagnosisHypothesis,
    CodeDiagnosisSupport,
)
from app.investigations.models import (
    ChangedFileEvidenceContent,
    CommitChangedFileEvidenceContent,
    CommitDiffHunkEvidenceContent,
    DiffHunkEvidenceContent,
    Evidence,
    FactSet,
    InvestigationRequest,
    StackFrameEvidenceContent,
)
from app.investigations.path_normalization import paths_match

if TYPE_CHECKING:
    from app.investigations.hypotheses.models import ValidatedHypothesis


class CodeContextBuilder:
    def build(
        self,
        request: InvestigationRequest,
        hypotheses: tuple[ValidatedHypothesis, ...],
        facts: FactSet,
        evidence: tuple[Evidence, ...],
    ) -> CodeDiagnosisInput:
        selected_hypotheses = tuple(
            sorted(hypotheses, key=lambda item: item.hypothesis_id)
        )
        relevant_paths = {item.subject for item in selected_hypotheses}
        relevant_fact_ids = {
            fact_id
            for hypothesis in selected_hypotheses
            for fact_id in hypothesis.supporting_fact_ids
        }
        selected_facts = tuple(
            sorted(
                (
                    fact
                    for fact in facts
                    if fact.fact_id in relevant_fact_ids
                ),
                key=lambda fact: fact.fact_id,
            )
        )
        facts_by_id = {fact.fact_id: fact for fact in selected_facts}
        support_bundles = tuple(
            _support_bundle(hypothesis, facts_by_id)
            for hypothesis in selected_hypotheses
        )
        locations = tuple(
            sorted(
                (
                    location
                    for item in evidence
                    if (location := _location(item, relevant_paths)) is not None
                ),
                key=lambda item: (item.file_path, item.kind, item.evidence_id),
            )[:MAX_CODE_CONTEXT_LOCATIONS]
        )
        return CodeDiagnosisInput(
            investigation_goal=request.question,
            hypotheses=tuple(
                CodeDiagnosisHypothesis(
                    hypothesis_id=hypothesis.hypothesis_id,
                    kind=hypothesis.kind,
                    subject=hypothesis.subject,
                    supporting_fact_ids=hypothesis.supporting_fact_ids,
                )
                for hypothesis in selected_hypotheses
            ),
            facts=selected_facts,
            support_bundles=support_bundles,
            locations=locations,
        )


def _support_bundle(
    hypothesis: ValidatedHypothesis,
    facts_by_id: dict[str, object],
) -> CodeDiagnosisSupport:
    evidence_ids: list[str] = []
    for fact_id in hypothesis.supporting_fact_ids:
        fact = facts_by_id.get(fact_id)
        if fact is None:
            raise ValueError("validated hypothesis references an unavailable Fact")
        for evidence_id in getattr(fact, "evidence_reference_ids", ()):
            if evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
    return CodeDiagnosisSupport(
        hypothesis_id=hypothesis.hypothesis_id,
        file_path=hypothesis.subject,
        supporting_fact_ids=hypothesis.supporting_fact_ids,
        supporting_evidence_ids=tuple(evidence_ids),
    )


def _matches_any(path: str, relevant_paths: set[str]) -> bool:
    return any(paths_match(path, relevant_path) for relevant_path in relevant_paths)


def _location(
    evidence: Evidence,
    relevant_paths: set[str],
) -> CodeContextLocation | None:
    content = evidence.content


    if isinstance(content, (ChangedFileEvidenceContent, CommitChangedFileEvidenceContent)):
        if not _matches_any(content.path, relevant_paths):
            return None
        return CodeContextLocation(
            evidence_id=evidence.evidence_id,
            kind=CodeContextKind.CHANGED_FILE,
            file_path=content.path,
        )
    if isinstance(content, (DiffHunkEvidenceContent, CommitDiffHunkEvidenceContent)):
        if not _matches_any(content.file_path, relevant_paths):
            return None
        first_line = (
            content.new_start
            if content.new_count > 0 and content.new_start > 0
            else None
        )
        last_line = (
            content.new_start + content.new_count - 1
            if first_line is not None
            else None
        )
        return CodeContextLocation(
            evidence_id=evidence.evidence_id,
            kind=CodeContextKind.DIFF_HUNK,
            file_path=content.file_path,
            line_start=first_line,
            line_end=last_line,
            lines=tuple(
                CodeContextLine(kind=line.kind, text=line.text[:300])
                for line in content.lines[:MAX_CODE_LINES_PER_HUNK]
            ),
        )
    if isinstance(content, StackFrameEvidenceContent):
        if content.file_path is None or not _matches_any(
            content.file_path, relevant_paths
        ):
            return None
        return CodeContextLocation(
            evidence_id=evidence.evidence_id,
            kind=CodeContextKind.STACK_FRAME,
            file_path=content.file_path,
            line_start=content.line_number,
            line_end=content.line_number,
            function_name=content.function_name,
            error_category=content.error_category,
        )
    return None

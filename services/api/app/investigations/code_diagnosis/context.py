"""Deterministic minimization of code Evidence for diagnosis generation."""

from app.investigations.code_diagnosis.models import (
    MAX_CODE_CONTEXT_LOCATIONS,
    MAX_CODE_LINES_PER_HUNK,
    CodeContextKind,
    CodeContextLine,
    CodeContextLocation,
    CodeDiagnosisInput,
    CodeDiagnosisSupport,
)
from app.investigations.hypotheses import ValidatedHypothesis
from app.investigations.models import (
    ChangedFileEvidenceContent,
    DiffHunkEvidenceContent,
    Evidence,
    FactSet,
    InvestigationRequest,
    StackFrameEvidenceContent,
)


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


class CodeContextBuilder:
    """Build stable, bounded context only for already validated hypotheses."""

    # PURPOSE: Minimize accumulated investigation state before it crosses the
    # code-diagnosis LLM boundary.
    #
    # FLOW: Select accepted-hypothesis paths -> retain only their supporting
    # Facts -> precompute exact support bundles -> normalize relevant Evidence
    # into capped changed-file, hunk, and stack-frame locations.
    #
    # SECURITY: Code lines are untrusted external data. Only relevant hunks are
    # included, with hard limits on location count, line count, and line width.
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
        relevant_paths = {
            _normalized_path(item.subject) for item in selected_hypotheses
        }
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
            hypotheses=selected_hypotheses,
            facts=selected_facts,
            support_bundles=support_bundles,
            locations=locations,
        )


def _support_bundle(
    hypothesis: ValidatedHypothesis,
    facts_by_id: dict[str, object],
) -> CodeDiagnosisSupport:
    # WHY HERE: Repeating this small deterministic join saves the model from
    # reconstructing Fact-to-Evidence relationships. The validator later
    # requires exact equality, so convenience never becomes authority.
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


def _location(
    evidence: Evidence,
    relevant_paths: set[str],
) -> CodeContextLocation | None:
    content = evidence.content
    if isinstance(content, ChangedFileEvidenceContent):
        if _normalized_path(content.path) not in relevant_paths:
            return None
        return CodeContextLocation(
            evidence_id=evidence.evidence_id,
            kind=CodeContextKind.CHANGED_FILE,
            file_path=content.path,
        )
    if isinstance(content, DiffHunkEvidenceContent):
        if _normalized_path(content.file_path) not in relevant_paths:
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
        if (
            content.file_path is None
            or _normalized_path(content.file_path) not in relevant_paths
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

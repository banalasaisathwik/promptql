"""Pure grounding rules for untrusted code-finding candidates."""

from app.investigations.code_diagnosis.models import (
    CodeFindingValidationFailureCode,
    CodeFindingValidationResult,
    RejectedCodeFinding,
    SuspectedCodeFinding,
    ValidatedCodeFinding,
)
from app.investigations.hypotheses import ValidatedHypothesis
from app.investigations.models import (
    ChangedFileEvidenceContent,
    DiffHunkEvidenceContent,
    Evidence,
    FactSet,
    StackFrameEvidenceContent,
)


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


class DeterministicCodeFindingValidator:
    """Accept only code locations that resolve through current trusted state."""

    # PURPOSE: Turn an untrusted semantic proposal into a location-backed domain
    # value without consulting a model, network, or mutable external source.
    #
    # FLOW: Index trusted state -> reject one stable reason per candidate ->
    # resolve the selected Evidence identity -> copy its authoritative location
    # fields into a new ValidatedCodeFinding.
    #
    # WHY: This is analogous to validating an incoming TypeScript DTO and then
    # loading the authoritative database row instead of trusting copied fields.
    def validate(
        self,
        candidates: tuple[SuspectedCodeFinding, ...],
        hypotheses: tuple[ValidatedHypothesis, ...],
        facts: FactSet,
        evidence: tuple[Evidence, ...],
    ) -> CodeFindingValidationResult:
        hypotheses_by_id = {item.hypothesis_id: item for item in hypotheses}
        facts_by_id = {item.fact_id: item for item in facts}
        evidence_by_id = {item.evidence_id: item for item in evidence}
        accepted: list[ValidatedCodeFinding] = []
        rejected: list[RejectedCodeFinding] = []
        seen_finding_ids: set[str] = set()

        for candidate in candidates:
            reason = (
                CodeFindingValidationFailureCode.DUPLICATE_FINDING_ID
                if candidate.finding_id in seen_finding_ids
                else self._rejection_reason(
                    candidate,
                    hypotheses_by_id,
                    facts_by_id,
                    evidence_by_id,
                )
            )
            seen_finding_ids.add(candidate.finding_id)
            if reason is not None:
                rejected.append(RejectedCodeFinding(candidate=candidate, reason=reason))
                continue
            accepted.append(
                _validated_finding(candidate, evidence_by_id)
            )

        return CodeFindingValidationResult(
            accepted_findings=tuple(accepted),
            rejected_candidates=tuple(rejected),
        )

    @staticmethod
    def _rejection_reason(
        candidate: SuspectedCodeFinding,
        hypotheses_by_id: dict[str, ValidatedHypothesis],
        facts_by_id: dict[str, object],
        evidence_by_id: dict[str, Evidence],
    ) -> CodeFindingValidationFailureCode | None:
        if (
            len(candidate.supporting_fact_ids)
            != len(set(candidate.supporting_fact_ids))
            or len(candidate.supporting_evidence_ids)
            != len(set(candidate.supporting_evidence_ids))
        ):
            return CodeFindingValidationFailureCode.DUPLICATE_REFERENCE

        hypothesis = hypotheses_by_id.get(candidate.hypothesis_id)
        if hypothesis is None:
            return CodeFindingValidationFailureCode.UNKNOWN_HYPOTHESIS
        if _normalized_path(candidate.file_path) != _normalized_path(hypothesis.subject):
            return CodeFindingValidationFailureCode.FILE_MISMATCH

        selected_facts = []
        for fact_id in candidate.supporting_fact_ids:
            fact = facts_by_id.get(fact_id)
            if fact is None:
                return CodeFindingValidationFailureCode.UNKNOWN_SUPPORTING_FACT
            selected_facts.append(fact)
        # Exact equality prevents plausible but unrelated existing entities from
        # being smuggled into the final finding as extra "support."
        if set(hypothesis.supporting_fact_ids) != set(candidate.supporting_fact_ids):
            return CodeFindingValidationFailureCode.HYPOTHESIS_SUPPORT_MISMATCH

        selected_evidence = []
        for evidence_id in candidate.supporting_evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                return CodeFindingValidationFailureCode.UNKNOWN_SUPPORTING_EVIDENCE
            selected_evidence.append(item)
        fact_evidence_ids = {
            evidence_id
            for fact in selected_facts
            for evidence_id in getattr(fact, "evidence_reference_ids", ())
        }
        if fact_evidence_ids != set(candidate.supporting_evidence_ids):
            return CodeFindingValidationFailureCode.EVIDENCE_RELATIONSHIP_MISMATCH

        normalized_path = _normalized_path(candidate.file_path)
        changed_file_observed = any(
            isinstance(item.content, ChangedFileEvidenceContent)
            and _normalized_path(item.content.path) == normalized_path
            for item in selected_evidence
        )
        failure_file_observed = any(
            isinstance(item.content, StackFrameEvidenceContent)
            and item.content.file_path is not None
            and _normalized_path(item.content.file_path) == normalized_path
            for item in selected_evidence
        )
        if not changed_file_observed or not failure_file_observed:
            return CodeFindingValidationFailureCode.EVIDENCE_RELATIONSHIP_MISMATCH
        if candidate.location_evidence_id not in candidate.supporting_evidence_ids:
            return CodeFindingValidationFailureCode.LOCATION_NOT_OBSERVED
        location = evidence_by_id.get(candidate.location_evidence_id)
        if location is None or _location_path(location) != normalized_path:
            return CodeFindingValidationFailureCode.LOCATION_NOT_OBSERVED
        return None


def _location_path(evidence: Evidence) -> str | None:
    content = evidence.content
    if isinstance(content, ChangedFileEvidenceContent):
        return _normalized_path(content.path)
    if isinstance(content, DiffHunkEvidenceContent):
        return _normalized_path(content.file_path)
    if isinstance(content, StackFrameEvidenceContent) and content.file_path is not None:
        return _normalized_path(content.file_path)
    return None


def _validated_finding(
    candidate: SuspectedCodeFinding,
    evidence_by_id: dict[str, Evidence],
) -> ValidatedCodeFinding:
    # The candidate cannot carry these coordinates. They enter the validated
    # model only by resolving a previously observed Evidence object.
    location = evidence_by_id[candidate.location_evidence_id]
    content = location.content
    line_number = None
    function_name = None
    hunk_evidence_id = None
    if isinstance(content, StackFrameEvidenceContent):
        line_number = content.line_number
        function_name = content.function_name
    elif isinstance(content, DiffHunkEvidenceContent):
        hunk_evidence_id = location.evidence_id
    return ValidatedCodeFinding(
        finding_id=candidate.finding_id,
        hypothesis_id=candidate.hypothesis_id,
        file_path=candidate.file_path,
        line_number=line_number,
        function_name=function_name,
        hunk_evidence_id=hunk_evidence_id,
        category=candidate.category,
        supporting_fact_ids=candidate.supporting_fact_ids,
        supporting_evidence_ids=candidate.supporting_evidence_ids,
    )

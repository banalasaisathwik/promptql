"""Pure, generic relationship validation for untrusted hypothesis candidates."""

from app.investigations.hypotheses.models import (
    CandidateHypothesis,
    HypothesisKind,
    HypothesisValidationFailureCode,
    HypothesisValidationResult,
    RejectedHypothesis,
    ValidatedHypothesis,
)
from app.investigations.models import (
    ChangedFileFact,
    ChangedFileMatchesFailureFileFact,
    ChangedHunkOverlapsFailureLineFact,
    FactSet,
)


class DeterministicHypothesisValidator:
    """Accept only candidates whose selected facts satisfy a family-specific predicate."""

    # PURPOSE: Decide accepted/rejected state using only supplied typed Facts.
    #
    # FLOW: Index the current FactSet -> inspect candidates in input order ->
    # record one stable rejection reason or construct a validated copy.
    #
    # WHY: The pure function has no provider/LLM dependency, so the same input
    # always produces the same result and no parsed proposal can bypass policy.
    def validate(
        self, candidates: tuple[CandidateHypothesis, ...], facts: FactSet
    ) -> HypothesisValidationResult:
        facts_by_id = {fact.fact_id: fact for fact in facts}
        accepted: list[ValidatedHypothesis] = []
        rejected: list[RejectedHypothesis] = []
        for candidate in candidates:
            rejection = self._rejection_reason(candidate, facts_by_id)
            if rejection is not None:
                rejected.append(RejectedHypothesis(candidate=candidate, reason=rejection))
                continue
            accepted.append(
                ValidatedHypothesis(
                    hypothesis_id=candidate.hypothesis_id,
                    kind=candidate.kind,
                    subject=candidate.subject,
                    supporting_fact_ids=candidate.supporting_fact_ids,
                )
            )
        return HypothesisValidationResult(
            accepted_hypotheses=tuple(accepted), rejected_candidates=tuple(rejected)
        )

    @staticmethod
    def _rejection_reason(candidate: CandidateHypothesis, facts_by_id: dict[str, object]) -> HypothesisValidationFailureCode | None:
        if candidate.kind is not HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED:
            return HypothesisValidationFailureCode.UNSUPPORTED_HYPOTHESIS_KIND
        if len(candidate.supporting_fact_ids) != len(set(candidate.supporting_fact_ids)):
            return HypothesisValidationFailureCode.DUPLICATE_FACT_REFERENCE
        selected_facts = []
        for fact_id in candidate.supporting_fact_ids:
            fact = facts_by_id.get(fact_id)
            if fact is None:
                return HypothesisValidationFailureCode.UNKNOWN_SUPPORTING_FACT
            selected_facts.append(fact)

        # The family rule is expressed in normalized relations, not technology
        # names: the candidate's file-path subject must be both changed and tied
        # to the observed failure location by the selected Facts.
        changed_file_support = any(
            isinstance(fact, ChangedFileFact) and fact.path == candidate.subject
            for fact in selected_facts
        )
        failure_location_support = any(
            isinstance(fact, (ChangedFileMatchesFailureFileFact, ChangedHunkOverlapsFailureLineFact))
            and fact.file_path == candidate.subject
            for fact in selected_facts
        )
        if not changed_file_support or not failure_location_support:
            selected_entities = {
                value
                for fact in selected_facts
                for value in (
                    getattr(fact, "path", None),
                    getattr(fact, "file_path", None),
                )
                if value is not None
            }
            if selected_entities and candidate.subject not in selected_entities:
                return HypothesisValidationFailureCode.ENTITY_MISMATCH
            return HypothesisValidationFailureCode.MISSING_REQUIRED_SUPPORT
        return None

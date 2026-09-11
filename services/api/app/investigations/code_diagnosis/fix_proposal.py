from __future__ import annotations

from hashlib import sha256

from pydantic import ValidationError

from app.explanations import LLMProviderError, LLMStructuredResponse, TypedLLMClient, TypedLLMRequest
from app.investigations.code_diagnosis.models import (
    CodeDiagnosisHypothesis,
    CodeFixProposalFailureCode,
    CodeFixValidationFailureCode,
    CodeFixValidationResult,
    FixProposalInput,
    FixProposalOutput,
    MAX_PROPOSED_FIX_EXPANSION_LINES,
    MAX_PROPOSED_FIX_LINES,
    ProposedCodeFix,
    ProposedCodeFixCandidate,
    RejectedCodeFix,
    ValidatedCodeFinding,
)
from app.investigations.models import (
    ChangedHunkOverlapsFailureLineFact,
    CommitDiffHunkEvidenceContent,
    DiffLineKind,
    DiffHunkEvidenceContent,
    Evidence,
    FactSet,
    StackFrameEvidenceContent,
)
from app.investigations.path_normalization import paths_match


FIX_PROPOSAL_PROMPT_ID = "investigation-code-fix-proposal"
FIX_PROPOSAL_PROMPT_VERSION = "v1.1"
FIX_PROPOSAL_SYSTEM_INSTRUCTIONS = """You are proposing a minimal code correction for an already-validated failure location.

Use only the supplied source/diff context. Explain the concrete runtime failure
mechanism and return the smallest replacement hunk that addresses it. Do not
modify another file, rewrite a whole function unless the supplied hunk is that
small, add imports, dependencies, APIs, variables, types, exception classes,
or helper functions not supported by the supplied context. If a safe concrete
fix cannot be derived, return candidate null.

corrected_hunk must be literal replacement source code, never a unified-diff
fragment: reproduce every line of the supplied original hunk exactly, with
its original indentation, except the lines that must change. Never prefix a
line with a bare "-" or "+" diff marker, and never return an isolated
one-line removal or addition in place of the full hunk -- the reader replaces
the entire original hunk with your entire corrected_hunk verbatim.

The suggestion is not applied. Copy the supplied finding_id, file_path, fact
IDs, and evidence IDs exactly. Return only the typed schema."""


class CodeFixProposalError(RuntimeError):
    def __init__(self, code: CodeFixProposalFailureCode, *, provider_details=None, provider_failure_category=None) -> None:
        self.code = code
        self.provider_details = provider_details
        self.provider_failure_category = provider_failure_category
        super().__init__("The code-fix provider did not return usable structured output.")


class FixProposalContextBuilder:
    def build(
        self,
        finding: ValidatedCodeFinding,
        hypothesis: CodeDiagnosisHypothesis,
        facts: FactSet,
        evidence: tuple[Evidence, ...],
    ) -> FixProposalInput | None:
        hunk_evidence = self._select_hunk(finding, evidence)
        if hunk_evidence is None:
            return None
        content = hunk_evidence.content
        assert isinstance(content, (DiffHunkEvidenceContent, CommitDiffHunkEvidenceContent))
        source_lines = tuple(
            line.text
            for line in content.lines
            if line.kind in {DiffLineKind.CONTEXT, DiffLineKind.ADDITION}
        )
        if not source_lines or len(source_lines) > MAX_PROPOSED_FIX_LINES:
            return None
        fact_ids = list(finding.supporting_fact_ids)
        for fact in facts:
            if (
                isinstance(fact, ChangedHunkOverlapsFailureLineFact)
                and finding.line_number == fact.line_number
                and paths_match(fact.file_path, finding.file_path)
                and hunk_evidence.evidence_id in fact.evidence_reference_ids
                and fact.fact_id not in fact_ids
            ):
                fact_ids.append(fact.fact_id)
        selected_facts = tuple(fact for fact in facts if fact.fact_id in fact_ids)
        if len(selected_facts) != len(fact_ids):
            return None
        evidence_ids = tuple(
            dict.fromkeys((*finding.supporting_evidence_ids, hunk_evidence.evidence_id))
        )
        error_category = next(
            (
                item.content.error_category
                for item in evidence
                if item.evidence_id in finding.supporting_evidence_ids
                and isinstance(item.content, StackFrameEvidenceContent)
                and item.content.error_category is not None
            ),
            None,
        )
        return FixProposalInput(
            finding=finding,
            hypothesis=hypothesis,
            facts=selected_facts,
            failure_error_category=error_category,
            source_evidence_id=hunk_evidence.evidence_id,
            source_line_start=content.new_start,
            source_line_end=content.new_start + content.new_count - 1,
            original_hunk="\n".join(source_lines),
            supporting_fact_ids=tuple(fact_ids),
            supporting_evidence_ids=evidence_ids,
        )

    @staticmethod
    def _select_hunk(
        finding: ValidatedCodeFinding,
        evidence: tuple[Evidence, ...],
    ) -> Evidence | None:
        candidates = []
        for item in evidence:
            content = item.content
            if not isinstance(content, (DiffHunkEvidenceContent, CommitDiffHunkEvidenceContent)):
                continue
            if not paths_match(content.file_path, finding.file_path) or content.new_count == 0:
                continue
            end = content.new_start + content.new_count - 1
            if finding.line_number is not None and not content.new_start <= finding.line_number <= end:
                continue
            candidates.append(item)
        return min(candidates, key=lambda item: item.evidence_id) if candidates else None


class TypedLLMFixProposalGenerator:
    def __init__(self, client: TypedLLMClient) -> None:
        self._client = client

    async def generate(self, proposal_input: FixProposalInput) -> ProposedCodeFixCandidate | None:
        try:
            response = await self._client.generate_typed(
                TypedLLMRequest(
                    system_instructions=FIX_PROPOSAL_SYSTEM_INSTRUCTIONS,
                    input=proposal_input,
                    output_model=FixProposalOutput,
                )
            )
        except LLMProviderError as error:
            raise CodeFixProposalError(
                CodeFixProposalFailureCode.PROVIDER_FAILURE,
                provider_details=error.details,
                provider_failure_category=error.category.value,
            ) from None
        except Exception:
            raise CodeFixProposalError(CodeFixProposalFailureCode.PROVIDER_FAILURE) from None
        try:
            structured = LLMStructuredResponse.model_validate(response)
        except (TypeError, ValidationError):
            raise CodeFixProposalError(CodeFixProposalFailureCode.INVALID_RESPONSE) from None
        try:
            return FixProposalOutput.model_validate(structured.output).candidate
        except ValidationError:
            raise CodeFixProposalError(CodeFixProposalFailureCode.CANDIDATE_SCHEMA_INVALID) from None


class DeterministicCodeFixValidator:
    def validate(
        self,
        candidate: ProposedCodeFixCandidate,
        proposal_input: FixProposalInput,
    ) -> CodeFixValidationResult:
        finding = proposal_input.finding
        reason = self._rejection_reason(candidate, proposal_input)
        if reason is not None:
            return CodeFixValidationResult(
                rejected_candidates=(RejectedCodeFix(candidate=candidate, reason=reason),)
            )
        return CodeFixValidationResult(
            accepted_fixes=(
                ProposedCodeFix(
                    fix_id="fix:" + sha256(finding.finding_id.encode()).hexdigest()[:16],
                    finding_id=finding.finding_id,
                    file_path=finding.file_path,
                    function_name=finding.function_name,
                    line_start=proposal_input.source_line_start,
                    line_end=proposal_input.source_line_end,
                    original_hunk=proposal_input.original_hunk,
                    corrected_hunk=candidate.corrected_hunk,
                    failure_mechanism=candidate.failure_mechanism,
                    fix_strategy=candidate.fix_strategy,
                    explanation=candidate.explanation,
                    supporting_fact_ids=proposal_input.supporting_fact_ids,
                    supporting_evidence_ids=proposal_input.supporting_evidence_ids,
                ),
            )
        )

    @staticmethod
    def _rejection_reason(
        candidate: ProposedCodeFixCandidate,
        proposal_input: FixProposalInput,
    ) -> CodeFixValidationFailureCode | None:
        finding = proposal_input.finding
        if candidate.finding_id != finding.finding_id:
            return CodeFixValidationFailureCode.UNKNOWN_FINDING
        if candidate.file_path != finding.file_path:
            return CodeFixValidationFailureCode.FILE_MISMATCH
        if (
            candidate.supporting_fact_ids != proposal_input.supporting_fact_ids
            or candidate.supporting_evidence_ids != proposal_input.supporting_evidence_ids
        ):
            return CodeFixValidationFailureCode.SUPPORT_MISMATCH
        lines = candidate.corrected_hunk.splitlines()
        if not lines or len(lines) > MAX_PROPOSED_FIX_LINES or (
            len(lines) > len(proposal_input.original_hunk.splitlines()) + MAX_PROPOSED_FIX_EXPANSION_LINES
        ):
            return CodeFixValidationFailureCode.OVERSIZED_REPLACEMENT
        if any(line.lstrip().startswith(("import ", "from ")) for line in lines):
            return CodeFixValidationFailureCode.UNSUPPORTED_IMPORT


        if any(line.startswith(("-", "+")) for line in lines):
            return CodeFixValidationFailureCode.DIFF_MARKER_ARTIFACT
        return None

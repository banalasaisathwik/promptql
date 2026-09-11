import ast
import builtins
import difflib
import keyword
import re
import textwrap
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from time import perf_counter_ns

from app.evals.fix_proposal.models import (
    FixProposalCaseObservation,
    FixProposalEvalCase,
    FixProposalEvalDataset,
    FixProposalEvalMetrics,
    FixProposalEvalReport,
    FixProposalEvalRunIdentity,
    FixProposalProviderBoundaryObservation,
)
from app.evals.graders import count_rate
from app.evals.models import LatencySummary, TokenSummary
from app.explanations import LLMProviderName, TypedLLMClient
from app.investigations import ChangedFileFact, ChangedFileMatchesFailureFileFact, ChangedHunkOverlapsFailureLineFact
from app.investigations import EvidenceKind, InvestigationRequest
from app.investigations.code_diagnosis import (
    CodeContextBuilder,
    CodeFindingCategory,
    CodeFixProposalError,
    CodeFixValidationFailureCode,
    DeterministicCodeFindingValidator,
    DeterministicCodeFixValidator,
    FixProposalContextBuilder,
    FixProposalInput,
    ProposedCodeFixCandidate,
    SuspectedCodeFinding,
    TypedLLMFixProposalGenerator,
)
from app.investigations.fact_derivation import derive_code_failure_facts
from app.investigations.hypotheses import (
    CandidateHypothesis,
    DeterministicHypothesisValidator,
    HypothesisKind,
)


_EVAL_REQUEST = InvestigationRequest(
    repository_owner="octo-org",
    repository_name="analytics",
    question="Why did this request fail?",
    incident_reference="incident:fix-proposal-eval",
)
_STRING_LITERAL_PATTERN = re.compile(
    r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"[^"\n]*"|\'[^\'\n]*\')'
)
_COMMENT_PATTERN = re.compile(r"#.*")


_BARE_IDENTIFIER_PATTERN = re.compile(r"(?<![.\w])[A-Za-z_][A-Za-z0-9_]*")
_ALLOWED_IDENTIFIERS = frozenset(dir(builtins)) | frozenset(keyword.kwlist) | frozenset(
    keyword.softkwlist
)


def _strip_noncode_text(source: str) -> str:
    return _COMMENT_PATTERN.sub(" ", _STRING_LITERAL_PATTERN.sub(" ", source))


def bare_identifiers(source: str) -> frozenset[str]:
    return frozenset(_BARE_IDENTIFIER_PATTERN.findall(_strip_noncode_text(source)))


def _elapsed_ms(started_at_ns: int) -> int:
    return max(0, (perf_counter_ns() - started_at_ns) // 1_000_000)


def build_proposal_input(case: FixProposalEvalCase) -> FixProposalInput | None:
    facts = derive_code_failure_facts(case.evidence)
    changed_fact = next(
        (item for item in facts if isinstance(item, ChangedFileFact)), None
    )
    relationship_fact = next(
        (
            item
            for item in facts
            if isinstance(item, ChangedFileMatchesFailureFileFact)
        ),
        None,
    )
    if changed_fact is None or relationship_fact is None:
        return None
    hunk_fact = next(
        (
            item
            for item in facts
            if isinstance(item, ChangedHunkOverlapsFailureLineFact)
        ),
        None,
    )
    supporting_fact_ids = tuple(
        fact_id
        for fact_id in (
            changed_fact.fact_id,
            relationship_fact.fact_id,
            hunk_fact.fact_id if hunk_fact is not None else None,
        )
        if fact_id is not None
    )
    hypothesis_result = DeterministicHypothesisValidator().validate(
        (
            CandidateHypothesis(
                hypothesis_id=f"hypothesis:{case.case_id}",
                kind=HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED,
                subject=case.hypothesis_subject,
                supporting_fact_ids=supporting_fact_ids,
            ),
        ),
        facts,
    )
    if not hypothesis_result.accepted_hypotheses:
        return None
    hypothesis = hypothesis_result.accepted_hypotheses[0]

    stack_evidence = next(
        item for item in case.evidence if item.kind is EvidenceKind.STACK_FRAME
    )
    supporting_evidence_ids = tuple(
        dict.fromkeys(
            evidence_id
            for fact in facts
            if fact.fact_id in hypothesis.supporting_fact_ids
            for evidence_id in fact.evidence_reference_ids
        )
    )
    finding_result = DeterministicCodeFindingValidator().validate(
        (
            SuspectedCodeFinding(
                finding_id=f"finding:{case.case_id}",
                hypothesis_id=hypothesis.hypothesis_id,
                file_path=case.expected_file_path,
                location_evidence_id=stack_evidence.evidence_id,
                category=CodeFindingCategory.CHANGED_CODE_NEAR_FAILURE,
                supporting_fact_ids=hypothesis.supporting_fact_ids,
                supporting_evidence_ids=supporting_evidence_ids,
                explanation="Deterministic eval fixture finding.",
            ),
        ),
        (hypothesis,),
        facts,
        case.evidence,
    )
    if not finding_result.accepted_findings:
        return None
    finding = finding_result.accepted_findings[0]

    diagnosis_input = CodeContextBuilder().build(
        _EVAL_REQUEST, (hypothesis,), facts, case.evidence
    )
    if not diagnosis_input.hypotheses:
        return None
    return FixProposalContextBuilder().build(
        finding, diagnosis_input.hypotheses[0], facts, case.evidence
    )


def build_fixture_candidate(
    case: FixProposalEvalCase, proposal_input: FixProposalInput
) -> ProposedCodeFixCandidate | None:
    if case.buggy_line_substring is None or case.fixed_line_substring is None:
        return None
    corrected_hunk = proposal_input.original_hunk.replace(
        case.buggy_line_substring, case.fixed_line_substring
    )
    keyword_hint = case.grounding_keywords[0]
    return ProposedCodeFixCandidate(
        finding_id=proposal_input.finding.finding_id,
        file_path=proposal_input.finding.file_path,
        corrected_hunk=corrected_hunk,
        failure_mechanism=(
            f"A {keyword_hint} occurs because the code assumes a precondition "
            "the observed runtime state does not satisfy."
        ),
        fix_strategy=(
            "Validate the assumption before using the value and handle the "
            "case where it does not hold."
        ),
        explanation=(
            "This bounded change addresses the observed failure without "
            "altering unrelated behavior."
        ),
        supporting_fact_ids=proposal_input.supporting_fact_ids,
        supporting_evidence_ids=proposal_input.supporting_evidence_ids,
    )


def _assignment_targets(corrected_hunk: str) -> frozenset[str]:
    stripped = _strip_noncode_text(corrected_hunk)
    targets: set[str] = set()
    for match in re.finditer(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=\n]+)?=(?!=)",
        stripped,
        re.MULTILINE,
    ):
        targets.add(match.group(1))
    for match in re.finditer(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b", stripped):
        targets.add(match.group(1))
    for match in re.finditer(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)\b", stripped):
        targets.add(match.group(1))
    for match in re.finditer(
        r"\bdef\s+[A-Za-z_][A-Za-z0-9_]*\s*\(([^)]*)\)", stripped
    ):
        targets.update(_BARE_IDENTIFIER_PATTERN.findall(match.group(1)))
    return frozenset(targets)


def unsupported_identifiers(original_hunk: str, corrected_hunk: str) -> tuple[str, ...]:
    original_identifiers = bare_identifiers(original_hunk)
    corrected_identifiers = bare_identifiers(corrected_hunk)
    allowed = (
        original_identifiers
        | _ALLOWED_IDENTIFIERS
        | _assignment_targets(corrected_hunk)
    )
    return tuple(sorted(corrected_identifiers - allowed))


def _failure_mechanism_grounded(failure_mechanism: str, keywords: Sequence[str]) -> bool:
    lowered = failure_mechanism.lower()
    return any(term.lower() in lowered for term in keywords)


def _minimal_edit(original_hunk: str, corrected_hunk: str) -> bool:
    original_lines = original_hunk.splitlines()
    corrected_lines = corrected_hunk.splitlines()
    matcher = difflib.SequenceMatcher(a=original_lines, b=corrected_lines, autojunk=False)
    changed = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )
    return changed <= max(3, len(original_lines) // 2 + 1)


def _syntax_valid(corrected_hunk: str) -> bool:
    try:
        ast.parse(textwrap.dedent(corrected_hunk))
    except (SyntaxError, IndentationError, TabError, ValueError):
        return False
    return True


async def observe_fix_proposal_case(
    case: FixProposalEvalCase,
    *,
    sample_number: int,
    provider: LLMProviderName,
    requested_model: str,
    client: TypedLLMClient,
) -> FixProposalCaseObservation:
    proposal_input = build_proposal_input(case)
    if proposal_input is None:
        raise ValueError(
            f"fixture case {case.case_id!r} produced no fix-proposal input; "
            "check its Evidence overlaps the stack-frame failure line"
        )

    started_at_ns = perf_counter_ns()
    candidate: ProposedCodeFixCandidate | None = None
    try:
        candidate = await TypedLLMFixProposalGenerator(client).generate(proposal_input)
    except CodeFixProposalError as error:
        failure_code = error.code.value
        provider_failure = failure_code == "provider_failure"
        boundary = FixProposalProviderBoundaryObservation(
            attempted=True,
            provider_success=not provider_failure,
            schema_valid=False,
            sanitized_failure_category=error.provider_failure_category or failure_code,
            latency_ms=_elapsed_ms(started_at_ns),
        )
        return FixProposalCaseObservation(
            case_id=case.case_id,
            category=case.category,
            sample_number=sample_number,
            provider=provider,
            requested_model=requested_model,
            boundary=boundary,
            candidate_returned=False,
            accepted=False,
            unsupported_identifier_count=0,
            corrected_identifier_count=0,
            fix_available_when_expected=(False if case.expect_fix_available else None),
            abstains_when_fix_not_grounded=(
                None if case.expect_fix_available else False
            ),
            latency_ms=_elapsed_ms(started_at_ns),
        )

    boundary = FixProposalProviderBoundaryObservation(
        attempted=True,
        provider_success=True,
        schema_valid=True,
        latency_ms=_elapsed_ms(started_at_ns),
    )

    if candidate is None:
        return FixProposalCaseObservation(
            case_id=case.case_id,
            category=case.category,
            sample_number=sample_number,
            provider=provider,
            requested_model=requested_model,
            boundary=boundary,
            candidate_returned=False,
            accepted=False,
            unsupported_identifier_count=0,
            corrected_identifier_count=0,
            fix_available_when_expected=(False if case.expect_fix_available else None),
            abstains_when_fix_not_grounded=(
                True if not case.expect_fix_available else None
            ),
            latency_ms=_elapsed_ms(started_at_ns),
        )

    validation = DeterministicCodeFixValidator().validate(candidate, proposal_input)
    accepted = bool(validation.accepted_fixes)
    rejection_reason = (
        validation.rejected_candidates[0].reason if validation.rejected_candidates else None
    )

    correct_file: bool | None = candidate.file_path == case.expected_file_path
    correct_hunk_or_location: bool | None
    if accepted:
        correct_hunk_or_location = True
    elif rejection_reason in {
        CodeFixValidationFailureCode.OVERSIZED_REPLACEMENT,
        CodeFixValidationFailureCode.DIFF_MARKER_ARTIFACT,
        CodeFixValidationFailureCode.SOURCE_CONTEXT_MISMATCH,
    }:
        correct_hunk_or_location = False
    else:
        correct_hunk_or_location = None

    new_identifiers = unsupported_identifiers(proposal_input.original_hunk, candidate.corrected_hunk)
    corrected_identifier_count = len(bare_identifiers(candidate.corrected_hunk))

    failure_mechanism_grounded = (
        _failure_mechanism_grounded(candidate.failure_mechanism, case.grounding_keywords)
        if accepted
        else None
    )
    minimal_edit = (
        _minimal_edit(proposal_input.original_hunk, candidate.corrected_hunk)
        if accepted
        else None
    )
    syntax_valid = (
        _syntax_valid(candidate.corrected_hunk)
        if accepted and case.syntax_checkable
        else None
    )

    return FixProposalCaseObservation(
        case_id=case.case_id,
        category=case.category,
        sample_number=sample_number,
        provider=provider,
        requested_model=requested_model,
        boundary=boundary,
        candidate_returned=True,
        accepted=accepted,
        rejection_reason=rejection_reason,
        correct_file=correct_file,
        correct_hunk_or_location=correct_hunk_or_location,
        failure_mechanism_grounded=failure_mechanism_grounded,
        minimal_edit=minimal_edit,
        unsupported_identifier_count=len(new_identifiers),
        corrected_identifier_count=corrected_identifier_count,
        syntax_valid=syntax_valid,
        fix_available_when_expected=(accepted if case.expect_fix_available else None),
        abstains_when_fix_not_grounded=(
            (not accepted) if not case.expect_fix_available else None
        ),
        latency_ms=_elapsed_ms(started_at_ns),
    )


def _bool_rate(values: Sequence[bool | None]) -> "tuple[int, int]":
    applicable = [value for value in values if value is not None]
    return sum(applicable), len(applicable)


def aggregate_fix_proposal_observations(
    observations: Sequence[FixProposalCaseObservation],
    *,
    planned_samples: int,
) -> FixProposalEvalMetrics:
    provider_attempted = [item.boundary for item in observations if item.boundary.attempted]
    provider_successes = sum(item.provider_success for item in provider_attempted)
    schema_successes = sum(
        item.schema_valid for item in provider_attempted if item.provider_success
    )
    provider_success_count = sum(item.provider_success for item in provider_attempted)

    correct_file_num, correct_file_den = _bool_rate([o.correct_file for o in observations])
    location_num, location_den = _bool_rate(
        [o.correct_hunk_or_location for o in observations]
    )
    grounded_num, grounded_den = _bool_rate(
        [o.failure_mechanism_grounded for o in observations]
    )
    minimal_num, minimal_den = _bool_rate([o.minimal_edit for o in observations])
    syntax_num, syntax_den = _bool_rate([o.syntax_valid for o in observations])
    available_num, available_den = _bool_rate(
        [o.fix_available_when_expected for o in observations]
    )
    abstain_num, abstain_den = _bool_rate(
        [o.abstains_when_fix_not_grounded for o in observations]
    )

    total_unsupported = sum(o.unsupported_identifier_count for o in observations)
    total_corrected_identifiers = sum(o.corrected_identifier_count for o in observations)
    unsupported_rate = (
        total_unsupported / total_corrected_identifiers
        if total_corrected_identifiers
        else 0.0
    )

    failures = Counter(
        item.sanitized_failure_category or "unexpected"
        for item in provider_attempted
        if not item.provider_success
    )
    latency_values = tuple(item.latency_ms for item in observations)

    return FixProposalEvalMetrics(
        planned_samples=planned_samples,
        completed_samples=len(observations),
        provider_success=count_rate(provider_success_count, len(provider_attempted)),
        schema_valid=count_rate(schema_successes, len(
            [item for item in provider_attempted if item.provider_success]
        )),
        correct_file=count_rate(correct_file_num, correct_file_den),
        correct_hunk_or_location=count_rate(location_num, location_den),
        failure_mechanism_grounded=count_rate(grounded_num, grounded_den),
        minimal_edit=count_rate(minimal_num, minimal_den),
        unsupported_identifier_rate=unsupported_rate,
        syntax_valid=count_rate(syntax_num, syntax_den),
        fix_available_when_expected=count_rate(available_num, available_den),
        abstains_when_fix_not_grounded=count_rate(abstain_num, abstain_den),
        provider_failures_by_category=dict(sorted(failures.items())),
        latency=LatencySummary(
            count=len(latency_values),
            minimum_ms=min(latency_values) if latency_values else None,
            maximum_ms=max(latency_values) if latency_values else None,
            mean_ms=(
                sum(latency_values) / len(latency_values) if latency_values else None
            ),
        ),


        tokens=TokenSummary(
            samples_with_usage=0,
            input_tokens=0,
            output_tokens=0,
            provider_total_tokens=0,
            samples_with_provider_total=0,
        ),
    )


async def execute_fix_proposal_eval(
    dataset: FixProposalEvalDataset,
    *,
    run_identity: FixProposalEvalRunIdentity,
    client: TypedLLMClient,
    git_commit: str | None = None,
) -> tuple[tuple[FixProposalCaseObservation, ...], FixProposalEvalReport]:
    started_at = datetime.now(UTC)
    observations: list[FixProposalCaseObservation] = []
    planned_samples = len(dataset.cases) * run_identity.samples_per_case
    for case in dataset.cases:
        for sample_number in range(1, run_identity.samples_per_case + 1):
            observations.append(
                await observe_fix_proposal_case(
                    case,
                    sample_number=sample_number,
                    provider=run_identity.provider,
                    requested_model=run_identity.requested_model,
                    client=client,
                )
            )
    observation_tuple = tuple(observations)
    metrics = aggregate_fix_proposal_observations(
        observation_tuple, planned_samples=planned_samples
    )
    release_rates = (
        ("provider_success", metrics.provider_success.rate),
        ("schema_valid", metrics.schema_valid.rate),
        ("correct_file", metrics.correct_file.rate),
        ("fix_available_when_expected", metrics.fix_available_when_expected.rate),
        ("abstains_when_fix_not_grounded", metrics.abstains_when_fix_not_grounded.rate),
    )
    failed_checks = tuple(
        name for name, rate in release_rates if rate is not None and rate != 1.0
    )
    report = FixProposalEvalReport(
        execution_completed=len(observation_tuple) == planned_samples,
        run_identity=run_identity,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        git_commit=git_commit,
        metrics=metrics,
        release_passed=not failed_checks,
        failed_checks=failed_checks,
    )
    return observation_tuple, report

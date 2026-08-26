from datetime import datetime

from pydantic import Field

from app.connectors.models import ContractModel, NonEmptyString
from app.evals.models import CountRate, EvalDatasetSplit, LatencySummary, TokenSummary
from app.explanations import LLMProviderName, LLMTokenUsage
from app.investigations import InvestigationRequest
from app.investigations.code_diagnosis import (
    CodeFindingCategory,
    DeveloperRecommendationCode,
)
from app.investigations.hypotheses import GroundedTerminationReason, HypothesisKind
from app.tools import InvestigationToolId


class InvestigationEvalCase(ContractModel):
    case_id: NonEmptyString
    request: InvestigationRequest
    relevant_evidence_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    expected_fact_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    useful_tool_ids: tuple[InvestigationToolId, ...] = Field(min_length=1)
    expected_hypothesis_kind: HypothesisKind
    expected_subject: NonEmptyString
    expected_code_category: CodeFindingCategory
    expected_recommendation_codes: tuple[DeveloperRecommendationCode, ...] = Field(
        min_length=1
    )
    sensible_termination_reasons: tuple[GroundedTerminationReason, ...] = Field(
        min_length=1
    )


class InvestigationEvalDataset(ContractModel):
    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    split: EvalDatasetSplit
    cases: tuple[InvestigationEvalCase, ...] = Field(min_length=1)


class ProviderBoundaryObservation(ContractModel):
    attempted: bool
    provider_success: bool
    schema_valid: bool
    sanitized_failure_category: NonEmptyString | None = None
    latency_ms: int = Field(ge=0)
    token_usage: LLMTokenUsage | None = None
    resolved_model: NonEmptyString | None = None


class InvestigationComponentObservation(ContractModel):
    planner_valid: bool
    planner_useful: bool
    fact_derivation_complete: bool
    fact_derivation_grounded: bool
    hypothesis_grounded: bool
    hypothesis_reference_match: bool
    code_finding_grounded: bool
    code_finding_reference_match: bool
    recommendations_grounded: bool
    recommendations_reference_match: bool
    unsupported_claims_rejected: bool


class InvestigationTrajectoryObservation(ContractModel):
    completed: bool
    generation_boundary_success: bool
    allowed_tools_only: bool
    all_plans_validated: bool
    budget_respected: bool
    round_limit_respected: bool
    relevant_evidence_discovered: bool
    facts_grounded: bool
    hypotheses_grounded: bool
    code_findings_grounded: bool
    recommendations_grounded: bool
    sensible_termination: bool
    deterministic_baseline_evidence_recall: float = Field(ge=0, le=1)
    adaptive_evidence_recall: float = Field(ge=0, le=1)
    deterministic_baseline_fact_recall: float = Field(ge=0, le=1)
    adaptive_fact_recall: float = Field(ge=0, le=1)
    termination_reason: GroundedTerminationReason | None = None


class InvestigationEvalObservation(ContractModel):
    case_id: NonEmptyString
    dataset_split: EvalDatasetSplit
    sample_number: int = Field(ge=1)
    provider: LLMProviderName
    requested_models: dict[str, NonEmptyString]
    planner: ProviderBoundaryObservation
    hypothesis: ProviderBoundaryObservation
    code_diagnosis: ProviderBoundaryObservation
    components: InvestigationComponentObservation
    trajectory: InvestigationTrajectoryObservation
    latency_ms: int = Field(ge=0)
    tokens: TokenSummary


class InvestigationEvalMetrics(ContractModel):
    planned_samples: int = Field(ge=0)
    completed_samples: int = Field(ge=0)
    provider_success: CountRate
    schema_valid: CountRate


    trajectory_generation_success: CountRate
    component_quality: CountRate
    trajectory_quality: CountRate
    component_pass_rates: dict[str, CountRate]
    trajectory_pass_rates: dict[str, CountRate]
    provider_failures_by_stage_and_category: dict[str, int]
    mean_deterministic_baseline_evidence_recall: float = Field(ge=0, le=1)
    mean_adaptive_evidence_recall: float = Field(ge=0, le=1)
    mean_deterministic_baseline_fact_recall: float = Field(ge=0, le=1)
    mean_adaptive_fact_recall: float = Field(ge=0, le=1)
    latency: LatencySummary
    tokens: TokenSummary
    estimated_cost: float | None = Field(default=None, ge=0)


class InvestigationEvalRunIdentity(ContractModel):
    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    dataset_split: EvalDatasetSplit
    provider: LLMProviderName
    requested_models: dict[str, NonEmptyString]
    samples_per_case: int = Field(ge=1)
    inter_request_delay_seconds: float = Field(ge=0)


class InvestigationEvalReport(ContractModel):
    execution_completed: bool
    run_identity: InvestigationEvalRunIdentity
    started_at: datetime
    completed_at: datetime
    git_commit: NonEmptyString | None
    metrics: InvestigationEvalMetrics
    release_passed: bool
    failed_checks: tuple[NonEmptyString, ...]

from app.evals.investigations.models import (
    InvestigationEvalCase,
    InvestigationEvalDataset,
)
from app.evals.models import EvalDatasetSplit
from app.investigations import InvestigationRequest
from app.investigations.code_diagnosis import (
    CodeFindingCategory,
    DeveloperRecommendationCode,
)
from app.investigations.hypotheses import GroundedTerminationReason, HypothesisKind
from app.tools import InvestigationToolId


CHANGED_FILE_EVIDENCE_ID = (
    "github:849ca9275d431a5c:pr:42:file:562617adbcdb5398"
)
CHANGED_HUNK_EVIDENCE_ID = (
    "github:849ca9275d431a5c:pr:42:hunk:562617adbcdb5398:1"
)
FAILURE_LOCATION_EVIDENCE_ID = "incident:checkout-500:failure-location:1"
INCIDENT_EVIDENCE_ID = "incident:checkout-500"
CHANGED_FILE_FACT_ID = "fact:changed-file:5acca6b6bb3082cf"
FAILURE_FILE_FACT_ID = "fact:changed-file-matches-failure-file:8096dd2d5ac22ba8"


# Purpose: Give both splits the same deterministic fixture contract with distinct
# questions, so holdout execution stays separate without inventing new evidence.
# Watch out: This first catalog measures one incident family; more samples improve
# repeatability for that fixture but do not create broader incident coverage.
def _case(case_id: str, question: str) -> InvestigationEvalCase:
    return InvestigationEvalCase(
        case_id=case_id,
        request=InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question=question,
            incident_reference="incident:checkout-500",
            deployment_reference="deployment:1042",
            pull_request_number=42,
            service="checkout-api",
            environment="production",
        ),
        relevant_evidence_ids=(
            CHANGED_FILE_EVIDENCE_ID,
            CHANGED_HUNK_EVIDENCE_ID,
            FAILURE_LOCATION_EVIDENCE_ID,
            INCIDENT_EVIDENCE_ID,
        ),
        expected_fact_ids=(CHANGED_FILE_FACT_ID, FAILURE_FILE_FACT_ID),
        useful_tool_ids=(
            InvestigationToolId.GET_DIFF,
            InvestigationToolId.GET_FAILURE_LOCATION,
        ),
        expected_hypothesis_kind=HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED,
        expected_subject="services/checkout.py",
        expected_code_category=CodeFindingCategory.ERROR_HANDLING_OR_NULL_PATH,
        expected_recommendation_codes=(
            DeveloperRecommendationCode.INSPECT_FAILURE_PATH,
            DeveloperRecommendationCode.VALIDATE_ERROR_HANDLING,
            DeveloperRecommendationCode.ADD_REGRESSION_TEST,
        ),
        sensible_termination_reasons=(
            GroundedTerminationReason.COMPLETED,
            GroundedTerminationReason.NO_PROGRESS,
            GroundedTerminationReason.PLANNING_LIMIT_REACHED,
            GroundedTerminationReason.BUDGET_EXHAUSTED,
        ),
    )


def build_investigation_eval_dataset(
    split: EvalDatasetSplit,
) -> InvestigationEvalDataset:
    # Key syntax: The conditional expression chooses the split-specific question,
    # while all stable Evidence/Fact labels remain centralized in `_case()`.
    case = (
        _case(
            "checkout-500-development",
            "Why did checkout start returning 500 errors?",
        )
        if split is EvalDatasetSplit.DEVELOPMENT
        else _case(
            "checkout-500-holdout",
            "Which observed code change could explain the checkout incident?",
        )
    )
    return InvestigationEvalDataset(
        dataset_id=f"v2-investigation-{split.value}",
        dataset_version="2026-08-21.1",
        split=split,
        cases=(case,),
    )

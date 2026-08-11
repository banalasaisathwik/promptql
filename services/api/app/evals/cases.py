from dataclasses import dataclass

from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import (
    CHANGES_REQUESTED_REQUEST,
    DRAFT_REQUEST,
    FAILED_CI_REQUEST,
    JIRA_IN_PROGRESS_REQUEST,
    MERGE_CONFLICT_REQUEST,
    MERGE_READY_REQUEST,
    MISSING_APPROVAL_REQUEST,
    PENDING_CI_REQUEST,
)
from app.connectors.models import (
    BlockerState,
    CheckStatus,
    ConnectorRequest,
    GitHubPullRequest,
    JiraIssue,
    JiraIssueStatus,
    Mergeability,
    PullRequestState,
    RequiredCheck,
)
from app.evals.models import EvalDatasetSplit


DEVELOPMENT_DATASET_ID = "merge-readiness-development-v1"
HOLDOUT_DATASET_ID = "merge-readiness-holdout-v1"
DATASET_VERSION = "v1"


@dataclass(frozen=True)
class ExplanationObservationCase:
    case_id: str
    github: GitHubPullRequest
    jira: JiraIssue | None


@dataclass(frozen=True)
class ExplanationEvalDataset:
    dataset_id: str
    dataset_version: str
    split: EvalDatasetSplit
    cases: tuple[ExplanationObservationCase, ...]


def _github_with(
    github: GitHubPullRequest,
    **updates: object,
) -> GitHubPullRequest:
    values = github.model_dump()
    values.update(updates)
    return GitHubPullRequest.model_validate(values)


def _jira_with(jira: JiraIssue, **updates: object) -> JiraIssue:
    values = jira.model_dump()
    values.update(updates)
    return JiraIssue.model_validate(values)


async def _facts_for(
    request: ConnectorRequest,
    github_connector: FakeGitHubConnector,
    jira_connector: FakeJiraConnector,
) -> tuple[GitHubPullRequest, JiraIssue]:
    github = await github_connector.get_pull_request(request)
    if github.linked_jira_key is None:
        raise RuntimeError("Stage 1 fixture must contain a Jira link.")
    jira = await jira_connector.get_issue(github.linked_jira_key)
    return github, jira


async def build_stage1_observation_cases() -> tuple[ExplanationObservationCase, ...]:
    github_connector = FakeGitHubConnector()
    jira_connector = FakeJiraConnector()

    fixture_cases: list[ExplanationObservationCase] = []
    for case_id, request in (
        ("ready", MERGE_READY_REQUEST),
        ("draft", DRAFT_REQUEST),
        ("failed-ci", FAILED_CI_REQUEST),
        ("pending-ci", PENDING_CI_REQUEST),
        ("missing-approval", MISSING_APPROVAL_REQUEST),
        ("changes-requested", CHANGES_REQUESTED_REQUEST),
        ("merge-conflict", MERGE_CONFLICT_REQUEST),
        ("jira-incomplete", JIRA_IN_PROGRESS_REQUEST),
    ):
        github, jira = await _facts_for(
            request,
            github_connector,
            jira_connector,
        )
        fixture_cases.append(
            ExplanationObservationCase(case_id, github, jira)
        )

    ready_github, ready_jira = await _facts_for(
        MERGE_READY_REQUEST,
        github_connector,
        jira_connector,
    )
    failed_ci_github, failed_ci_jira = await _facts_for(
        FAILED_CI_REQUEST,
        github_connector,
        jira_connector,
    )

    unknown_evidence = ExplanationObservationCase(
        case_id="unknown-mergeability",
        github=_github_with(
            ready_github,
            mergeability=Mergeability.UNKNOWN,
        ),
        jira=ready_jira,
    )
    two_blockers = ExplanationObservationCase(
        case_id="draft-and-merge-conflict",
        github=_github_with(
            ready_github,
            is_draft=True,
            mergeability=Mergeability.CONFLICTING,
        ),
        jira=ready_jira,
    )
    many_blockers_and_actions = ExplanationObservationCase(
        case_id="multiple-blockers-and-actions",
        github=_github_with(
            failed_ci_github,
            is_draft=True,
            approvals=(),
            changes_requested=True,
        ),
        jira=_jira_with(
            failed_ci_jira,
            status=JiraIssueStatus.IN_PROGRESS,
            blocker_state=BlockerState.BLOCKED,
            status_name="Development",
            is_resolved=False,
        ),
    )

    return (
        *fixture_cases,
        unknown_evidence,
        two_blockers,
        many_blockers_and_actions,
    )


def validate_eval_dataset(dataset: ExplanationEvalDataset) -> ExplanationEvalDataset:
    if dataset.dataset_version != DATASET_VERSION:
        raise ValueError("The explanation dataset version is unsupported.")
    case_ids = tuple(case.case_id for case in dataset.cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Explanation eval case IDs must be unique.")
    if not all(case_id and case_id == case_id.strip() for case_id in case_ids):
        raise ValueError("Explanation eval case IDs must be non-empty and trimmed.")
    for case in dataset.cases:
        if case.jira is not None and (
            case.github.linked_jira_key != case.jira.issue_key
        ):
            raise ValueError("GitHub and Jira eval facts must describe one issue.")
    return dataset


async def build_development_dataset() -> ExplanationEvalDataset:
    return validate_eval_dataset(
        ExplanationEvalDataset(
            dataset_id=DEVELOPMENT_DATASET_ID,
            dataset_version=DATASET_VERSION,
            split=EvalDatasetSplit.DEVELOPMENT,
            cases=await build_stage1_observation_cases(),
        )
    )


async def build_holdout_dataset() -> ExplanationEvalDataset:
    github_connector = FakeGitHubConnector()
    jira_connector = FakeJiraConnector()
    ready_github, ready_jira = await _facts_for(
        MERGE_READY_REQUEST,
        github_connector,
        jira_connector,
    )
    pending_github, pending_jira = await _facts_for(
        PENDING_CI_REQUEST,
        github_connector,
        jira_connector,
    )
    failed_github, failed_jira = await _facts_for(
        FAILED_CI_REQUEST,
        github_connector,
        jira_connector,
    )

    cases = (
        ExplanationObservationCase(
            "closed-unmerged",
            _github_with(ready_github, state=PullRequestState.CLOSED),
            ready_jira,
        ),
        ExplanationObservationCase(
            "missing-jira-link",
            _github_with(ready_github, linked_jira_key=None),
            None,
        ),
        ExplanationObservationCase(
            "required-checks-unknown",
            _github_with(
                ready_github,
                required_checks=(),
                required_checks_known=False,
            ),
            ready_jira,
        ),
        ExplanationObservationCase(
            "reviews-unknown",
            _github_with(
                ready_github,
                approvals=(),
                required_approval_count=None,
                reviews_known=False,
                changes_requested=False,
            ),
            ready_jira,
        ),
        ExplanationObservationCase(
            "pending-ci-and-jira-blocker",
            pending_github,
            _jira_with(pending_jira, blocker_state=BlockerState.BLOCKED),
        ),
        ExplanationObservationCase(
            "closed-failed-ci-and-jira-incomplete",
            _github_with(
                failed_github,
                state=PullRequestState.CLOSED,
                required_checks=(
                    RequiredCheck(name="unit-tests", status=CheckStatus.FAILED),
                ),
            ),
            _jira_with(
                failed_jira,
                status=JiraIssueStatus.IN_PROGRESS,
                status_name="Development",
                is_resolved=False,
            ),
        ),
    )
    return validate_eval_dataset(
        ExplanationEvalDataset(
            dataset_id=HOLDOUT_DATASET_ID,
            dataset_version=DATASET_VERSION,
            split=EvalDatasetSplit.HOLDOUT,
            cases=cases,
        )
    )


async def build_eval_dataset(split: EvalDatasetSplit) -> ExplanationEvalDataset:
    if split is EvalDatasetSplit.DEVELOPMENT:
        return await build_development_dataset()
    return await build_holdout_dataset()

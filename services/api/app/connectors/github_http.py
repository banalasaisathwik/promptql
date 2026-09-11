from dataclasses import dataclass
import re
from urllib.parse import quote

import httpx

from app.connectors.errors import (
    GitHubConnectorError,
    GitHubForbiddenError,
    GitHubInvalidResponseError,
    GitHubNotFoundError,
)
from app.connectors.github_http_base import (
    BaseHttpGitHubConnector,
    GitHubRequestObservation,
)
from app.connectors.github_http_models import (
    GitHubBranchProtectionResponse,
    GitHubCheckRunResponse,
    GitHubCheckRunsPageResponse,
    GitHubCommitStatusResponse,
    GitHubCommitStatusesPageResponse,
    GitHubPullRequestResponse,
    GitHubRepositoryResponse,
    GitHubReviewResponse,
    GitHubRuleResponse,
    GitHubUserResponse,
)
from app.connectors.models import (
    CheckStatus,
    ConnectorRequest,
    ConnectorSource,
    GitHubPullRequest,
    GitHubUser,
    Mergeability,
    PullRequestState,
    RequiredCheck,
)
from app.observability import FailureCategory, RuntimeTelemetry


MAX_PAGES = 10
JIRA_KEY_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z][A-Z0-9]*-[1-9][0-9]*)(?![0-9])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RequirementEvidence:
    required_check_names: tuple[str, ...]
    required_checks_known: bool
    required_approval_count: int | None


class HttpGitHubConnector(BaseHttpGitHubConnector):
    source = ConnectorSource.LIVE


    def __init__(
        self,
        client: httpx.AsyncClient,
        telemetry: RuntimeTelemetry | None = None,
        max_pages: int = MAX_PAGES,
    ) -> None:
        super().__init__(client, telemetry, max_pages)

    async def get_authenticated_context(
        self,
    ) -> tuple[str, tuple[GitHubRepositoryResponse, ...]]:
        observation = GitHubRequestObservation()
        with self._telemetry.observe_connector(
            "github", self.source.value, "get_authenticated_context"
        ) as span:
            try:
                user = await self._get_model("/user", GitHubUserResponse, observation)
                repositories = await self._get_paginated_list(
                    "/user/repos",
                    GitHubRepositoryResponse,
                    observation,
                    {"affiliation": "owner,collaborator,organization", "sort": "full_name", "direction": "asc"},
                )
            except GitHubConnectorError as error:
                span.set_attributes(
                    **{
                        "promptql.connector.result": error.category.value,
                        "promptql.http.status_class": observation.status_class,
                        "promptql.pagination.page_count": observation.page_count,
                    }
                )
                span.mark_error(FailureCategory.CONNECTOR_FAILURE)
                raise
            span.set_attributes(
                **{
                    "promptql.connector.result": "success",
                    "promptql.http.status_class": observation.status_class,
                    "promptql.pagination.page_count": observation.page_count,
                }
            )
            return user.login, repositories


    async def get_pull_request(
        self,
        request: ConnectorRequest,
    ) -> GitHubPullRequest:
        observation_data = GitHubRequestObservation()
        with self._telemetry.observe_connector(
            "github",
            self.source.value,
            "get_pull_request",
        ) as span:
            try:
                facts = await self._load_pull_request(request, observation_data)
            except GitHubConnectorError as error:
                span.set_attributes(
                    **{
                        "promptql.connector.result": error.category.value,
                        "promptql.http.status_class": observation_data.status_class,
                        "promptql.pagination.page_count": observation_data.page_count,
                    }
                )
                span.mark_error(FailureCategory.CONNECTOR_FAILURE)
                raise
            span.set_attributes(
                **{
                    "promptql.connector.result": "success",
                    "promptql.http.status_class": observation_data.status_class,
                    "promptql.pagination.page_count": observation_data.page_count,
                }
            )
            return facts


    async def _load_pull_request(
        self,
        request: ConnectorRequest,
        observation: GitHubRequestObservation,
    ) -> GitHubPullRequest:
        repository_path = self._repository_path(
            request.repository_owner,
            request.repository_name,
        )
        pull_path = f"{repository_path}/pulls/{request.pr_number}"
        raw_pull = await self._get_model(
            pull_path,
            GitHubPullRequestResponse,
            observation,
        )
        if raw_pull.number != request.pr_number:
            raise GitHubInvalidResponseError()

        reviews, reviews_known = await self._load_reviews(
            pull_path,
            observation,
        )
        requirements = await self._load_requirements(
            repository_path,
            raw_pull.base.ref,
            observation,
        )
        checks, checks_known = await self._load_required_checks(
            repository_path,
            raw_pull.head.sha,
            requirements,
            observation,
        )
        approvals, changes_requested = self._normalize_reviews(reviews)

        return GitHubPullRequest(
            pr_number=raw_pull.number,
            title=raw_pull.title,
            url=raw_pull.html_url,
            head_branch=raw_pull.head.ref,
            base_branch=raw_pull.base.ref,
            state=self._normalize_state(raw_pull),
            is_draft=raw_pull.draft,
            mergeability=self._normalize_mergeability(raw_pull.mergeable),
            required_checks=checks,
            required_checks_known=(
                requirements.required_checks_known and checks_known
            ),
            approvals=approvals,
            required_approval_count=requirements.required_approval_count,
            reviews_known=reviews_known,
            changes_requested=changes_requested,
            author=GitHubUser(login=raw_pull.user.login),
            assignees=tuple(
                GitHubUser(login=user.login) for user in raw_pull.assignees
            ),
            requested_reviewers=tuple(
                GitHubUser(login=user.login)
                for user in raw_pull.requested_reviewers
            ),
            linked_jira_key=self._find_jira_key(
                raw_pull.title,
                raw_pull.body,
                raw_pull.head.ref,
            ),
        )


    async def _load_reviews(
        self,
        pull_path: str,
        observation: GitHubRequestObservation,
    ) -> tuple[tuple[GitHubReviewResponse, ...], bool]:
        try:
            reviews = await self._get_paginated_list(
                f"{pull_path}/reviews",
                GitHubReviewResponse,
                observation,
            )
            return reviews, True
        except (GitHubForbiddenError, GitHubNotFoundError):
            return (), False


    async def _load_requirements(
        self,
        repository_path: str,
        base_branch: str,
        observation: GitHubRequestObservation,
    ) -> RequirementEvidence:
        encoded_branch = quote(base_branch, safe="")
        try:
            rules = await self._get_paginated_list(
                f"{repository_path}/rules/branches/{encoded_branch}",
                GitHubRuleResponse,
                observation,
            )
        except (GitHubForbiddenError, GitHubNotFoundError):
            return RequirementEvidence((), False, None)

        try:
            protection = await self._get_model(
                f"{repository_path}/branches/{encoded_branch}/protection",
                GitHubBranchProtectionResponse,
                observation,
            )
        except GitHubNotFoundError:
            protection = None
        except GitHubForbiddenError:
            return RequirementEvidence((), False, None)

        try:
            return self._normalize_requirements(rules, protection)
        except (KeyError, TypeError, ValueError):
            raise GitHubInvalidResponseError() from None


    async def _load_required_checks(
        self,
        repository_path: str,
        head_sha: str,
        requirements: RequirementEvidence,
        observation: GitHubRequestObservation,
    ) -> tuple[tuple[RequiredCheck, ...], bool]:
        if not requirements.required_checks_known:
            return (), False
        if not requirements.required_check_names:
            return (), True

        check_runs: tuple[GitHubCheckRunResponse, ...] = ()
        statuses: tuple[GitHubCommitStatusResponse, ...] = ()
        check_runs_known = True
        statuses_known = True
        try:
            check_runs = await self._get_paginated_object_list(
                f"{repository_path}/commits/{head_sha}/check-runs",
                GitHubCheckRunsPageResponse,
                "check_runs",
                observation,
            )
        except (GitHubForbiddenError, GitHubNotFoundError):
            check_runs_known = False
        try:
            statuses = await self._get_paginated_object_list(
                f"{repository_path}/commits/{head_sha}/status",
                GitHubCommitStatusesPageResponse,
                "statuses",
                observation,
            )
        except (GitHubForbiddenError, GitHubNotFoundError):
            statuses_known = False

        observed_statuses: dict[str, CheckStatus] = {}
        for check_run in check_runs:
            observed_statuses[check_run.name] = self._check_run_status(check_run)
        for commit_status in statuses:
            normalized = self._commit_status(commit_status.state)
            current = observed_statuses.get(commit_status.context)
            observed_statuses[commit_status.context] = self._worse_status(
                current,
                normalized,
            )

        missing_names = set(requirements.required_check_names) - observed_statuses.keys()
        if missing_names and not (check_runs_known and statuses_known):
            return (), False

        checks = tuple(
            RequiredCheck(
                name=name,
                status=observed_statuses.get(name, CheckStatus.PENDING),
            )
            for name in requirements.required_check_names
        )
        return checks, True


    @staticmethod
    def _normalize_state(pull: GitHubPullRequestResponse) -> PullRequestState:
        if pull.merged:
            return PullRequestState.MERGED
        return (
            PullRequestState.OPEN
            if pull.state == "open"
            else PullRequestState.CLOSED
        )

    @staticmethod
    def _normalize_mergeability(mergeable: bool | None) -> Mergeability:
        if mergeable is True:
            return Mergeability.MERGEABLE
        if mergeable is False:
            return Mergeability.CONFLICTING
        return Mergeability.UNKNOWN

    @staticmethod
    def _normalize_reviews(
        reviews: tuple[GitHubReviewResponse, ...],
    ) -> tuple[tuple[GitHubUser, ...], bool]:
        latest_decisive_state: dict[str, str] = {}
        for review in reviews:
            state = review.state.upper()
            if state in {"APPROVED", "CHANGES_REQUESTED"}:
                latest_decisive_state[review.user.login] = state
            elif state == "DISMISSED":
                latest_decisive_state.pop(review.user.login, None)
        approvals = tuple(
            GitHubUser(login=login)
            for login, state in sorted(latest_decisive_state.items())
            if state == "APPROVED"
        )
        changes_requested = any(
            state == "CHANGES_REQUESTED"
            for state in latest_decisive_state.values()
        )
        return approvals, changes_requested

    @staticmethod
    def _normalize_requirements(
        rules: tuple[GitHubRuleResponse, ...],
        protection: GitHubBranchProtectionResponse | None,
    ) -> RequirementEvidence:
        check_names: set[str] = set()
        approval_counts: list[int] = []
        for rule in rules:
            parameters = rule.parameters or {}
            if rule.type == "required_status_checks":
                raw_checks = parameters["required_status_checks"]
                if not isinstance(raw_checks, list):
                    raise TypeError
                for raw_check in raw_checks:
                    if not isinstance(raw_check, dict):
                        raise TypeError
                    context = raw_check["context"]
                    if not isinstance(context, str) or not context:
                        raise TypeError
                    check_names.add(context)
            elif rule.type == "pull_request":
                count = parameters["required_approving_review_count"]
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise TypeError
                approval_counts.append(count)

        if protection is not None:
            if protection.required_status_checks is not None:
                check_names.update(protection.required_status_checks.contexts)
                for raw_check in protection.required_status_checks.checks:
                    context = raw_check.get("context")
                    if not isinstance(context, str) or not context:
                        raise TypeError
                    check_names.add(context)
            if protection.required_pull_request_reviews is not None:
                approval_counts.append(
                    protection.required_pull_request_reviews.required_approving_review_count
                )

        return RequirementEvidence(
            required_check_names=tuple(sorted(check_names)),
            required_checks_known=True,
            required_approval_count=max(approval_counts, default=0),
        )

    @staticmethod
    def _check_run_status(check_run: GitHubCheckRunResponse) -> CheckStatus:
        if check_run.status != "completed" or check_run.conclusion is None:
            return CheckStatus.PENDING
        if check_run.conclusion in {"success", "neutral", "skipped"}:
            return CheckStatus.PASSED
        return CheckStatus.FAILED

    @staticmethod
    def _commit_status(state: str) -> CheckStatus:
        normalized = state.lower()
        if normalized == "success":
            return CheckStatus.PASSED
        if normalized in {"failure", "error"}:
            return CheckStatus.FAILED
        if normalized == "pending":
            return CheckStatus.PENDING
        raise GitHubInvalidResponseError()

    @staticmethod
    def _worse_status(
        current: CheckStatus | None,
        new: CheckStatus,
    ) -> CheckStatus:
        order = {
            CheckStatus.PASSED: 0,
            CheckStatus.PENDING: 1,
            CheckStatus.FAILED: 2,
        }
        if current is None or order[new] > order[current]:
            return new
        return current

    @staticmethod
    def _find_jira_key(title: str, body: str | None, branch: str) -> str | None:
        for candidate in (title, body or "", branch):
            match = JIRA_KEY_PATTERN.search(candidate)
            if match is not None:
                return match.group(1).upper()
        return None

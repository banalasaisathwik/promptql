from dataclasses import dataclass
import re
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from app.connectors.errors import (
    GitHubConnectorError,
    GitHubForbiddenError,
    GitHubInvalidResponseError,
    GitHubNotFoundError,
    GitHubRateLimitedError,
    GitHubTimeoutError,
    GitHubUnauthorizedError,
    GitHubUpstreamUnavailableError,
)
from app.connectors.github_http_models import (
    GitHubBranchProtectionResponse,
    GitHubCheckRunResponse,
    GitHubCheckRunsPageResponse,
    GitHubCommitStatusResponse,
    GitHubCommitStatusesPageResponse,
    GitHubPullRequestResponse,
    GitHubReviewResponse,
    GitHubRuleResponse,
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
from app.observability import FailureCategory, NoOpRuntimeTelemetry, RuntimeTelemetry


GITHUB_API_VERSION = "2026-03-10"
MAX_PAGES = 10
PAGE_SIZE = 100
JIRA_KEY_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z][A-Z0-9]*-[1-9][0-9]*)(?![0-9])",
    re.IGNORECASE,
)
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


@dataclass
class RequestObservation:
    page_count: int = 0
    status_class: str = "none"


@dataclass(frozen=True)
class RequirementEvidence:
    required_check_names: tuple[str, ...]
    required_checks_known: bool
    required_approval_count: int | None


class HttpGitHubConnector:
    source = ConnectorSource.LIVE


    def __init__(
        self,
        client: httpx.AsyncClient,
        telemetry: RuntimeTelemetry | None = None,
        max_pages: int = MAX_PAGES,
    ) -> None:
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self._client = client
        self._telemetry = telemetry or NoOpRuntimeTelemetry()
        self._max_pages = max_pages


    async def aclose(self) -> None:
        await self._client.aclose()


    async def get_pull_request(
        self,
        request: ConnectorRequest,
    ) -> GitHubPullRequest:
        observation_data = RequestObservation()
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
        observation: RequestObservation,
    ) -> GitHubPullRequest:
        repository_path = self._repository_path(request)
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


    @staticmethod
    def _repository_path(request: ConnectorRequest) -> str:
        owner = quote(request.repository_owner, safe="")
        repository = quote(request.repository_name, safe="")
        return f"/repos/{owner}/{repository}"


    async def _load_reviews(
        self,
        pull_path: str,
        observation: RequestObservation,
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
        observation: RequestObservation,
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
        observation: RequestObservation,
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


    async def _get_model(
        self,
        path: str,
        model_type: type[ResponseModel],
        observation: RequestObservation,
        params: dict[str, int | str] | None = None,
    ) -> ResponseModel:
        payload = await self._request_json(path, observation, params)
        try:
            return model_type.model_validate(payload)
        except ValidationError:
            raise GitHubInvalidResponseError() from None


    async def _get_paginated_list(
        self,
        path: str,
        model_type: type[ResponseModel],
        observation: RequestObservation,
    ) -> tuple[ResponseModel, ...]:
        results: list[ResponseModel] = []
        for page in range(1, self._max_pages + 1):
            observation.page_count += 1
            payload = await self._request_json(
                path,
                observation,
                {"per_page": PAGE_SIZE, "page": page},
            )
            if not isinstance(payload, list):
                raise GitHubInvalidResponseError()
            try:
                page_results = [model_type.model_validate(value) for value in payload]
            except ValidationError:
                raise GitHubInvalidResponseError() from None
            results.extend(page_results)
            if len(page_results) < PAGE_SIZE:
                return tuple(results)
        raise GitHubInvalidResponseError()


    async def _get_paginated_object_list(
        self,
        path: str,
        page_model: type[BaseModel],
        list_field: str,
        observation: RequestObservation,
    ) -> tuple[Any, ...]:
        results: list[Any] = []
        total_count: int | None = None
        for page in range(1, self._max_pages + 1):
            observation.page_count += 1
            response_page = await self._get_model(
                path,
                page_model,
                observation,
                {"per_page": PAGE_SIZE, "page": page},
            )
            page_results = getattr(response_page, list_field)
            total_count = response_page.total_count
            results.extend(page_results)
            if len(results) >= total_count or len(page_results) < PAGE_SIZE:
                return tuple(results)
        raise GitHubInvalidResponseError()


    async def _request_json(
        self,
        path: str,
        observation: RequestObservation,
        params: dict[str, int | str] | None = None,
    ) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException:
            raise GitHubTimeoutError() from None
        except httpx.RequestError:
            raise GitHubUpstreamUnavailableError() from None

        observation.status_class = f"{response.status_code // 100}xx"
        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError:
            raise GitHubInvalidResponseError() from None


    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        rate_limited = (
            status in {403, 429}
            and (
                response.headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in response.headers
                or status == 429
            )
        )
        if rate_limited:
            raise GitHubRateLimitedError()
        if status == 401:
            raise GitHubUnauthorizedError()
        if status == 403:
            raise GitHubForbiddenError()
        if status == 404:
            raise GitHubNotFoundError()
        if 500 <= status <= 599:
            raise GitHubUpstreamUnavailableError()
        if not 200 <= status <= 299:
            raise GitHubInvalidResponseError()


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

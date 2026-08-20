from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, TypeAdapter, ValidationError

from app.connectors.errors import (
    GitHubConnectorError,
    GitHubForbiddenError,
    GitHubIncompleteResultError,
    GitHubInvalidResponseError,
    GitHubNotFoundError,
    GitHubRateLimitedError,
    GitHubTimeoutError,
    GitHubUnauthorizedError,
    GitHubUpstreamUnavailableError,
)
from app.connectors.github_code_http_models import (
    GitHubChangedFileResponse,
    GitHubCodePullRequestResponse,
    GitHubCommitEvidenceResponse,
)
from app.connectors.github_diff import ParsedDiffHunk, parse_github_patch
from app.connectors.models import (
    ConnectorSource,
    GitHubCommitEvidenceRequest,
    GitHubPullRequestEvidenceRequest,
    PullRequestState,
)
from app.investigations import (
    ChangedFileEvidenceContent,
    CommitEvidenceContent,
    DiffHunkEvidenceContent,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    FileChangeType,
    PullRequestEvidenceContent,
)
from app.observability import FailureCategory, NoOpRuntimeTelemetry, RuntimeTelemetry


PAGE_SIZE = 100
MAX_FILE_PAGES = 10
MAX_EVIDENCE_TEXT_CHARACTERS = 4096
MAX_COMMIT_PARENTS = 100
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
AwareDatetimeAdapter = TypeAdapter(AwareDatetime)
Clock = Callable[[], datetime]


@dataclass
class CodeEvidenceObservation:
    page_count: int = 0
    status_class: str = "none"


class HttpGitHubCodeEvidenceSource:
    source = ConnectorSource.LIVE

    def __init__(
        self,
        client: httpx.AsyncClient,
        telemetry: RuntimeTelemetry | None = None,
        *,
        max_file_pages: int = MAX_FILE_PAGES,
        clock: Clock | None = None,
    ) -> None:
        if max_file_pages <= 0:
            raise ValueError("max_file_pages must be positive")
        self._client = client
        self._telemetry = telemetry or NoOpRuntimeTelemetry()
        self._max_file_pages = max_file_pages
        self._clock = clock or (lambda: datetime.now(UTC))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_commit_evidence(
        self,
        request: GitHubCommitEvidenceRequest,
    ) -> Evidence:
        observation = CodeEvidenceObservation()
        with self._telemetry.observe_connector(
            "github",
            self.source.value,
            "get_commit_evidence",
        ) as span:
            try:
                evidence = await self._load_commit_evidence(request, observation)
            except GitHubConnectorError as error:
                self._record_failure(span, observation, error)
                raise
            self._record_success(span, observation)
            return evidence

    async def get_pull_request_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
    ) -> Evidence:
        observation = CodeEvidenceObservation()
        with self._telemetry.observe_connector(
            "github",
            self.source.value,
            "get_pull_request_evidence",
        ) as span:
            try:
                evidence = await self._load_pull_request_evidence(request, observation)
            except GitHubConnectorError as error:
                self._record_failure(span, observation, error)
                raise
            self._record_success(span, observation)
            return evidence

    async def get_changed_file_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
    ) -> tuple[Evidence, ...]:
        observation = CodeEvidenceObservation()
        with self._telemetry.observe_connector(
            "github",
            self.source.value,
            "get_changed_file_evidence",
        ) as span:
            try:
                evidence = await self._load_changed_file_evidence(
                    request,
                    observation,
                )
            except GitHubConnectorError as error:
                self._record_failure(span, observation, error)
                raise
            self._record_success(span, observation)
            return evidence

    async def _load_commit_evidence(
        self,
        request: GitHubCommitEvidenceRequest,
        observation: CodeEvidenceObservation,
    ) -> Evidence:
        repository_path = self._repository_path(
            request.repository_owner,
            request.repository_name,
        )
        raw_commit = await self._get_model(
            f"{repository_path}/commits/{quote(request.commit_sha, safe='')}",
            GitHubCommitEvidenceResponse,
            observation,
        )
        if raw_commit.sha.lower() != request.commit_sha.lower():
            raise GitHubInvalidResponseError()
        if len(raw_commit.commit.message) > MAX_EVIDENCE_TEXT_CHARACTERS:
            raise GitHubIncompleteResultError()
        if len(raw_commit.parents) > MAX_COMMIT_PARENTS:
            raise GitHubIncompleteResultError()

        try:
            authored_at = self._parse_optional_datetime(
                raw_commit.commit.author.date
                if raw_commit.commit.author is not None
                else None
            )
            repository_digest = self._digest(
                f"{request.repository_owner}/{request.repository_name}"
            )
            return Evidence(
                evidence_id=(
                    f"github:{repository_digest}:commit:{raw_commit.sha.lower()}"
                ),
                source=EvidenceSource.GITHUB,
                kind=EvidenceKind.COMMIT,
                provenance=EvidenceProvenance(
                    source_reference=(
                        f"github:{request.repository_owner}/{request.repository_name}"
                        f":commit:{raw_commit.sha.lower()}"
                    ),
                    observed_at=authored_at,
                    retrieved_at=self._clock(),
                ),
                content=CommitEvidenceContent(
                    repository_owner=request.repository_owner,
                    repository_name=request.repository_name,
                    commit_sha=raw_commit.sha.lower(),
                    message=raw_commit.commit.message,
                    authored_at=authored_at,
                    parent_shas=tuple(
                        parent.sha.lower() for parent in raw_commit.parents
                    ),
                ),
            )
        except ValidationError:
            raise GitHubInvalidResponseError() from None

    async def _load_pull_request_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
        observation: CodeEvidenceObservation,
    ) -> Evidence:
        repository_path = self._repository_path(
            request.repository_owner,
            request.repository_name,
        )
        raw_pull = await self._get_model(
            f"{repository_path}/pulls/{request.pr_number}",
            GitHubCodePullRequestResponse,
            observation,
        )
        if raw_pull.number != request.pr_number:
            raise GitHubInvalidResponseError()

        try:
            repository_digest = self._digest(
                f"{request.repository_owner}/{request.repository_name}"
            )
            return Evidence(
                evidence_id=f"github:{repository_digest}:pr:{raw_pull.number}",
                source=EvidenceSource.GITHUB,
                kind=EvidenceKind.PULL_REQUEST,
                provenance=EvidenceProvenance(
                    source_reference=(
                        f"github:{request.repository_owner}/{request.repository_name}"
                        f":pull:{raw_pull.number}"
                    ),
                    observed_at=None,
                    retrieved_at=self._clock(),
                ),
                content=PullRequestEvidenceContent(
                    repository_owner=request.repository_owner,
                    repository_name=request.repository_name,
                    pull_request_number=raw_pull.number,
                    title=raw_pull.title,
                    state=self._pull_request_state(raw_pull),
                    base_sha=raw_pull.base.sha.lower(),
                    head_sha=raw_pull.head.sha.lower(),
                    merge_commit_sha=(
                        raw_pull.merge_commit_sha.lower()
                        if raw_pull.merge_commit_sha is not None
                        else None
                    ),
                ),
            )
        except ValidationError:
            raise GitHubInvalidResponseError() from None

    async def _load_changed_file_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
        observation: CodeEvidenceObservation,
    ) -> tuple[Evidence, ...]:
        repository_path = self._repository_path(
            request.repository_owner,
            request.repository_name,
        )
        raw_files = await self._get_paginated_list(
            f"{repository_path}/pulls/{request.pr_number}/files",
            GitHubChangedFileResponse,
            observation,
        )
        retrieved_at = self._clock()
        normalized: list[Evidence] = []
        for raw_file in raw_files:
            try:
                file_evidence = self._normalize_changed_file(
                    request,
                    raw_file,
                    retrieved_at,
                )
                normalized.append(file_evidence)
                if raw_file.patch is not None:
                    hunks = parse_github_patch(raw_file.patch)
                    normalized.extend(
                        self._normalize_hunk(
                            request,
                            raw_file.filename,
                            hunk,
                            hunk_index,
                            retrieved_at,
                        )
                        for hunk_index, hunk in enumerate(hunks, start=1)
                    )
            except ValidationError:
                raise GitHubInvalidResponseError() from None
        return tuple(normalized)

    def _normalize_changed_file(
        self,
        request: GitHubPullRequestEvidenceRequest,
        raw_file: GitHubChangedFileResponse,
        retrieved_at: datetime,
    ) -> Evidence:
        repository_digest = self._digest(
            f"{request.repository_owner}/{request.repository_name}"
        )
        path_digest = self._digest(raw_file.filename)
        return Evidence(
            evidence_id=(
                f"github:{repository_digest}:pr:{request.pr_number}"
                f":file:{path_digest}"
            ),
            source=EvidenceSource.GITHUB,
            kind=EvidenceKind.CHANGED_FILE,
            provenance=EvidenceProvenance(
                source_reference=(
                    f"github:{request.repository_owner}/{request.repository_name}"
                    f":pull:{request.pr_number}:file-sha256:{path_digest}"
                ),
                observed_at=None,
                retrieved_at=retrieved_at,
            ),
            content=ChangedFileEvidenceContent(
                repository_owner=request.repository_owner,
                repository_name=request.repository_name,
                pull_request_number=request.pr_number,
                path=raw_file.filename,
                change_type=self._file_change_type(raw_file.status),
                previous_path=raw_file.previous_filename,
                additions=raw_file.additions,
                deletions=raw_file.deletions,
                changes=raw_file.changes,
                patch_available=raw_file.patch is not None,
            ),
        )

    def _normalize_hunk(
        self,
        request: GitHubPullRequestEvidenceRequest,
        file_path: str,
        hunk: ParsedDiffHunk,
        hunk_index: int,
        retrieved_at: datetime,
    ) -> Evidence:
        repository_digest = self._digest(
            f"{request.repository_owner}/{request.repository_name}"
        )
        path_digest = self._digest(file_path)
        identity_prefix = (
            f"github:{repository_digest}:pr:{request.pr_number}"
            f":hunk:{path_digest}:{hunk_index}"
        )
        return Evidence(
            evidence_id=identity_prefix,
            source=EvidenceSource.GITHUB,
            kind=EvidenceKind.DIFF_HUNK,
            provenance=EvidenceProvenance(
                source_reference=identity_prefix,
                observed_at=None,
                retrieved_at=retrieved_at,
            ),
            content=DiffHunkEvidenceContent(
                repository_owner=request.repository_owner,
                repository_name=request.repository_name,
                pull_request_number=request.pr_number,
                file_path=file_path,
                old_start=hunk.old_start,
                old_count=hunk.old_count,
                new_start=hunk.new_start,
                new_count=hunk.new_count,
                lines=hunk.lines,
            ),
        )

    async def _get_model(
        self,
        path: str,
        model_type: type[ResponseModel],
        observation: CodeEvidenceObservation,
    ) -> ResponseModel:
        payload = await self._request_json(path, observation)
        try:
            return model_type.model_validate(payload)
        except ValidationError:
            raise GitHubInvalidResponseError() from None

    async def _get_paginated_list(
        self,
        path: str,
        model_type: type[ResponseModel],
        observation: CodeEvidenceObservation,
    ) -> tuple[ResponseModel, ...]:
        results: list[ResponseModel] = []


        for page in range(1, self._max_file_pages + 1):
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
        raise GitHubIncompleteResultError()

    async def _request_json(
        self,
        path: str,
        observation: CodeEvidenceObservation,
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
    def _repository_path(repository_owner: str, repository_name: str) -> str:
        owner = quote(repository_owner, safe="")
        repository = quote(repository_name, safe="")
        return f"/repos/{owner}/{repository}"

    @staticmethod
    def _pull_request_state(
        raw_pull: GitHubCodePullRequestResponse,
    ) -> PullRequestState:
        if raw_pull.merged:
            return PullRequestState.MERGED
        return (
            PullRequestState.OPEN
            if raw_pull.state == "open"
            else PullRequestState.CLOSED
        )

    @staticmethod
    def _file_change_type(status: str) -> FileChangeType:
        normalized = {
            "added": FileChangeType.ADDED,
            "modified": FileChangeType.MODIFIED,
            "removed": FileChangeType.DELETED,
            "renamed": FileChangeType.RENAMED,
        }.get(status)
        if normalized is None:
            raise GitHubInvalidResponseError()
        return normalized

    @staticmethod
    def _parse_optional_datetime(value: str | None) -> datetime | None:
        if value is None:
            return None
        try:
            return AwareDatetimeAdapter.validate_python(value)
        except ValidationError:
            raise GitHubInvalidResponseError() from None

    @staticmethod
    def _digest(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _record_success(span: Any, observation: CodeEvidenceObservation) -> None:
        span.set_attributes(
            **{
                "promptql.connector.result": "success",
                "promptql.http.status_class": observation.status_class,
                "promptql.pagination.page_count": observation.page_count,
            }
        )

    @staticmethod
    def _record_failure(
        span: Any,
        observation: CodeEvidenceObservation,
        error: GitHubConnectorError,
    ) -> None:
        span.set_attributes(
            **{
                "promptql.connector.result": error.category.value,
                "promptql.http.status_class": observation.status_class,
                "promptql.pagination.page_count": observation.page_count,
            }
        )
        span.mark_error(FailureCategory.CONNECTOR_FAILURE)

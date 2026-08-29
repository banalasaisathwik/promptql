from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, TypeAdapter, ValidationError

from app.connectors.errors import (
    SentryConnectorError,
    SentryDeployNotFoundError,
    SentryForbiddenError,
    SentryInvalidDeploymentReferenceError,
    SentryInvalidResponseError,
    SentryNotFoundError,
    SentryRateLimitedError,
    SentryReleaseMissingCommitError,
    SentryTimeoutError,
    SentryUnauthorizedError,
    SentryUnsupportedTelemetrySignalError,
    SentryUpstreamUnavailableError,
)
from app.connectors.models import (
    ConnectorSource,
    DeploymentEvidenceRequest,
    FailureLocationEvidenceRequest,
    IncidentEvidenceRequest,
    TelemetrySignal,
    TelemetryWindowEvidenceRequest,
)
from app.connectors.sentry_http_models import (
    SentryDeployResponse,
    SentryEventResponse,
    SentryEventsStatsResponse,
    SentryExceptionEntryDataResponse,
    SentryIssueResponse,
    SentryReleaseResponse,
    SentryResponseModel,
    SentryShortIdResponse,
)
from app.investigations import (
    DeploymentEvidenceContent,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    IncidentEvidenceContent,
    IncidentStatus,
    StackFrameEvidenceContent,
    TelemetryWindowEvidenceContent,
)
from app.observability import FailureCategory, NoOpRuntimeTelemetry, RuntimeTelemetry


AwareDatetimeAdapter = TypeAdapter(AwareDatetime)
Clock = Callable[[], datetime]


_SIGNAL_QUERY_FRAGMENTS: dict[TelemetrySignal, str] = {
    TelemetrySignal.ERROR_EVENTS: "event.type:error",
}

_ISSUE_STATUS_TO_INCIDENT_STATUS: dict[str, IncidentStatus] = {
    "unresolved": IncidentStatus.ACTIVE,
    "resolved": IncidentStatus.RESOLVED,
    "ignored": IncidentStatus.UNKNOWN,
}


@dataclass(frozen=True)
class _CrashFrame:
    exception_type: str | None
    filename: str | None
    function: str | None
    line_number: int | None


class HttpSentrySource:
    source = ConnectorSource.LIVE

    def __init__(
        self,
        client: httpx.AsyncClient,
        organization_slug: str,
        telemetry: RuntimeTelemetry | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._client = client
        self._organization_path = quote(organization_slug, safe="")
        self._telemetry = telemetry or NoOpRuntimeTelemetry()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_incident_evidence(
        self,
        request: IncidentEvidenceRequest,
    ) -> Evidence:
        with self._telemetry.observe_connector(
            "sentry",
            self.source.value,
            "get_incident_evidence",
        ) as span:
            try:
                evidence = await self._load_incident_evidence(request)
            except SentryConnectorError as error:
                self._record_failure(span, error)
                raise
            self._record_success(span)
            return evidence

    async def get_deployment_evidence(
        self,
        request: DeploymentEvidenceRequest,
    ) -> Evidence:
        with self._telemetry.observe_connector(
            "sentry",
            self.source.value,
            "get_deployment_evidence",
        ) as span:
            try:
                evidence = await self._load_deployment_evidence(request)
            except SentryConnectorError as error:
                self._record_failure(span, error)
                raise
            self._record_success(span)
            return evidence

    async def get_failure_location_evidence(
        self,
        request: FailureLocationEvidenceRequest,
    ) -> Evidence:
        with self._telemetry.observe_connector(
            "sentry",
            self.source.value,
            "get_failure_location_evidence",
        ) as span:
            try:
                evidence = await self._load_failure_location_evidence(request)
            except SentryConnectorError as error:
                self._record_failure(span, error)
                raise
            self._record_success(span)
            return evidence

    async def get_telemetry_window_evidence(
        self,
        request: TelemetryWindowEvidenceRequest,
    ) -> Evidence:
        with self._telemetry.observe_connector(
            "sentry",
            self.source.value,
            "get_telemetry_window_evidence",
        ) as span:
            try:
                evidence = await self._load_telemetry_window_evidence(request)
            except SentryConnectorError as error:
                self._record_failure(span, error)
                raise
            self._record_success(span)
            return evidence

    async def _load_incident_evidence(
        self,
        request: IncidentEvidenceRequest,
    ) -> Evidence:
        raw_issue, _issue_id = await self._resolve_issue(request.incident_reference)
        started_at = self._parse_datetime(raw_issue.firstSeen)
        try:
            return Evidence(
                evidence_id=f"sentry:issue:{raw_issue.id}",
                source=EvidenceSource.INCIDENT,
                kind=EvidenceKind.INCIDENT,
                provenance=EvidenceProvenance(
                    source_reference=f"sentry:issue:{raw_issue.id}",
                    observed_at=started_at,
                    retrieved_at=self._clock(),
                ),
                content=IncidentEvidenceContent(
                    incident_reference=request.incident_reference,
                    service=raw_issue.project.slug,


                    environment=None,
                    started_at=started_at,
                    status=_ISSUE_STATUS_TO_INCIDENT_STATUS[raw_issue.status],
                    category=None,
                ),
            )
        except ValidationError:
            raise SentryInvalidResponseError() from None

    async def _load_deployment_evidence(
        self,
        request: DeploymentEvidenceRequest,
    ) -> Evidence:
        version, environment = self._parse_deployment_reference(
            request.deployment_reference
        )
        encoded_version = quote(version, safe="")
        release_path = (
            f"/organizations/{self._organization_path}/releases/{encoded_version}/"
        )
        raw_release = await self._get_model(release_path, SentryReleaseResponse)
        if raw_release.lastCommit is None:
            raise SentryReleaseMissingCommitError()
        if not raw_release.projects:
            raise SentryInvalidResponseError()

        deploy = await self._load_matching_deploy(release_path, environment)
        if deploy.dateFinished is None:
            raise SentryInvalidResponseError()
        deployed_at = self._parse_datetime(deploy.dateFinished)

        try:
            return Evidence(


                evidence_id=(
                    f"sentry:release:{self._digest(raw_release.version)}"
                    f":{self._digest(environment)}"
                ),
                source=EvidenceSource.DEPLOYMENT,
                kind=EvidenceKind.DEPLOYMENT,
                provenance=EvidenceProvenance(
                    source_reference=(
                        f"sentry:release:{raw_release.version}:{environment}"
                    ),
                    observed_at=deployed_at,
                    retrieved_at=self._clock(),
                ),
                content=DeploymentEvidenceContent(
                    deployment_reference=request.deployment_reference,
                    service=raw_release.projects[0].slug,
                    environment=environment,
                    commit_sha=raw_release.lastCommit.id,
                    deployed_at=deployed_at,
                ),
            )
        except ValidationError:
            raise SentryInvalidResponseError() from None

    async def _load_matching_deploy(
        self,
        release_path: str,
        environment: str,
    ) -> SentryDeployResponse:
        payload = await self._get_json(f"{release_path}deploys/")
        if not isinstance(payload, list):
            raise SentryInvalidResponseError()
        try:
            deploys = [SentryDeployResponse.model_validate(item) for item in payload]
        except ValidationError:
            raise SentryInvalidResponseError() from None
        matching = [
            deploy for deploy in deploys if deploy.environment == environment
        ]
        if len(matching) != 1:
            raise SentryDeployNotFoundError()
        return matching[0]

    async def _load_failure_location_evidence(
        self,
        request: FailureLocationEvidenceRequest,
    ) -> Evidence:
        _raw_issue, issue_id = await self._resolve_issue(request.incident_reference)
        raw_event = await self._get_model(
            f"/organizations/{self._organization_path}/issues/{issue_id}"
            f"/events/latest/",
            SentryEventResponse,
            params={"full": "true"},
        )
        crash_frame = self._extract_crash_frame(raw_event)
        if crash_frame is None:
            raise SentryInvalidResponseError()

        try:
            return Evidence(


                evidence_id=(
                    f"sentry:issue:{self._digest(request.incident_reference)}"
                    f":failure-location:{raw_event.eventID}"
                ),
                source=EvidenceSource.INCIDENT,
                kind=EvidenceKind.STACK_FRAME,
                provenance=EvidenceProvenance(
                    source_reference=f"sentry:event:{raw_event.eventID}",
                    observed_at=None,
                    retrieved_at=self._clock(),
                ),
                content=StackFrameEvidenceContent(


                    service=None,
                    error_category=crash_frame.exception_type,
                    file_path=crash_frame.filename,
                    function_name=crash_frame.function,
                    line_number=crash_frame.line_number,
                ),
            )
        except ValidationError:
            raise SentryInvalidResponseError() from None

    async def _resolve_issue(
        self,
        incident_reference: str,
    ) -> tuple[SentryIssueResponse, str]:
        encoded_reference = quote(incident_reference, safe="")
        try:
            issue = await self._get_model(
                f"/organizations/{self._organization_path}/issues/{encoded_reference}/",
                SentryIssueResponse,
            )
            return issue, issue.id
        except SentryNotFoundError:
            resolved = await self._get_model(
                f"/organizations/{self._organization_path}/shortids/"
                f"{encoded_reference}/",
                SentryShortIdResponse,
            )
            return resolved.group, resolved.groupId

    async def _load_telemetry_window_evidence(
        self,
        request: TelemetryWindowEvidenceRequest,
    ) -> Evidence:
        query_fragment = _SIGNAL_QUERY_FRAGMENTS.get(request.signal)
        if query_fragment is None:
            raise SentryUnsupportedTelemetrySignalError()
        query_parts = [query_fragment] + [
            f"{filter_.key}:{filter_.value}" for filter_ in request.filters
        ]
        raw_stats = await self._get_model(
            f"/organizations/{self._organization_path}/events-stats/",
            SentryEventsStatsResponse,
            params={
                "project": request.service,
                "query": " ".join(query_parts),
                "yAxis": "count()",
                "start": request.start_time.astimezone(UTC).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
                "end": request.end_time.astimezone(UTC).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
            },
        )
        event_count = sum(
            bucket_value.count
            for _, bucket_values in raw_stats.data
            for bucket_value in bucket_values
        )

        try:
            return Evidence(


                evidence_id=(
                    f"sentry:telemetry:{self._digest(request.service)}"
                    f":{request.signal.value}"
                    f":{request.start_time.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}"
                ),
                source=EvidenceSource.TELEMETRY,
                kind=EvidenceKind.TELEMETRY_WINDOW,
                provenance=EvidenceProvenance(
                    source_reference=(
                        f"sentry:telemetry:{request.service}:{request.signal.value}"
                        f":{request.start_time.isoformat()}"
                    ),
                    observed_at=None,
                    retrieved_at=self._clock(),
                ),
                content=TelemetryWindowEvidenceContent(
                    service=request.service,
                    signal=request.signal,
                    start_time=request.start_time,
                    end_time=request.end_time,
                    filters=request.filters,
                    event_count=event_count,
                ),
            )
        except ValidationError:
            raise SentryInvalidResponseError() from None

    @staticmethod
    def _extract_crash_frame(raw_event: SentryEventResponse) -> _CrashFrame | None:
        exception_entry = next(
            (entry for entry in raw_event.entries if entry.type == "exception"),
            None,
        )
        if exception_entry is None:
            return None
        try:
            exception_data = SentryExceptionEntryDataResponse.model_validate(
                exception_entry.data
            )
        except ValidationError:
            raise SentryInvalidResponseError() from None
        if not exception_data.values:
            return None
        exception_value = exception_data.values[0]
        if (
            exception_value.stacktrace is None
            or not exception_value.stacktrace.frames
        ):
            return None


        crash_frame = exception_value.stacktrace.frames[-1]
        return _CrashFrame(
            exception_type=exception_value.type,
            filename=crash_frame.filename,
            function=crash_frame.function,
            line_number=crash_frame.lineNo,
        )

    @staticmethod
    def _parse_deployment_reference(deployment_reference: str) -> tuple[str, str]:
        version, separator, environment = deployment_reference.rpartition(":")
        if not separator or not version or not environment:
            raise SentryInvalidDeploymentReferenceError()
        return version, environment

    @staticmethod
    def _digest(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        try:
            return AwareDatetimeAdapter.validate_python(value)
        except ValidationError:
            raise SentryInvalidResponseError() from None

    async def _get_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException:
            raise SentryTimeoutError() from None
        except httpx.RequestError:
            raise SentryUpstreamUnavailableError() from None
        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError:
            raise SentryInvalidResponseError() from None

    async def _get_model[ResponseModel: SentryResponseModel](
        self,
        path: str,
        model_type: type[ResponseModel],
        params: dict[str, str] | None = None,
    ) -> ResponseModel:
        payload = await self._get_json(path, params)
        try:
            return model_type.model_validate(payload)
        except ValidationError:
            raise SentryInvalidResponseError() from None

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status == 401:
            raise SentryUnauthorizedError()
        if status == 403:
            raise SentryForbiddenError()
        if status == 404:
            raise SentryNotFoundError()
        if status == 429:
            raise SentryRateLimitedError()
        if 500 <= status <= 599:
            raise SentryUpstreamUnavailableError()
        if not 200 <= status <= 299:
            raise SentryInvalidResponseError()

    @staticmethod
    def _record_success(span: Any) -> None:
        span.set_attributes(
            **{
                "promptql.connector.result": "success",
            }
        )

    @staticmethod
    def _record_failure(span: Any, error: SentryConnectorError) -> None:
        span.set_attributes(
            **{
                "promptql.connector.result": error.category.value,
            }
        )
        span.mark_error(FailureCategory.CONNECTOR_FAILURE)

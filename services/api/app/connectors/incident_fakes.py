from collections.abc import Mapping
from datetime import UTC, datetime

from app.connectors.errors import FixtureNotFoundError
from app.connectors.models import (
    ConnectorSource,
    DeploymentEvidenceRequest,
    FailureLocationEvidenceRequest,
    IncidentEvidenceRequest,
    TelemetryFilter,
    TelemetrySignal,
    TelemetryWindowEvidenceRequest,
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


FIXTURE_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
INCIDENT_STARTED_AT = datetime(2026, 8, 17, 11, 42, tzinfo=UTC)
DEPLOYED_AT = datetime(2026, 8, 17, 11, 30, tzinfo=UTC)
WINDOW_START = datetime(2026, 8, 17, 11, 40, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 17, 11, 45, tzinfo=UTC)
COMMIT_SHA = "a" * 40

INCIDENT_REQUEST = IncidentEvidenceRequest(incident_reference="incident:checkout-500")
DEPLOYMENT_REQUEST = DeploymentEvidenceRequest(deployment_reference="deployment:1042")
FAILURE_LOCATION_REQUEST = FailureLocationEvidenceRequest(
    incident_reference="incident:checkout-500"
)
TELEMETRY_REQUEST = TelemetryWindowEvidenceRequest(
    service="checkout-api",
    signal=TelemetrySignal.ERROR_EVENTS,
    start_time=WINDOW_START,
    end_time=WINDOW_END,
    filters=(TelemetryFilter(key="environment", value="production"),),
)


INCIDENT_EVIDENCE_FIXTURES: Mapping[IncidentEvidenceRequest, Evidence] = {
    INCIDENT_REQUEST: Evidence(
        evidence_id="incident:checkout-500",
        source=EvidenceSource.INCIDENT,
        kind=EvidenceKind.INCIDENT,
        provenance=EvidenceProvenance(
            source_reference="incident:checkout-500",
            observed_at=INCIDENT_STARTED_AT,
            retrieved_at=FIXTURE_TIME,
        ),
        content=IncidentEvidenceContent(
            incident_reference="incident:checkout-500",
            service="checkout-api",
            environment="production",
            started_at=INCIDENT_STARTED_AT,
            status=IncidentStatus.ACTIVE,
            category="http_5xx",
        ),
    )
}

DEPLOYMENT_EVIDENCE_FIXTURES: Mapping[DeploymentEvidenceRequest, Evidence] = {
    DEPLOYMENT_REQUEST: Evidence(
        evidence_id="deployment:1042",
        source=EvidenceSource.DEPLOYMENT,
        kind=EvidenceKind.DEPLOYMENT,
        provenance=EvidenceProvenance(
            source_reference="deployment:1042",
            observed_at=DEPLOYED_AT,
            retrieved_at=FIXTURE_TIME,
        ),
        content=DeploymentEvidenceContent(
            deployment_reference="deployment:1042",
            service="checkout-api",
            environment="production",
            commit_sha=COMMIT_SHA,
            deployed_at=DEPLOYED_AT,
        ),
    )
}

FAILURE_LOCATION_EVIDENCE_FIXTURES: Mapping[
    FailureLocationEvidenceRequest,
    Evidence,
] = {
    FAILURE_LOCATION_REQUEST: Evidence(
        evidence_id="incident:checkout-500:failure-location:1",
        source=EvidenceSource.INCIDENT,
        kind=EvidenceKind.STACK_FRAME,
        provenance=EvidenceProvenance(
            source_reference="incident:checkout-500:failure-location:1",
            observed_at=INCIDENT_STARTED_AT,
            retrieved_at=FIXTURE_TIME,
        ),
        content=StackFrameEvidenceContent(
            service="checkout-api",
            error_category="null_pointer",
            file_path="services/checkout.py",
            function_name="create_order",
            line_number=87,
        ),
    )
}

TELEMETRY_WINDOW_EVIDENCE_FIXTURES: Mapping[
    TelemetryWindowEvidenceRequest,
    Evidence,
] = {
    TELEMETRY_REQUEST: Evidence(
        evidence_id="telemetry:checkout-api:error-events:20260817T1140Z",
        source=EvidenceSource.TELEMETRY,
        kind=EvidenceKind.TELEMETRY_WINDOW,
        provenance=EvidenceProvenance(
            source_reference="telemetry:checkout-api:error-events:20260817T1140Z",
            observed_at=None,
            retrieved_at=FIXTURE_TIME,
        ),
        content=TelemetryWindowEvidenceContent(
            service="checkout-api",
            signal=TelemetrySignal.ERROR_EVENTS,
            start_time=WINDOW_START,
            end_time=WINDOW_END,
            filters=(TelemetryFilter(key="environment", value="production"),),
            event_count=17,
        ),
    )
}


class FakeIncidentSource:
    source = ConnectorSource.FAKE

    def __init__(
        self,
        incident_fixtures: Mapping[IncidentEvidenceRequest, Evidence] = (
            INCIDENT_EVIDENCE_FIXTURES
        ),
        deployment_fixtures: Mapping[DeploymentEvidenceRequest, Evidence] = (
            DEPLOYMENT_EVIDENCE_FIXTURES
        ),
        failure_location_fixtures: Mapping[FailureLocationEvidenceRequest, Evidence] = (
            FAILURE_LOCATION_EVIDENCE_FIXTURES
        ),
        telemetry_window_fixtures: Mapping[TelemetryWindowEvidenceRequest, Evidence] = (
            TELEMETRY_WINDOW_EVIDENCE_FIXTURES
        ),
    ) -> None:
        self._incident_fixtures = incident_fixtures
        self._deployment_fixtures = deployment_fixtures
        self._failure_location_fixtures = failure_location_fixtures
        self._telemetry_window_fixtures = telemetry_window_fixtures

    async def get_incident_evidence(
        self,
        request: IncidentEvidenceRequest,
    ) -> Evidence:
        return self._lookup(self._incident_fixtures, request)

    async def get_deployment_evidence(
        self,
        request: DeploymentEvidenceRequest,
    ) -> Evidence:
        return self._lookup(self._deployment_fixtures, request)

    async def get_failure_location_evidence(
        self,
        request: FailureLocationEvidenceRequest,
    ) -> Evidence:
        return self._lookup(self._failure_location_fixtures, request)

    async def get_telemetry_window_evidence(
        self,
        request: TelemetryWindowEvidenceRequest,
    ) -> Evidence:
        return self._lookup(self._telemetry_window_fixtures, request)

    @staticmethod
    def _lookup[Request](
        fixtures: Mapping[Request, Evidence],
        request: Request,
    ) -> Evidence:
        try:
            return fixtures[request]
        except KeyError:
            raise FixtureNotFoundError("incident") from None

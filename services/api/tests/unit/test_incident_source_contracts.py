from datetime import UTC, datetime
import unittest

from pydantic import ValidationError

from app.connectors.errors import FixtureNotFoundError
from app.connectors.incident_fakes import (
    DEPLOYMENT_REQUEST,
    FAILURE_LOCATION_REQUEST,
    INCIDENT_REQUEST,
    TELEMETRY_REQUEST,
    FakeIncidentSource,
)
from app.connectors.models import (
    TelemetryFilter,
    TelemetrySignal,
    TelemetryWindowEvidenceRequest,
)
from app.investigations import (
    Evidence,
    EvidenceKind,
    IncidentEvidenceContent,
    StackFrameEvidenceContent,
    TelemetryWindowEvidenceContent,
)


class IncidentSourceContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_source_returns_deterministic_normalized_evidence(self) -> None:
        source = FakeIncidentSource()

        incident = await source.get_incident_evidence(INCIDENT_REQUEST)
        deployment = await source.get_deployment_evidence(DEPLOYMENT_REQUEST)
        failure_location = await source.get_failure_location_evidence(
            FAILURE_LOCATION_REQUEST
        )
        telemetry = await source.get_telemetry_window_evidence(TELEMETRY_REQUEST)

        self.assertEqual(
            (incident.kind, deployment.kind, failure_location.kind, telemetry.kind),
            (
                EvidenceKind.INCIDENT,
                EvidenceKind.DEPLOYMENT,
                EvidenceKind.STACK_FRAME,
                EvidenceKind.TELEMETRY_WINDOW,
            ),
        )
        self.assertEqual(incident.provenance.observed_at, incident.content.started_at)
        self.assertEqual(deployment.content.commit_sha, "a" * 40)
        self.assertEqual(failure_location.content.error_category, "null_pointer")
        self.assertEqual(telemetry.content.event_count, 17)

        repeated = await source.get_incident_evidence(INCIDENT_REQUEST)
        self.assertEqual(repeated, incident)

    async def test_missing_fixture_is_not_fake_empty_evidence(self) -> None:
        source = FakeIncidentSource()
        unavailable_request = TELEMETRY_REQUEST.model_copy(
            update={"service": "billing-api"}
        )

        with self.assertRaises(FixtureNotFoundError):
            await source.get_telemetry_window_evidence(unavailable_request)

    def test_telemetry_window_requires_aware_ordered_timestamps(self) -> None:
        start_time = datetime(2026, 8, 17, 11, 40, tzinfo=UTC)
        end_time = datetime(2026, 8, 17, 11, 45, tzinfo=UTC)

        accepted = TelemetryWindowEvidenceRequest(
            service="checkout-api",
            signal=TelemetrySignal.ERROR_EVENTS,
            start_time=start_time,
            end_time=end_time,
            filters=(TelemetryFilter(key="environment", value="production"),),
        )
        self.assertEqual(accepted.start_time, start_time)

        with self.assertRaises(ValidationError):
            TelemetryWindowEvidenceRequest(
                service="checkout-api",
                signal=TelemetrySignal.ERROR_EVENTS,
                start_time=datetime(2026, 8, 17, 11, 40),
                end_time=end_time,
            )
        with self.assertRaises(ValidationError):
            TelemetryWindowEvidenceRequest(
                service="checkout-api",
                signal=TelemetrySignal.ERROR_EVENTS,
                start_time=end_time,
                end_time=start_time,
            )

    def test_incident_optional_fields_and_structured_failure_location_are_bounded(self) -> None:
        incident = IncidentEvidenceContent(incident_reference="incident:partial")
        error_only = StackFrameEvidenceContent(error_category="timeout")

        self.assertIsNone(incident.started_at)
        self.assertEqual(error_only.error_category, "timeout")
        with self.assertRaises(ValidationError):
            StackFrameEvidenceContent(line_number=87)

    def test_malformed_or_provider_specific_payloads_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            TelemetryWindowEvidenceContent(
                service="checkout-api",
                signal=TelemetrySignal.ERROR_EVENTS,
                start_time=datetime(2026, 8, 17, 11, 45, tzinfo=UTC),
                end_time=datetime(2026, 8, 17, 11, 40, tzinfo=UTC),
                event_count=1,
            )

        raw_provider_values = {
            "evidence_id": "evidence:vendor-payload",
            "source": "incident",
            "kind": "incident",
            "provenance": {
                "source_reference": "incident:checkout-500",
                "retrieved_at": "2026-08-17T12:00:00Z",
            },
            "content": {
                "content_type": "incident",
                "incident_reference": "incident:checkout-500",
                "grafana_query": "{service=\"checkout-api\"}",
            },
        }
        with self.assertRaises(ValidationError):
            Evidence.model_validate(raw_provider_values)


if __name__ == "__main__":
    unittest.main()

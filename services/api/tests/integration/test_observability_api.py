pass

import unittest

from fastapi.testclient import TestClient

from app.api.v1.connector_router import get_run_repository
from app.connectors.fixture_catalog import MERGE_READY_REQUEST
from app.main import create_app
from app.observability import Observability, ObservedRunRepository
from app.runtime import InMemoryRunRepository
from tests.telemetry_support import create_telemetry_harness


class ObservabilityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = create_telemetry_harness()
        observability = Observability(
            runtime_telemetry=self.harness.telemetry,
            tracer_provider=self.harness.tracer_provider,
            meter_provider=self.harness.meter_provider,
        )
        self.app = create_app(observability)
        self.repository = ObservedRunRepository(
            InMemoryRunRepository(),
            self.harness.telemetry,
        )
        self.app.dependency_overrides[get_run_repository] = lambda: self.repository
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()
        self.harness.shutdown()

    def test_http_workflow_steps_and_persistence_share_one_trace(self) -> None:
        response = self.client.post(
            "/v1/pull-request-merge-readiness",
            json=MERGE_READY_REQUEST.model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        spans = self.harness.span_exporter.get_finished_spans()
        server_span = next(span for span in spans if span.kind.name == "SERVER")
        workflow_span = next(
            span for span in spans if span.name == "merge_readiness.execute"
        )
        self.assertEqual(workflow_span.parent.span_id, server_span.context.span_id)
        self.assertTrue(
            all(span.context.trace_id == server_span.context.trace_id for span in spans)
        )
        self.assertEqual(
            server_span.attributes["promptql.run.id"],
            body["run_id"],
        )
        self.assertIn("merge_readiness.github.fetch", {span.name for span in spans})
        self.assertIn("merge_readiness.jira.fetch", {span.name for span in spans})
        self.assertIn("merge_readiness.policy.evaluate", {span.name for span in spans})
        self.assertIn("runtime.persistence.save", {span.name for span in spans})

    def test_health_request_does_not_create_a_trace(self) -> None:
        self.harness.span_exporter.clear()

        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.harness.span_exporter.get_finished_spans(), ())

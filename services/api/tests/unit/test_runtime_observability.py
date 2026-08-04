pass

import asyncio
import json
import io
import logging
import os
import unittest
from unittest.mock import patch

from app.config import TelemetrySettings
from app.connectors.errors import ConnectorUnavailableError
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FAILED_CI_REQUEST, MERGE_READY_REQUEST
from app.connectors.models import ConnectorRequest, GitHubPullRequest
from app.observability import ObservedRunRepository, RuntimeTelemetry
from app.observability.contracts import (
    METRIC_LABEL_ALLOWLISTS,
    PERSISTENCE_FAILURES_METRIC,
    WORKFLOW_RUNS_METRIC,
    WORKFLOW_RUN_DURATION_METRIC,
    WORKFLOW_STEP_DURATION_METRIC,
    WORKFLOW_STEP_FAILURES_METRIC,
    validate_metric_labels,
)
from app.observability.setup import create_observability
from app.observability.setup import FailureIsolatingSpanExporter
from app.observability.structured_logging import StructuredEventLogger
from app.runtime import (
    InMemoryRunRepository,
    MergeReadinessRun,
    RunPersistenceError,
    RunStatus,
)
from app.workflows import MergeReadinessWorkflowService
from tests.telemetry_support import create_telemetry_harness
from opentelemetry import metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExportResult,
    SpanExporter,
)


class FailingGitHubConnector:
    async def get_pull_request(
        self,
        _request: ConnectorRequest,
    ) -> GitHubPullRequest:
        raise RuntimeError(
            "password=hunter2 token=abc db.internal SELECT * FROM secrets payload=x"
        )


class UnavailableJiraConnector:
    def get_issue_for_pull_request(self, _request):
        raise ConnectorUnavailableError("jira")


class TerminalSaveFailureRepository(InMemoryRunRepository):
    def save(self, run: MergeReadinessRun) -> None:
        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            raise RunPersistenceError("postgres://secret@db.internal/runtime")
        super().save(run)


class RaisingSpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.export_attempts = 0

    def export(self, _spans):
        self.export_attempts += 1
        raise RuntimeError("token=exporter-secret")

    def shutdown(self) -> None:
        return


class RuntimeObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = create_telemetry_harness()

    def tearDown(self) -> None:
        self.harness.shutdown()

    def run_workflow(
        self,
        request: ConnectorRequest = MERGE_READY_REQUEST,
        github_connector=None,
        repository=None,
    ):
        inner_repository = repository or InMemoryRunRepository()
        observed_repository = ObservedRunRepository(
            inner_repository,
            self.harness.telemetry,
        )
        workflow = MergeReadinessWorkflowService(
            github_connector or FakeGitHubConnector(),
            FakeJiraConnector(),
            observed_repository,
            telemetry=self.harness.telemetry,
        )
        return asyncio.run(workflow.execute(request)), inner_repository

    def test_completed_run_records_hierarchy_durations_and_one_counter(self) -> None:
        run, repository = self.run_workflow(FAILED_CI_REQUEST)

        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(run.result.decision.value, "blocked")
        self.assertEqual(repository.get(run.run_id), run)

        spans = self.harness.span_exporter.get_finished_spans()
        workflow_span = next(
            span for span in spans if span.name == "merge_readiness.execute"
        )
        domain_spans = [span for span in spans if span is not workflow_span]
        self.assertTrue(domain_spans)
        self.assertTrue(
            all(span.context.trace_id == workflow_span.context.trace_id for span in spans)
        )
        self.assertTrue(
            all(span.parent.span_id == workflow_span.context.span_id for span in domain_spans)
        )
        self.assertEqual(workflow_span.status.status_code.name, "UNSET")

        run_points = self.harness.metric_points(WORKFLOW_RUNS_METRIC)
        self.assertEqual(sum(point.value for point in run_points), 1)
        self.assertEqual(dict(run_points[0].attributes)["run.status"], "completed")
        self.assertEqual(len(self.harness.metric_points(WORKFLOW_RUN_DURATION_METRIC)), 1)
        self.assertEqual(len(self.harness.metric_points(WORKFLOW_STEP_DURATION_METRIC)), 3)
        self.assertEqual(len(self.harness.metric_points(WORKFLOW_STEP_FAILURES_METRIC)), 0)

        log = json.loads(self.harness.log_stream.getvalue().strip())
        self.assertEqual(log["event"], "runtime.workflow.completed")
        self.assertEqual(log["run_id"], str(run.run_id))
        self.assertEqual(log["policy_decision"], "blocked")
        self.assertIn("trace_id", log)

    def test_ready_blocked_and_unknown_are_successful_trace_outcomes(self) -> None:
        cases = (
            (MERGE_READY_REQUEST, FakeJiraConnector(), "ready"),
            (FAILED_CI_REQUEST, FakeJiraConnector(), "blocked"),
            (MERGE_READY_REQUEST, UnavailableJiraConnector(), "unknown"),
        )
        for request, jira_connector, expected_decision in cases:
            with self.subTest(decision=expected_decision):
                harness = create_telemetry_harness()
                try:
                    workflow = MergeReadinessWorkflowService(
                        FakeGitHubConnector(),
                        jira_connector,
                        ObservedRunRepository(
                            InMemoryRunRepository(),
                            harness.telemetry,
                        ),
                        telemetry=harness.telemetry,
                    )
                    run = asyncio.run(workflow.execute(request))
                    workflow_span = next(
                        span
                        for span in harness.span_exporter.get_finished_spans()
                        if span.name == "merge_readiness.execute"
                    )
                    self.assertEqual(run.result.decision.value, expected_decision)
                    self.assertEqual(workflow_span.status.status_code.name, "UNSET")
                    self.assertNotIn("error.type", workflow_span.attributes)
                finally:
                    harness.shutdown()

    def test_system_failure_is_sanitized_and_counted_once(self) -> None:
        run, _repository = self.run_workflow(
            github_connector=FailingGitHubConnector()
        )

        self.assertEqual(run.status, RunStatus.FAILED)
        spans = self.harness.span_exporter.get_finished_spans()
        workflow_span = next(
            span for span in spans if span.name == "merge_readiness.execute"
        )
        github_span = next(
            span for span in spans if span.name == "merge_readiness.github.fetch"
        )
        self.assertEqual(workflow_span.attributes["error.type"], "connector_failure")
        self.assertEqual(github_span.attributes["error.type"], "connector_failure")
        self.assertEqual(github_span.events, ())

        run_points = self.harness.metric_points(WORKFLOW_RUNS_METRIC)
        self.assertEqual(sum(point.value for point in run_points), 1)
        self.assertEqual(dict(run_points[0].attributes)["run.status"], "failed")
        failure_points = self.harness.metric_points(WORKFLOW_STEP_FAILURES_METRIC)
        self.assertEqual(sum(point.value for point in failure_points), 1)

        exported_text = repr(spans) + repr(
            [dict(point.attributes) for point in run_points + failure_points]
        ) + self.harness.log_stream.getvalue()
        for forbidden_text in (
            "hunter2",
            "token=abc",
            "db.internal",
            "SELECT *",
            "payload=x",
        ):
            self.assertNotIn(forbidden_text, exported_text)

    def test_terminal_commit_failure_emits_only_persistence_failure(self) -> None:
        repository = TerminalSaveFailureRepository()

        with self.assertRaises(RunPersistenceError):
            self.run_workflow(repository=repository)

        self.assertEqual(self.harness.metric_points(WORKFLOW_RUNS_METRIC), [])
        persistence_points = self.harness.metric_points(
            PERSISTENCE_FAILURES_METRIC
        )
        self.assertEqual(sum(point.value for point in persistence_points), 1)
        self.assertEqual(
            dict(persistence_points[0].attributes)["failure.category"],
            "persistence_unavailable",
        )
        self.assertNotIn(
            "runtime.workflow.completed",
            self.harness.log_stream.getvalue(),
        )

    def test_observed_repository_preserves_return_values_and_exceptions(self) -> None:
        inner = InMemoryRunRepository()
        observed = ObservedRunRepository(inner, self.harness.telemetry)
        run = asyncio.run(
            MergeReadinessWorkflowService(
                FakeGitHubConnector(),
                FakeJiraConnector(),
                observed,
                telemetry=self.harness.telemetry,
            ).execute(MERGE_READY_REQUEST)
        )
        self.assertEqual(observed.get(run.run_id), run)
        self.assertIsNone(observed.get(run.run_id.__class__(int=0)))

        failure = RunPersistenceError("secret storage detail", run.run_id)

        class FailingRepository:
            def save(self, _run):
                raise failure

            def get(self, _run_id):
                raise failure

        failing = ObservedRunRepository(FailingRepository(), self.harness.telemetry)
        with self.assertRaises(RunPersistenceError) as caught:
            failing.get(run.run_id)
        self.assertIs(caught.exception, failure)

    def test_metric_label_allowlists_reject_missing_and_extra_keys(self) -> None:
        for metric_name, allowed_keys in METRIC_LABEL_ALLOWLISTS.items():
            valid = {key: "bounded" for key in allowed_keys}
            validate_metric_labels(metric_name, valid)
            with self.assertRaises(ValueError):
                validate_metric_labels(metric_name, {**valid, "run_id": "123"})
            key_to_remove = next(iter(allowed_keys))
            with self.assertRaises(ValueError):
                validate_metric_labels(
                    metric_name,
                    {key: value for key, value in valid.items() if key != key_to_remove},
                )

    def test_exporter_failure_does_not_change_workflow_or_persistence(self) -> None:
        log_stream = io.StringIO()
        logger = logging.Logger("promptql.exporter.failure.test")
        logger.addHandler(logging.StreamHandler(log_stream))
        event_logger = StructuredEventLogger(logger)
        provider = TracerProvider(shutdown_on_exit=False)
        raising_exporter = RaisingSpanExporter()
        safe_exporter = FailureIsolatingSpanExporter(
            raising_exporter,
            event_logger,
        )
        provider.add_span_processor(SimpleSpanProcessor(safe_exporter))
        telemetry = RuntimeTelemetry(
            provider.get_tracer("promptql.exporter.test"),
            metrics.NoOpMeterProvider().get_meter("promptql.exporter.test"),
            event_logger,
        )
        inner_repository = InMemoryRunRepository()
        workflow = MergeReadinessWorkflowService(
            FakeGitHubConnector(),
            FakeJiraConnector(),
            ObservedRunRepository(inner_repository, telemetry),
            telemetry=telemetry,
        )

        run = asyncio.run(workflow.execute(MERGE_READY_REQUEST))
        provider.shutdown()

        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(inner_repository.get(run.run_id), run)
        self.assertNotIn("exporter-secret", log_stream.getvalue())
        self.assertEqual(
            log_stream.getvalue().count("runtime.telemetry.export_failed"),
            1,
        )
        self.assertEqual(raising_exporter.export_attempts, 1)


class TelemetryConfigurationTests(unittest.TestCase):
    def test_telemetry_and_console_export_are_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = TelemetrySettings.from_environment()
            observability = create_observability(settings)

        self.assertFalse(settings.enabled)
        self.assertFalse(settings.console_enabled)
        self.assertIsNone(observability.tracer_provider)
        self.assertIsNone(observability.meter_provider)

    def test_disabled_telemetry_preserves_workflow_result(self) -> None:
        settings = TelemetrySettings(
            enabled=False,
            console_enabled=False,
            service_name="promptql-api",
            otlp_endpoint=None,
            otlp_headers={},
            protocol="http/protobuf",
        )
        observability = create_observability(settings)
        repository = InMemoryRunRepository()

        run = asyncio.run(
            MergeReadinessWorkflowService(
                FakeGitHubConnector(),
                FakeJiraConnector(),
                repository,
                telemetry=observability.runtime_telemetry,
            ).execute(MERGE_READY_REQUEST)
        )

        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(run.result.decision.value, "ready")
        self.assertEqual(repository.get(run.run_id), run)

    def test_invalid_configuration_degrades_to_no_op_observability(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PROMPTQL_TELEMETRY_ENABLED": "true",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://remote.example/secret",
                "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic%20secret",
            },
            clear=True,
        ):
            observability = create_observability()

        self.assertIsNone(observability.tracer_provider)
        self.assertIsNone(observability.meter_provider)

    def test_otlp_configuration_creates_application_scoped_providers(self) -> None:
        settings = TelemetrySettings(
            enabled=True,
            console_enabled=False,
            service_name="promptql-api",
            otlp_endpoint="https://otlp.example.test/otlp",
            otlp_headers={"Authorization": "Basic placeholder"},
            protocol="http/protobuf",
        )

        observability = create_observability(settings)
        try:
            self.assertIsNotNone(observability.tracer_provider)
            self.assertIsNotNone(observability.meter_provider)
        finally:
            observability.shutdown()

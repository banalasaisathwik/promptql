pass

import logging
from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from app.observability.contracts import (
    METRIC_LABEL_ALLOWLISTS,
    PERSISTENCE_FAILURES_METRIC,
    WORKFLOW_RUN_DURATION_METRIC,
    WORKFLOW_RUNS_METRIC,
    WORKFLOW_STEP_DURATION_METRIC,
    WORKFLOW_STEP_FAILURES_METRIC,
    FailureCategory,
    PersistenceCheckpoint,
    PersistenceOperation,
    PersistenceOutcome,
    StepOutcome,
    use_persistence_checkpoint,
    validate_metric_labels,
)
from app.observability.structured_logging import (
    NoOpStructuredEventLogger,
    StructuredEventLogger,
)
from app.runtime.models import MergeReadinessRun, RunStatus, WorkflowStepName


SPAN_ATTRIBUTE_ALLOWLIST = frozenset(
    {
        "promptql.run.id",
        "promptql.workflow.name",
        "promptql.workflow.version",
        "promptql.run.status",
        "promptql.step.name",
        "promptql.step.outcome",
        "promptql.policy.decision",
        "promptql.persistence.operation",
        "promptql.persistence.outcome",
        "promptql.persistence.checkpoint",
        "error.type",
    }
)
SUPPORTED_WORKFLOWS = frozenset({("merge_readiness", "1")})


class SpanObservation:
    pass

    def __init__(self, span: Span) -> None:
        self._span = span

    def set_attributes(self, **attributes: str) -> None:
        try:
            if not attributes.keys() <= SPAN_ATTRIBUTE_ALLOWLIST:
                raise ValueError("span attribute is not allowed")
            for name, value in attributes.items():
                self._span.set_attribute(name, value)
        except Exception:
            return

    def mark_error(self, category: FailureCategory) -> None:
        try:
            self._span.set_attribute("error.type", category.value)
            self._span.set_status(Status(StatusCode.ERROR))
        except Exception:
            return


class RuntimeTelemetry:
    pass

    def __init__(
        self,
        tracer: Tracer,
        meter: Meter,
        event_logger: StructuredEventLogger | NoOpStructuredEventLogger,
    ) -> None:
        self._tracer = tracer
        self._event_logger = event_logger
        self._workflow_runs = meter.create_counter(
            WORKFLOW_RUNS_METRIC,
            unit="1",
            description="Durably committed terminal workflow runs.",
        )
        self._workflow_run_duration = meter.create_histogram(
            WORKFLOW_RUN_DURATION_METRIC,
            unit="s",
            description="Duration of durably committed workflow runs.",
        )
        self._workflow_step_duration = meter.create_histogram(
            WORKFLOW_STEP_DURATION_METRIC,
            unit="s",
            description="Duration of durably committed runtime steps.",
        )
        self._workflow_step_failures = meter.create_counter(
            WORKFLOW_STEP_FAILURES_METRIC,
            unit="1",
            description="Durably committed failed workflow steps.",
        )
        self._persistence_failures = meter.create_counter(
            PERSISTENCE_FAILURES_METRIC,
            unit="1",
            description="Failed runtime repository operations.",
        )

    @staticmethod
    def _workflow_labels(run: MergeReadinessRun) -> dict[str, str]:
        identity = (run.workflow_name, run.workflow_version)
        if identity not in SUPPORTED_WORKFLOWS:
            raise ValueError("workflow identity is not approved for metrics")
        return {
            "workflow.name": run.workflow_name,
            "workflow.version": run.workflow_version,
        }

    @contextmanager
    def _observe_span(
        self,
        name: str,
        attributes: dict[str, str],
    ) -> Iterator[SpanObservation]:
        safe_attributes = {
            key: value
            for key, value in attributes.items()
            if key in SPAN_ATTRIBUTE_ALLOWLIST
        }
        with self._tracer.start_as_current_span(
            name,
            kind=trace.SpanKind.INTERNAL,
            attributes=safe_attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            yield SpanObservation(span)

    def observe_workflow(
        self,
        run: MergeReadinessRun,
    ) -> Iterator[SpanObservation]:
        return self._observe_span(
            "merge_readiness.execute",
            {
                "promptql.run.id": str(run.run_id),
                "promptql.workflow.name": run.workflow_name,
                "promptql.workflow.version": run.workflow_version,
            },
        )

    def observe_step(
        self,
        run: MergeReadinessRun,
        step_name: WorkflowStepName,
    ) -> Iterator[SpanObservation]:
        span_names = {
            WorkflowStepName.FETCH_GITHUB_FACTS: "merge_readiness.github.fetch",
            WorkflowStepName.FETCH_JIRA_FACTS: "merge_readiness.jira.fetch",
            WorkflowStepName.EVALUATE_MERGE_READINESS: (
                "merge_readiness.policy.evaluate"
            ),
        }
        return self._observe_span(
            span_names[step_name],
            {
                "promptql.run.id": str(run.run_id),
                "promptql.workflow.name": run.workflow_name,
                "promptql.workflow.version": run.workflow_version,
                "promptql.step.name": step_name.value,
            },
        )

    def observe_persistence(
        self,
        operation: PersistenceOperation,
        run_id: UUID,
        checkpoint: PersistenceCheckpoint | None,
    ) -> Iterator[SpanObservation]:
        attributes = {
            "promptql.run.id": str(run_id),
            "promptql.persistence.operation": operation.value,
        }
        if checkpoint is not None:
            attributes["promptql.persistence.checkpoint"] = checkpoint.value
        return self._observe_span(
            f"runtime.persistence.{operation.value}",
            attributes,
        )

    def checkpoint(self, checkpoint: PersistenceCheckpoint) -> Iterator[None]:
        return use_persistence_checkpoint(checkpoint)

    def correlate_current_span(self, run: MergeReadinessRun) -> None:
        pass

        try:
            span = trace.get_current_span()
            span.set_attribute("promptql.run.id", str(run.run_id))
            span.set_attribute("promptql.run.status", run.status.value)
        except Exception:
            self._warn_telemetry_failure("traces")

    def record_terminal_workflow(self, run: MergeReadinessRun) -> None:
        pass

        try:
            if run.status not in {RunStatus.COMPLETED, RunStatus.FAILED}:
                raise ValueError("workflow is not terminal")
            if run.started_at is None or run.completed_at is None:
                raise ValueError("terminal workflow has no duration")

            labels = {
                **self._workflow_labels(run),
                "run.status": run.status.value,
            }
            validate_metric_labels(WORKFLOW_RUNS_METRIC, labels)
            validate_metric_labels(WORKFLOW_RUN_DURATION_METRIC, labels)
            duration_seconds = max(
                0.0,
                (run.completed_at - run.started_at).total_seconds(),
            )
            self._workflow_runs.add(1, labels)
            self._workflow_run_duration.record(duration_seconds, labels)

            if run.status is RunStatus.COMPLETED:
                event = "runtime.workflow.completed"
                level = logging.INFO
            else:
                event = "runtime.workflow.failed"
                level = logging.ERROR

            self._event_logger.emit(
                event,
                level,
                run_id=run.run_id,
                workflow_name=run.workflow_name,
                workflow_version=run.workflow_version,
                run_status=run.status,
                policy_decision=(
                    run.result.decision if run.result is not None else None
                ),
                failure_category=(
                    failure_category_for_runtime_code(run.error.code.value)
                    if run.error is not None
                    else None
                ),
            )
        except Exception:
            self._warn_telemetry_failure("metrics")

    def record_terminal_step(
        self,
        run: MergeReadinessRun,
        step_name: WorkflowStepName,
        duration_ms: int,
        outcome: StepOutcome,
        failure_category: FailureCategory | None = None,
    ) -> None:
        try:
            labels = {
                **self._workflow_labels(run),
                "step.name": step_name.value,
                "step.outcome": outcome.value,
            }
            validate_metric_labels(WORKFLOW_STEP_DURATION_METRIC, labels)
            self._workflow_step_duration.record(duration_ms / 1000, labels)

            if failure_category is not None:
                failure_labels = {
                    **self._workflow_labels(run),
                    "step.name": step_name.value,
                    "failure.category": failure_category.value,
                }
                validate_metric_labels(
                    WORKFLOW_STEP_FAILURES_METRIC,
                    failure_labels,
                )
                self._workflow_step_failures.add(1, failure_labels)
        except Exception:
            self._warn_telemetry_failure("metrics")

    def record_persistence_failure(
        self,
        operation: PersistenceOperation,
        category: FailureCategory,
        run_id: UUID,
        checkpoint: PersistenceCheckpoint | None,
    ) -> None:
        try:
            labels = {
                "persistence.operation": operation.value,
                "failure.category": category.value,
            }
            validate_metric_labels(PERSISTENCE_FAILURES_METRIC, labels)
            self._persistence_failures.add(1, labels)
            self._event_logger.emit(
                "runtime.persistence.failed",
                logging.ERROR,
                run_id=run_id,
                persistence_operation=operation,
                persistence_checkpoint=checkpoint,
                failure_category=category,
            )
        except Exception:
            self._warn_telemetry_failure("metrics")

    def _warn_telemetry_failure(self, signal: str) -> None:
        self._event_logger.emit(
            "runtime.telemetry.export_failed",
            logging.WARNING,
            telemetry_signal=signal,
            failure_category=FailureCategory.TELEMETRY_EXPORT_FAILURE,
        )


class NoOpRuntimeTelemetry(RuntimeTelemetry):
    pass

    def __init__(self) -> None:
        tracer = trace.NoOpTracerProvider().get_tracer("promptql.runtime")
        meter = metrics.NoOpMeterProvider().get_meter("promptql.runtime")
        super().__init__(tracer, meter, NoOpStructuredEventLogger())


def failure_category_for_runtime_code(error_code: str) -> FailureCategory:
    categories = {
        "connector_execution_failed": FailureCategory.CONNECTOR_FAILURE,
        "policy_execution_failed": FailureCategory.POLICY_FAILURE,
        "fixture_not_found": FailureCategory.FIXTURE_NOT_FOUND,
    }
    return categories.get(error_code, FailureCategory.SYSTEM_FAILURE)

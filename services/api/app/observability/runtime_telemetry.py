import logging
from contextlib import contextmanager
from time import perf_counter_ns
from typing import Iterator
from uuid import UUID

from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from app.observability.contracts import (
    METRIC_LABEL_ALLOWLISTS,
    INVESTIGATION_PLANNING_ROUNDS_METRIC,
    INVESTIGATION_STAGE_DURATION_METRIC,
    INVESTIGATION_TOOL_CALLS_METRIC,
    LLM_EXPLANATION_DURATION_METRIC,
    LLM_TOKEN_USAGE_METRIC,
    PERSISTENCE_FAILURES_METRIC,
    WORKFLOW_RUN_DURATION_METRIC,
    WORKFLOW_RUNS_METRIC,
    WORKFLOW_STEP_DURATION_METRIC,
    WORKFLOW_STEP_FAILURES_METRIC,
    FailureCategory,
    InvestigationStage,
    InvestigationStageResult,
    LLMCallResult,
    LLMTokenType,
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


# SECURITY: Attribute names are closed before values reach an exporter. Adding
# a new backend destination therefore cannot accidentally widen the data sent;
# callers still cannot attach prompts, code, Evidence, or exception messages.
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
        "promptql.connector.name",
        "promptql.connector.source",
        "promptql.connector.operation",
        "promptql.connector.result",
        "promptql.http.status_class",
        "promptql.pagination.page_count",
        "promptql.llm.operation",
        "promptql.llm.provider",
        "promptql.llm.prompt.id",
        "promptql.llm.prompt.version",
        "promptql.llm.model.fingerprint",
        "promptql.llm.result",
        "promptql.llm.failure.category",
        "promptql.llm.validation.result",
        "promptql.llm.validation.failure_category",
        "promptql.llm.input_tokens",
        "promptql.llm.output_tokens",
        "promptql.llm.total_tokens",
        "promptql.llm.requested_model",
        "promptql.llm.resolved_model",
        "promptql.investigation.stage",
        "promptql.investigation.round",
        "promptql.investigation.tool.id",
        "promptql.investigation.tool.attempt",
        "promptql.investigation.tool.count",
        "promptql.investigation.round.count",
        "promptql.investigation.termination_reason",
        "promptql.stage.result",
        "langfuse.trace.name",
        "langfuse.observation.type",
        "langfuse.observation.model.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "error.type",
    }
)
SUPPORTED_WORKFLOWS = frozenset({("merge_readiness", "1"), ("investigation", "2.19.2")})
SUPPORTED_LLM_PROVIDERS = frozenset({"fake", "gemini", "groq", "openai", "openrouter"})
SUPPORTED_LLM_FAILURE_CATEGORIES = frozenset(
    {
        "authentication",
        "permission",
        "rate_limit",
        "timeout",
        "connection",
        "invalid_request",
        "refusal",
        "invalid_structured_response",
        "upstream_unavailable",
        "unexpected",
    }
)


class SpanObservation:
    def __init__(self, span: Span) -> None:
        self._span = span
        self._stage_result = InvestigationStageResult.SUCCEEDED

    def set_attributes(self, **attributes: str | int) -> None:
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

    def set_stage_result(self, result: InvestigationStageResult) -> None:
        self._stage_result = result
        self.set_attributes(**{"promptql.stage.result": result.value})

    @property
    def stage_result(self) -> InvestigationStageResult:
        return self._stage_result


class RuntimeTelemetry:
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
        self._llm_explanation_duration = meter.create_histogram(
            LLM_EXPLANATION_DURATION_METRIC,
            unit="s",
            description="Duration of internal merge-readiness explanations.",
        )
        self._llm_token_usage = meter.create_counter(
            LLM_TOKEN_USAGE_METRIC,
            unit="1",
            description="Provider-reported tokens for internal explanations.",
        )
        self._investigation_stage_duration = meter.create_histogram(
            INVESTIGATION_STAGE_DURATION_METRIC,
            unit="s",
            description="Duration of bounded investigation stages.",
        )
        self._investigation_tool_calls = meter.create_counter(
            INVESTIGATION_TOOL_CALLS_METRIC,
            unit="1",
            description="Physical read-only investigation tool attempts.",
        )
        self._investigation_planning_rounds = meter.create_counter(
            INVESTIGATION_PLANNING_ROUNDS_METRIC,
            unit="1",
            description="Planning rounds completed by terminal investigations.",
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
        attributes: dict[str, str | int],
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

    def observe_connector(
        self,
        connector_name: str,
        connector_source: str,
        operation: str,
    ) -> Iterator[SpanObservation]:
        allowed_identities = {
            ("github", "fake", "get_pull_request"),
            ("github", "live", "get_pull_request"),
            ("github", "fake", "get_commit_evidence"),
            ("github", "live", "get_commit_evidence"),
            ("github", "fake", "get_pull_request_evidence"),
            ("github", "live", "get_pull_request_evidence"),
            ("github", "fake", "get_changed_file_evidence"),
            ("github", "live", "get_changed_file_evidence"),
            ("jira", "fake", "get_issue"),
            ("jira", "live", "get_issue"),
        }
        identity = (connector_name, connector_source, operation)
        if identity not in allowed_identities:
            return self._observe_span("connector.invalid", {})
        return self._observe_span(
            f"connector.{connector_name}.{operation}",
            {
                "promptql.connector.name": connector_name,
                "promptql.connector.source": connector_source,
                "promptql.connector.operation": operation,
            },
        )

    def observe_llm_explanation(
        self,
        provider: str,
        prompt_id: str,
        prompt_version: str,
        model_fingerprint: str,
    ) -> Iterator[SpanObservation]:
        if provider not in SUPPORTED_LLM_PROVIDERS:
            return self._observe_span("llm.invalid", {})

        return self._observe_span(
            "merge_readiness.explanation.generate",
            {
                "promptql.llm.operation": "merge_readiness_explanation",
                "promptql.llm.provider": provider,
                "promptql.llm.prompt.id": prompt_id,
                "promptql.llm.prompt.version": prompt_version,
                "promptql.llm.model.fingerprint": model_fingerprint,
            },
        )

    @contextmanager
    def observe_investigation_stage(
        self,
        stage: InvestigationStage,
        run_id: UUID,
        *,
        round_number: int | None = None,
        tool_id: str | None = None,
        attempt: int | None = None,
        task: str | None = None,
        provider: str | None = None,
        requested_model: str | None = None,
        resolved_model: str | None = None,
        prompt_version: str | None = None,
    ) -> Iterator[SpanObservation]:
        # FLOW: Build bounded correlation metadata -> open the child span -> let
        # domain code run -> convert uncategorized exceptions -> always record
        # duration. The context manager observes; it never decides or recovers.
        attributes: dict[str, str | int] = {
            "promptql.run.id": str(run_id),
            "promptql.workflow.name": "investigation",
            "promptql.workflow.version": "2.19.2",
            "promptql.investigation.stage": stage.value,
        }
        optional_attributes = {
            "promptql.investigation.round": round_number,
            "promptql.investigation.tool.id": tool_id,
            "promptql.investigation.tool.attempt": attempt,
            "promptql.llm.operation": task,
            "promptql.llm.provider": provider,
            "promptql.llm.requested_model": requested_model,
            "promptql.llm.resolved_model": resolved_model,
            "promptql.llm.prompt.version": prompt_version,
            "gen_ai.request.model": requested_model,
            "gen_ai.response.model": resolved_model,
        }
        attributes.update(
            {name: value for name, value in optional_attributes.items() if value is not None}
        )
        if stage is InvestigationStage.INVESTIGATION:
            attributes["langfuse.trace.name"] = "promptql-investigation"
        if task is not None:
            attributes["langfuse.observation.type"] = "generation"
            if resolved_model or requested_model:
                attributes["langfuse.observation.model.name"] = (
                    resolved_model or requested_model or "unknown"
                )

        started_at_ns = perf_counter_ns()
        with self._observe_span(f"investigation.{stage.value}", attributes) as observation:
            try:
                yield observation
            except Exception:
                if observation.stage_result is not InvestigationStageResult.FAILED:
                    observation.set_stage_result(InvestigationStageResult.FAILED)
                    observation.mark_error(FailureCategory.SYSTEM_FAILURE)
                raise
            finally:
                observation.set_stage_result(observation.stage_result)
                self._record_investigation_stage_duration(
                    stage,
                    observation.stage_result,
                    perf_counter_ns() - started_at_ns,
                )

    def _record_investigation_stage_duration(
        self,
        stage: InvestigationStage,
        result: InvestigationStageResult,
        duration_ns: int,
    ) -> None:
        try:
            labels = {
                "investigation.stage": stage.value,
                "stage.result": result.value,
            }
            validate_metric_labels(INVESTIGATION_STAGE_DURATION_METRIC, labels)
            self._investigation_stage_duration.record(
                max(0, duration_ns) / 1_000_000_000,
                labels,
            )
        except Exception:
            self._warn_telemetry_failure("metrics")

    def record_investigation_tool_call(self, tool_id: str, outcome: str) -> None:
        try:
            labels = {"tool.id": tool_id, "tool.outcome": outcome}
            validate_metric_labels(INVESTIGATION_TOOL_CALLS_METRIC, labels)
            self._investigation_tool_calls.add(1, labels)
        except Exception:
            self._warn_telemetry_failure("metrics")

    def record_investigation_termination(
        self,
        observation: SpanObservation,
        *,
        planning_rounds: int,
        tool_calls: int,
        termination_reason: str,
    ) -> None:
        try:
            observation.set_attributes(
                **{
                    "promptql.investigation.round.count": max(0, planning_rounds),
                    "promptql.investigation.tool.count": max(0, tool_calls),
                    "promptql.investigation.termination_reason": termination_reason,
                }
            )
            labels = {"termination.reason": termination_reason}
            validate_metric_labels(INVESTIGATION_PLANNING_ROUNDS_METRIC, labels)
            self._investigation_planning_rounds.add(max(0, planning_rounds), labels)
        except Exception:
            self._warn_telemetry_failure("metrics")

    def record_llm_explanation(
        self,
        duration_ms: int,
        result: LLMCallResult,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        provider: str,
    ) -> None:
        try:
            if provider not in SUPPORTED_LLM_PROVIDERS:
                raise ValueError("LLM provider is not approved for metrics")
            duration_labels = {
                "llm.operation": "merge_readiness_explanation",
                "llm.provider": provider,
                "llm.result": result.value,
            }
            validate_metric_labels(
                LLM_EXPLANATION_DURATION_METRIC,
                duration_labels,
            )
            self._llm_explanation_duration.record(
                max(0, duration_ms) / 1_000,
                duration_labels,
            )

            token_counts = (
                (LLMTokenType.INPUT, input_tokens),
                (LLMTokenType.OUTPUT, output_tokens),
                (LLMTokenType.TOTAL, total_tokens),
            )
            for token_type, token_count in token_counts:
                if token_count is None:
                    continue
                token_labels = {
                    "llm.operation": "merge_readiness_explanation",
                    "llm.provider": provider,
                    "llm.token.type": token_type.value,
                }
                validate_metric_labels(LLM_TOKEN_USAGE_METRIC, token_labels)
                self._llm_token_usage.add(max(0, token_count), token_labels)
        except Exception:
            self._warn_telemetry_failure("metrics")

    def record_llm_failure(self, provider: str, failure_category: str) -> None:
        try:
            if provider not in SUPPORTED_LLM_PROVIDERS:
                raise ValueError("LLM provider is not approved for logs")
            if failure_category not in SUPPORTED_LLM_FAILURE_CATEGORIES:
                raise ValueError("LLM failure category is not approved for logs")
            self._event_logger.emit(
                "llm.explanation.failed",
                logging.ERROR,
                llm_provider=provider,
                failure_category=failure_category,
            )
        except Exception:
            self._warn_telemetry_failure("logs")

    def checkpoint(self, checkpoint: PersistenceCheckpoint) -> Iterator[None]:
        return use_persistence_checkpoint(checkpoint)

    def correlate_current_span(self, run: MergeReadinessRun) -> None:
        try:
            span = trace.get_current_span()
            span.set_attribute("promptql.run.id", str(run.run_id))
            span.set_attribute("promptql.run.status", run.status.value)
        except Exception:
            self._warn_telemetry_failure("traces")

    def record_terminal_workflow(self, run: MergeReadinessRun) -> None:
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

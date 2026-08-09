from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from typing import Iterator


class FailureCategory(StrEnum):
    CONNECTOR_FAILURE = "connector_failure"
    POLICY_FAILURE = "policy_failure"
    FIXTURE_NOT_FOUND = "fixture_not_found"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"
    STATE_CONFLICT = "state_conflict"
    RECORD_INVALID = "record_invalid"
    SYSTEM_FAILURE = "system_failure"
    TELEMETRY_EXPORT_FAILURE = "telemetry_export_failure"
    LLM_PROVIDER_FAILURE = "llm_provider_failure"
    LLM_INVALID_OUTPUT = "llm_invalid_output"
    LLM_VALIDATION_FAILURE = "llm_validation_failure"


class LLMCallResult(StrEnum):
    SUCCESS = "success"
    PROVIDER_FAILURE = "provider_failure"
    INVALID_OUTPUT = "invalid_output"
    VALIDATION_FAILURE = "validation_failure"


class LLMTokenType(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class StepOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class PersistenceOperation(StrEnum):
    SAVE = "save"
    GET = "get"


class PersistenceOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_FOUND = "not_found"


class PersistenceCheckpoint(StrEnum):
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


WORKFLOW_RUNS_METRIC = "promptql.workflow.runs"
WORKFLOW_RUN_DURATION_METRIC = "promptql.workflow.run.duration"
WORKFLOW_STEP_DURATION_METRIC = "promptql.workflow.step.duration"
WORKFLOW_STEP_FAILURES_METRIC = "promptql.workflow.step.failures"
PERSISTENCE_FAILURES_METRIC = "promptql.runtime.persistence.failures"
LLM_EXPLANATION_DURATION_METRIC = "promptql.llm.explanation.duration"
LLM_TOKEN_USAGE_METRIC = "promptql.llm.tokens"

METRIC_LABEL_ALLOWLISTS: dict[str, frozenset[str]] = {
    WORKFLOW_RUNS_METRIC: frozenset(
        {"workflow.name", "workflow.version", "run.status"}
    ),
    WORKFLOW_RUN_DURATION_METRIC: frozenset(
        {"workflow.name", "workflow.version", "run.status"}
    ),
    WORKFLOW_STEP_DURATION_METRIC: frozenset(
        {
            "workflow.name",
            "workflow.version",
            "step.name",
            "step.outcome",
        }
    ),
    WORKFLOW_STEP_FAILURES_METRIC: frozenset(
        {
            "workflow.name",
            "workflow.version",
            "step.name",
            "failure.category",
        }
    ),
    PERSISTENCE_FAILURES_METRIC: frozenset(
        {"persistence.operation", "failure.category"}
    ),
    LLM_EXPLANATION_DURATION_METRIC: frozenset(
        {"llm.operation", "llm.result"}
    ),
    LLM_TOKEN_USAGE_METRIC: frozenset(
        {"llm.operation", "llm.token.type"}
    ),
}

_current_checkpoint: ContextVar[PersistenceCheckpoint | None] = ContextVar(
    "promptql_persistence_checkpoint",
    default=None,
)


@contextmanager
def use_persistence_checkpoint(
    checkpoint: PersistenceCheckpoint,
) -> Iterator[None]:
    token = _current_checkpoint.set(checkpoint)
    try:
        yield
    finally:
        _current_checkpoint.reset(token)


def current_persistence_checkpoint() -> PersistenceCheckpoint | None:
    return _current_checkpoint.get()


def validate_metric_labels(
    metric_name: str,
    labels: dict[str, str],
) -> None:
    allowed_keys = METRIC_LABEL_ALLOWLISTS.get(metric_name)
    if allowed_keys is None or frozenset(labels) != allowed_keys:
        raise ValueError(f"metric labels are not allowed for {metric_name}")

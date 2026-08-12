from datetime import datetime
from uuid import UUID, uuid4

from app.connectors.models import ConnectorRequest
from app.runtime.models import RunSources
from app.policy.models import MergeReadinessResult
from app.runtime.models import (
    MergeReadinessRun,
    RunStatus,
    RuntimeErrorInfo,
    RuntimeStep,
    StepStatus,
    WorkflowStepName,
)


class InvalidStateTransitionError(ValueError):
    pass


ALLOWED_RUN_TRANSITIONS = {
    RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}

ALLOWED_STEP_TRANSITIONS = {
    StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.CANCELLED},
    StepStatus.RUNNING: {
        StepStatus.COMPLETED,
        StepStatus.FAILED,
        StepStatus.CANCELLED,
    },
    StepStatus.COMPLETED: set(),
    StepStatus.FAILED: set(),
    StepStatus.CANCELLED: set(),
}


def _replace_run(run: MergeReadinessRun, **updates) -> MergeReadinessRun:
    run_values = run.model_dump()
    run_values.update(updates)
    return MergeReadinessRun.model_validate(run_values)


def _replace_step(step: RuntimeStep, **updates) -> RuntimeStep:
    step_values = step.model_dump()
    step_values.update(updates)
    return RuntimeStep.model_validate(step_values)


def create_pending_run(
    request: ConnectorRequest,
    run_id: UUID | None = None,
    sources: RunSources | None = None,
) -> MergeReadinessRun:
    return MergeReadinessRun(
        run_id=run_id or uuid4(),
        workflow_name="merge_readiness",
        workflow_version="1",
        sources=sources,
        status=RunStatus.PENDING,
        started_at=None,
        completed_at=None,
        steps=(),
        error=None,
        result=None,
        request=request,
        github=None,
        jira=None,
    )


def create_pending_step(
    name: WorkflowStepName,
    step_id: UUID | None = None,
) -> RuntimeStep:
    return RuntimeStep(
        step_id=step_id or uuid4(),
        name=name,
        status=StepStatus.PENDING,
        started_at=None,
        completed_at=None,
        duration_ms=None,
        attempt=1,
        error=None,
    )


def transition_run(
    run: MergeReadinessRun,
    new_status: RunStatus,
    changed_at: datetime,
    *,
    error: RuntimeErrorInfo | None = None,
    result: MergeReadinessResult | None = None,
) -> MergeReadinessRun:
    if new_status not in ALLOWED_RUN_TRANSITIONS[run.status]:
        raise InvalidStateTransitionError(
            f"run cannot move from {run.status.value} to {new_status.value}"
        )

    if new_status is RunStatus.RUNNING:
        return _replace_run(run, status=new_status, started_at=changed_at)

    return _replace_run(
        run,
        status=new_status,
        started_at=run.started_at or changed_at,
        completed_at=changed_at,
        error=error,
        result=result,
    )


def transition_step(
    step: RuntimeStep,
    new_status: StepStatus,
    changed_at: datetime,
    *,
    duration_ms: int | None = None,
    error: RuntimeErrorInfo | None = None,
) -> RuntimeStep:
    if new_status not in ALLOWED_STEP_TRANSITIONS[step.status]:
        raise InvalidStateTransitionError(
            f"step cannot move from {step.status.value} to {new_status.value}"
        )

    if new_status is StepStatus.RUNNING:
        return _replace_step(step, status=new_status, started_at=changed_at)

    return _replace_step(
        step,
        status=new_status,
        started_at=step.started_at or changed_at,
        completed_at=changed_at,
        duration_ms=duration_ms,
        error=error,
    )

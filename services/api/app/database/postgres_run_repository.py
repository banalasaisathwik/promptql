from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.models import ConnectorRequest, GitHubPullRequest, JiraIssue
from app.database.models import WorkflowRunRow, WorkflowStepRow
from app.policy.models import MergeReadinessResult
from app.runtime.errors import (
    RunPersistenceError,
    RunRecordInvalidError,
    RunStateConflictError,
)
from app.runtime.models import (
    MergeReadinessRun,
    RunStatus,
    RunSources,
    RuntimeErrorInfo,
    RuntimeStep,
    StepStatus,
)
from app.runtime.state import ALLOWED_RUN_TRANSITIONS, ALLOWED_STEP_TRANSITIONS


def _json_value(model) -> dict[str, Any] | None:
    if model is None:
        return None
    return model.model_dump(mode="json")


def _run_values(run: MergeReadinessRun) -> dict[str, Any]:
    sources = run.sources
    return {
        "workflow_name": run.workflow_name,
        "workflow_version": run.workflow_version,
        "github_source": sources.github.value if sources and sources.github else None,
        "jira_source": sources.jira.value if sources and sources.jira else None,
        "explanation_source": (
            sources.explanation.value if sources and sources.explanation else None
        ),
        "status": run.status.value,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "request_payload": _json_value(run.request),
        "github_facts": _json_value(run.github),
        "jira_facts": _json_value(run.jira),
        "result": _json_value(run.result),
        "runtime_error": _json_value(run.error),
    }


def _step_values(
    run_id: UUID,
    sequence_number: int,
    step: RuntimeStep,
) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "run_id": run_id,
        "sequence_number": sequence_number,
        "name": step.name.value,
        "status": step.status.value,
        "started_at": step.started_at,
        "completed_at": step.completed_at,
        "duration_ms": step.duration_ms,
        "attempt": step.attempt,
        "runtime_error": _json_value(step.error),
    }


def _step_row_values(step: WorkflowStepRow) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "run_id": step.run_id,
        "sequence_number": step.sequence_number,
        "name": step.name,
        "status": step.status,
        "started_at": step.started_at,
        "completed_at": step.completed_at,
        "duration_ms": step.duration_ms,
        "attempt": step.attempt,
        "runtime_error": step.runtime_error,
    }


class PostgresRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory


        self._confirmed_run_ids: set[UUID] = set()

    def save(self, run: MergeReadinessRun) -> None:
        try:
            with self._session_factory.begin() as session:
                stored_run = session.get(WorkflowRunRow, run.run_id)
                if stored_run is None:
                    self._insert_pending_run(session, run)
                else:
                    self._update_existing_run(session, stored_run, run)
                self._save_steps(session, run)


            self._confirmed_run_ids.add(run.run_id)
        except RunStateConflictError:
            raise
        except IntegrityError:
            raise RunStateConflictError(
                "The stored runtime state changed concurrently.",
                self._confirmed_run_id(run.run_id),
            ) from None
        except SQLAlchemyError:
            raise RunPersistenceError(
                "Runtime persistence is unavailable.",
                self._confirmed_run_id(run.run_id),
            ) from None

    def get(self, run_id: UUID) -> MergeReadinessRun | None:
        try:
            with self._session_factory() as session:
                stored_run = session.get(WorkflowRunRow, run_id)
                if stored_run is None:
                    return None
                stored_steps = tuple(
                    session.scalars(
                        select(WorkflowStepRow)
                        .where(WorkflowStepRow.run_id == run_id)
                        .order_by(WorkflowStepRow.sequence_number)
                    )
                )
        except SQLAlchemyError:
            raise RunPersistenceError(
                "Runtime persistence is unavailable."
            ) from None


        try:
            self._validate_step_sequence(stored_steps, run_id)
            return self._read_run(stored_run, stored_steps)
        except (ValidationError, ValueError, TypeError):
            raise RunRecordInvalidError(
                "The stored runtime record could not be reconstructed.",
                run_id,
            ) from None

    def _read_run(
        self,
        stored_run: WorkflowRunRow,
        stored_steps: tuple[WorkflowStepRow, ...],
    ) -> MergeReadinessRun:
        runtime_error = None
        if stored_run.runtime_error is not None:
            runtime_error = RuntimeErrorInfo.model_validate(stored_run.runtime_error)

        policy_result = None
        if stored_run.result is not None:
            policy_result = MergeReadinessResult.model_validate(
                stored_run.result
            )

        github_facts = None
        if stored_run.github_facts is not None:
            github_facts = GitHubPullRequest.model_validate(stored_run.github_facts)

        jira_facts = None
        if stored_run.jira_facts is not None:
            jira_facts = JiraIssue.model_validate(stored_run.jira_facts)

        runtime_steps = tuple(
            self._read_step(stored_step) for stored_step in stored_steps
        )
        connector_request = ConnectorRequest.model_validate(
            stored_run.request_payload
        )
        sources = None
        if any(
            source is not None
            for source in (
                stored_run.github_source,
                stored_run.jira_source,
                stored_run.explanation_source,
            )
        ):
            sources = RunSources(
                github=stored_run.github_source,
                jira=stored_run.jira_source,
                explanation=stored_run.explanation_source,
            )

        return MergeReadinessRun(
            run_id=stored_run.run_id,
            workflow_name=stored_run.workflow_name,
            workflow_version=stored_run.workflow_version,
            sources=sources,
            status=stored_run.status,
            started_at=stored_run.started_at,
            completed_at=stored_run.completed_at,
            steps=runtime_steps,
            error=runtime_error,
            result=policy_result,
            request=connector_request,
            github=github_facts,
            jira=jira_facts,
        )

    def _confirmed_run_id(self, run_id: UUID) -> UUID | None:
        return run_id if run_id in self._confirmed_run_ids else None

    def _insert_pending_run(
        self,
        session: Session,
        run: MergeReadinessRun,
    ) -> None:
        if run.status.value != "pending" or run.steps:
            raise RunStateConflictError(
                "A new durable run must begin in pending state."
            )
        session.add(WorkflowRunRow(run_id=run.run_id, **_run_values(run)))

    def _update_existing_run(
        self,
        session: Session,
        stored_run: WorkflowRunRow,
        run: MergeReadinessRun,
    ) -> None:
        self._validate_run_identity(stored_run, run)
        stored_status = stored_run.status
        incoming_status = run.status.value

        if stored_status != incoming_status:
            allowed_statuses = {
                status.value
                for status in ALLOWED_RUN_TRANSITIONS[RunStatus(stored_status)]
            }
            if incoming_status not in allowed_statuses:
                raise RunStateConflictError(
                    "The stored run does not permit this state transition.",
                    run.run_id,
                )
        elif incoming_status in {"completed", "failed", "cancelled"}:
            if _run_values(run) == self._stored_run_values(stored_run):
                return
            raise RunStateConflictError(
                "A terminal run cannot be changed.",
                run.run_id,
            )


        statement = (
            update(WorkflowRunRow)
            .where(
                WorkflowRunRow.run_id == run.run_id,
                WorkflowRunRow.status == stored_status,
            )
            .values(**_run_values(run))
        )
        update_result = session.execute(statement)
        if update_result.rowcount != 1:
            raise RunStateConflictError(
                "The stored runtime state changed concurrently.",
                run.run_id,
            )

    def _save_steps(self, session: Session, run: MergeReadinessRun) -> None:
        stored_steps = tuple(
            session.scalars(
                select(WorkflowStepRow)
                .where(WorkflowStepRow.run_id == run.run_id)
                .order_by(WorkflowStepRow.sequence_number)
            )
        )
        if len(stored_steps) > len(run.steps):
            raise RunStateConflictError(
                "A saved runtime step cannot be removed.",
                run.run_id,
            )

        for sequence_number, step in enumerate(run.steps):
            incoming_values = _step_values(run.run_id, sequence_number, step)
            if sequence_number >= len(stored_steps):
                if step.status.value != "pending":
                    raise RunStateConflictError(
                        "A new durable step must begin in pending state.",
                        run.run_id,
                    )
                session.add(WorkflowStepRow(**incoming_values))
                continue

            stored_step = stored_steps[sequence_number]
            if stored_step.step_id != step.step_id:
                raise RunStateConflictError(
                    "A saved runtime step cannot be replaced.",
                    run.run_id,
                )
            if _step_row_values(stored_step) == incoming_values:
                continue

            stored_status = StepStatus(stored_step.status)
            if step.status not in ALLOWED_STEP_TRANSITIONS[stored_status]:
                raise RunStateConflictError(
                    "The stored step does not permit this state transition.",
                    run.run_id,
                )

            update_values = dict(incoming_values)


            update_values.pop("step_id")
            update_values.pop("run_id")
            update_values.pop("sequence_number")
            statement = (
                update(WorkflowStepRow)
                .where(
                    WorkflowStepRow.step_id == step.step_id,
                    WorkflowStepRow.status == stored_step.status,
                )
                .values(**update_values)
            )
            update_result = session.execute(statement)
            if update_result.rowcount != 1:
                raise RunStateConflictError(
                    "The stored runtime step changed concurrently.",
                    run.run_id,
                )

    @staticmethod
    def _stored_run_values(stored_run: WorkflowRunRow) -> dict[str, Any]:
        return {
            "workflow_name": stored_run.workflow_name,
            "workflow_version": stored_run.workflow_version,
            "github_source": stored_run.github_source,
            "jira_source": stored_run.jira_source,
            "explanation_source": stored_run.explanation_source,
            "status": stored_run.status,
            "started_at": stored_run.started_at,
            "completed_at": stored_run.completed_at,
            "request_payload": stored_run.request_payload,
            "github_facts": stored_run.github_facts,
            "jira_facts": stored_run.jira_facts,
            "result": stored_run.result,
            "runtime_error": stored_run.runtime_error,
        }

    @staticmethod
    def _validate_run_identity(
        stored_run: WorkflowRunRow,
        run: MergeReadinessRun,
    ) -> None:
        if (
            stored_run.workflow_name != run.workflow_name
            or stored_run.workflow_version != run.workflow_version
            or stored_run.github_source
            != (run.sources.github.value if run.sources and run.sources.github else None)
            or stored_run.jira_source
            != (run.sources.jira.value if run.sources and run.sources.jira else None)
            or stored_run.explanation_source
            != (
                run.sources.explanation.value
                if run.sources and run.sources.explanation
                else None
            )
            or stored_run.request_payload != _json_value(run.request)
        ):
            raise RunStateConflictError(
                "A durable run's identity cannot be changed.",
                run.run_id,
            )

    @staticmethod
    def _validate_step_sequence(
        stored_steps: tuple[WorkflowStepRow, ...],
        run_id: UUID,
    ) -> None:
        if tuple(step.sequence_number for step in stored_steps) != tuple(
            range(len(stored_steps))
        ):
            raise RunRecordInvalidError(
                "The stored runtime record could not be reconstructed.",
                run_id,
            )

    @staticmethod
    def _read_step(stored_step: WorkflowStepRow) -> RuntimeStep:
        return RuntimeStep(
            step_id=stored_step.step_id,
            name=stored_step.name,
            status=stored_step.status,
            started_at=stored_step.started_at,
            completed_at=stored_step.completed_at,
            duration_ms=stored_step.duration_ms,
            attempt=stored_step.attempt,
            error=(
                RuntimeErrorInfo.model_validate(stored_step.runtime_error)
                if stored_step.runtime_error is not None
                else None
            ),
        )

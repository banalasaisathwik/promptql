from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class DatabaseModel(DeclarativeBase):
    pass


class WorkflowRunRow(DatabaseModel):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_workflow_runs_status",
        ),
        CheckConstraint(
            "length(btrim(workflow_name)) > 0",
            name="ck_workflow_runs_name_not_empty",
        ),
        CheckConstraint(
            "length(btrim(workflow_version)) > 0",
            name="ck_workflow_runs_version_not_empty",
        ),
        CheckConstraint(
            "github_source IS NULL OR github_source IN ('fake', 'live')",
            name="ck_workflow_runs_github_source",
        ),
        CheckConstraint(
            "jira_source IS NULL OR jira_source IN ('fake', 'live')",
            name="ck_workflow_runs_jira_source",
        ),
        CheckConstraint(
            "explanation_source IS NULL OR "
            "explanation_source IN ('fake', 'gemini', 'groq', 'openai')",
            name="ck_workflow_runs_explanation_source",
        ),
        CheckConstraint(
            "jsonb_typeof(request_payload) = 'object'",
            name="ck_workflow_runs_request_object",
        ),
        CheckConstraint(
            "github_facts IS NULL OR jsonb_typeof(github_facts) = 'object'",
            name="ck_workflow_runs_github_object",
        ),
        CheckConstraint(
            "jira_facts IS NULL OR jsonb_typeof(jira_facts) = 'object'",
            name="ck_workflow_runs_jira_object",
        ),
        CheckConstraint(
            "result IS NULL OR jsonb_typeof(result) = 'object'",
            name="ck_workflow_runs_result_object",
        ),
        CheckConstraint(
            "runtime_error IS NULL OR jsonb_typeof(runtime_error) = 'object'",
            name="ck_workflow_runs_error_object",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND completed_at IS NULL "
            "AND result IS NULL AND runtime_error IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND result IS NULL "
            "AND runtime_error IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result IS NOT NULL "
            "AND runtime_error IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result IS NULL "
            "AND runtime_error IS NOT NULL) OR "
            "(status = 'cancelled' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result IS NULL)",
            name="ck_workflow_runs_lifecycle",
        ),
    )


    run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workflow_name: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_version: Mapped[str] = mapped_column(Text, nullable=False)
    github_source: Mapped[str | None] = mapped_column(Text)
    jira_source: Mapped[str | None] = mapped_column(Text)
    explanation_source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


    github_facts: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    jira_facts: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    runtime_error: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )


class WorkflowStepRow(DatabaseModel):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_workflow_steps_run_sequence",
        ),
        CheckConstraint(
            "sequence_number >= 0",
            name="ck_workflow_steps_sequence_non_negative",
        ),
        CheckConstraint("attempt > 0", name="ck_workflow_steps_attempt_positive"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_workflow_steps_duration_non_negative",
        ),
        CheckConstraint(
            "name IN ('fetch_github_facts', 'fetch_jira_facts', "
            "'evaluate_merge_readiness')",
            name="ck_workflow_steps_name",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_workflow_steps_status",
        ),
        CheckConstraint(
            "runtime_error IS NULL OR jsonb_typeof(runtime_error) = 'object'",
            name="ck_workflow_steps_error_object",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL "
            "AND completed_at IS NULL AND duration_ms IS NULL "
            "AND runtime_error IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND duration_ms IS NULL "
            "AND runtime_error IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND duration_ms IS NOT NULL "
            "AND runtime_error IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND duration_ms IS NOT NULL "
            "AND runtime_error IS NOT NULL) OR "
            "(status = 'cancelled' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND duration_ms IS NOT NULL "
            "AND runtime_error IS NULL)",
            name="ck_workflow_steps_lifecycle",
        ),
    )

    step_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    runtime_error: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )

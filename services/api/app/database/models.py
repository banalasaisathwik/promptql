from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
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
            "explanation_source IN ('fake', 'gemini', 'groq', 'openai', 'openrouter')",
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
            "jsonb_typeof(investigation_results) = 'array'",
            name="ck_workflow_runs_investigation_results_array",
        ),
        CheckConstraint(
            "follow_up_count >= 0",
            name="ck_workflow_runs_follow_up_count_non_negative",
        ),
        CheckConstraint(
            "jsonb_typeof(recorded_fact_types) = 'array'",
            name="ck_workflow_runs_recorded_fact_types_array",
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
            "AND completed_at IS NOT NULL AND runtime_error IS NULL AND "
            "(workflow_name = 'investigation' OR result IS NOT NULL) AND "
            "(workflow_name <> 'investigation' OR jsonb_array_length(investigation_results) > 0)) OR "
            "(status = 'failed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result IS NULL "
            "AND runtime_error IS NOT NULL) OR "
            "(status = 'cancelled' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result IS NULL)",
            name="ck_workflow_runs_lifecycle",
        ),
    )


    run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id"),
        index=True,
    )
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
    investigation_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    runtime_error: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    investigation_results: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    follow_up_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    recorded_fact_types: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


_KNOWN_FACT_TYPES = (
    "changed_file",
    "deployment",
    "stack_frame",
    "deployment_preceded_incident",
    "deployment_references_commit",
    "commit_associated_with_pull_request",
    "changed_file_matches_failure_file",
    "changed_hunk_overlaps_failure_line",
)


class UserRow(DatabaseModel):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(email)) > 0",
            name="ck_users_email_not_empty",
        ),
        CheckConstraint(
            "length(btrim(password_hash)) > 0",
            name="ck_users_password_hash_not_empty",
        ),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class CredentialRow(DatabaseModel):
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('github', 'jira', 'sentry')",
            name="ck_credentials_provider",
        ),
        UniqueConstraint("user_id", "provider", name="uq_credentials_user_provider"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    encrypted_token: Mapped[bytes] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RepositoryFactRecurrenceRow(DatabaseModel):
    __tablename__ = "repository_fact_recurrence"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(repository_owner)) > 0",
            name="ck_repository_fact_recurrence_owner_not_empty",
        ),
        CheckConstraint(
            "length(btrim(repository_name)) > 0",
            name="ck_repository_fact_recurrence_name_not_empty",
        ),
        CheckConstraint(
            "fact_type IN ("
            + ", ".join(f"'{fact_type}'" for fact_type in _KNOWN_FACT_TYPES)
            + ")",
            name="ck_repository_fact_recurrence_fact_type",
        ),
        CheckConstraint(
            "occurrence_count > 0",
            name="ck_repository_fact_recurrence_count_positive",
        ),
        PrimaryKeyConstraint("repository_owner", "repository_name", "fact_type"),
    )

    repository_owner: Mapped[str] = mapped_column(Text)
    repository_name: Mapped[str] = mapped_column(Text)
    fact_type: Mapped[str] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_observed_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    last_observed_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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

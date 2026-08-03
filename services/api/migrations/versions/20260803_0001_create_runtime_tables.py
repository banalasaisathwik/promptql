pass

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260803_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_name", sa.Text(), nullable=False),
        sa.Column("workflow_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("github_facts", postgresql.JSONB(), nullable=True),
        sa.Column("jira_facts", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("runtime_error", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_workflow_runs_status",
        ),
        sa.CheckConstraint(
            "length(btrim(workflow_name)) > 0",
            name="ck_workflow_runs_name_not_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(workflow_version)) > 0",
            name="ck_workflow_runs_version_not_empty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(request_payload) = 'object'",
            name="ck_workflow_runs_request_object",
        ),
        sa.CheckConstraint(
            "github_facts IS NULL OR jsonb_typeof(github_facts) = 'object'",
            name="ck_workflow_runs_github_object",
        ),
        sa.CheckConstraint(
            "jira_facts IS NULL OR jsonb_typeof(jira_facts) = 'object'",
            name="ck_workflow_runs_jira_object",
        ),
        sa.CheckConstraint(
            "result IS NULL OR jsonb_typeof(result) = 'object'",
            name="ck_workflow_runs_result_object",
        ),
        sa.CheckConstraint(
            "runtime_error IS NULL OR jsonb_typeof(runtime_error) = 'object'",
            name="ck_workflow_runs_error_object",
        ),
        sa.CheckConstraint(
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
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_table(
        "workflow_steps",
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("runtime_error", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "sequence_number >= 0",
            name="ck_workflow_steps_sequence_non_negative",
        ),
        sa.CheckConstraint(
            "attempt > 0",
            name="ck_workflow_steps_attempt_positive",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_workflow_steps_duration_non_negative",
        ),
        sa.CheckConstraint(
            "name IN ('fetch_github_facts', 'fetch_jira_facts', "
            "'evaluate_merge_readiness')",
            name="ck_workflow_steps_name",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_workflow_steps_status",
        ),
        sa.CheckConstraint(
            "runtime_error IS NULL OR jsonb_typeof(runtime_error) = 'object'",
            name="ck_workflow_steps_error_object",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("step_id"),
        sa.UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_workflow_steps_run_sequence",
        ),
    )


def downgrade() -> None:
    op.drop_table("workflow_steps")
    op.drop_table("workflow_runs")

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260828_0007"
down_revision: str | None = "20260827_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_LIFECYCLE_SQL = (
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
    "AND completed_at IS NOT NULL AND result IS NULL)"
)

_NEW_LIFECYCLE_SQL = (
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
    "AND completed_at IS NOT NULL AND result IS NULL)"
)


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column(
            "investigation_results",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "workflow_runs",
        sa.Column(
            "follow_up_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


    op.drop_constraint("ck_workflow_runs_lifecycle", "workflow_runs", type_="check")


    op.execute(
        "UPDATE workflow_runs "
        "SET investigation_results = jsonb_build_array(result), result = NULL "
        "WHERE workflow_name = 'investigation' AND result IS NOT NULL"
    )

    op.create_check_constraint(
        "ck_workflow_runs_lifecycle",
        "workflow_runs",
        _NEW_LIFECYCLE_SQL,
    )
    op.create_check_constraint(
        "ck_workflow_runs_investigation_results_array",
        "workflow_runs",
        "jsonb_typeof(investigation_results) = 'array'",
    )
    op.create_check_constraint(
        "ck_workflow_runs_follow_up_count_non_negative",
        "workflow_runs",
        "follow_up_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workflow_runs_follow_up_count_non_negative", "workflow_runs", type_="check"
    )
    op.drop_constraint(
        "ck_workflow_runs_investigation_results_array", "workflow_runs", type_="check"
    )
    op.drop_constraint("ck_workflow_runs_lifecycle", "workflow_runs", type_="check")


    op.execute(
        "UPDATE workflow_runs "
        "SET result = investigation_results -> 0 "
        "WHERE workflow_name = 'investigation' "
        "AND jsonb_array_length(investigation_results) > 0"
    )

    op.create_check_constraint(
        "ck_workflow_runs_lifecycle",
        "workflow_runs",
        _OLD_LIFECYCLE_SQL,
    )
    op.drop_column("workflow_runs", "follow_up_count")
    op.drop_column("workflow_runs", "investigation_results")

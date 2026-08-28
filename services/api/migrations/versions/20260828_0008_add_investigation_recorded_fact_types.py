from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260828_0008"
down_revision: str | None = "20260828_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column(
            "recorded_fact_types",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_workflow_runs_recorded_fact_types_array",
        "workflow_runs",
        "jsonb_typeof(recorded_fact_types) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workflow_runs_recorded_fact_types_array", "workflow_runs", type_="check"
    )
    op.drop_column("workflow_runs", "recorded_fact_types")

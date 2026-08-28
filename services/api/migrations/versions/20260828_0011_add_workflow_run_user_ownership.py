from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260828_0011"
down_revision: str | None = "20260828_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_workflow_runs_user_id_users",
        "workflow_runs",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_index("ix_workflow_runs_user_id", "workflow_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_user_id", table_name="workflow_runs")
    op.drop_constraint(
        "fk_workflow_runs_user_id_users", "workflow_runs", type_="foreignkey"
    )
    op.drop_column("workflow_runs", "user_id")

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260827_0006"
down_revision: str | None = "20260825_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def upgrade() -> None:
    op.create_table(
        "repository_fact_recurrence",
        sa.Column("repository_owner", sa.Text(), nullable=False),
        sa.Column("repository_name", sa.Text(), nullable=False),
        sa.Column("fact_type", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column(
            "first_observed_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "last_observed_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "last_observed_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "promoted_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "length(btrim(repository_owner)) > 0",
            name="ck_repository_fact_recurrence_owner_not_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(repository_name)) > 0",
            name="ck_repository_fact_recurrence_name_not_empty",
        ),
        sa.CheckConstraint(
            "fact_type IN ("
            + ", ".join(f"'{fact_type}'" for fact_type in _KNOWN_FACT_TYPES)
            + ")",
            name="ck_repository_fact_recurrence_fact_type",
        ),
        sa.CheckConstraint(
            "occurrence_count > 0",
            name="ck_repository_fact_recurrence_count_positive",
        ),
        sa.PrimaryKeyConstraint(
            "repository_owner", "repository_name", "fact_type"
        ),
    )


def downgrade() -> None:
    op.drop_table("repository_fact_recurrence")

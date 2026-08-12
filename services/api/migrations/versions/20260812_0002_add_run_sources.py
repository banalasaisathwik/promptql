from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0002"
down_revision: str | None = "20260803_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("github_source", sa.Text()))
    op.add_column("workflow_runs", sa.Column("jira_source", sa.Text()))
    op.add_column("workflow_runs", sa.Column("explanation_source", sa.Text()))
    op.create_check_constraint(
        "ck_workflow_runs_github_source",
        "workflow_runs",
        "github_source IS NULL OR github_source IN ('fake', 'live')",
    )
    op.create_check_constraint(
        "ck_workflow_runs_jira_source",
        "workflow_runs",
        "jira_source IS NULL OR jira_source IN ('fake', 'live')",
    )
    op.create_check_constraint(
        "ck_workflow_runs_explanation_source",
        "workflow_runs",
        "explanation_source IS NULL OR "
        "explanation_source IN ('fake', 'gemini', 'openai')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workflow_runs_explanation_source",
        "workflow_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_workflow_runs_jira_source",
        "workflow_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_workflow_runs_github_source",
        "workflow_runs",
        type_="check",
    )
    op.drop_column("workflow_runs", "explanation_source")
    op.drop_column("workflow_runs", "jira_source")
    op.drop_column("workflow_runs", "github_source")

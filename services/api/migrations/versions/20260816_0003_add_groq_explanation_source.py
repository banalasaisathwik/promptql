from collections.abc import Sequence

from alembic import op


revision: str = "20260816_0003"
down_revision: str | None = "20260812_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CONSTRAINT_NAME = "ck_workflow_runs_explanation_source"


def upgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "workflow_runs",
        type_="check",
    )
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "workflow_runs",
        "explanation_source IS NULL OR "
        "explanation_source IN ('fake', 'gemini', 'groq', 'openai')",
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "workflow_runs",
        type_="check",
    )


    op.create_check_constraint(
        CONSTRAINT_NAME,
        "workflow_runs",
        "explanation_source IS NULL OR "
        "explanation_source IN ('fake', 'gemini', 'openai')",
    )

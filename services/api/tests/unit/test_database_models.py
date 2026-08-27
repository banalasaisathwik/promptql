import unittest
from typing import get_args

from sqlalchemy.dialects import postgresql

from app.database.models import (
    RepositoryFactRecurrenceRow,
    WorkflowRunRow,
    WorkflowStepRow,
)
from app.investigations.models import InvestigationFact


class DatabaseModelTests(unittest.TestCase):
    def test_source_columns_are_nullable_and_have_closed_checks(self) -> None:
        self.assertTrue(WorkflowRunRow.github_source.nullable)
        self.assertTrue(WorkflowRunRow.jira_source.nullable)
        self.assertTrue(WorkflowRunRow.explanation_source.nullable)
        constraint_names = {
            constraint.name for constraint in WorkflowRunRow.__table__.constraints
        }
        self.assertIn("ck_workflow_runs_github_source", constraint_names)
        self.assertIn("ck_workflow_runs_jira_source", constraint_names)
        self.assertIn("ck_workflow_runs_explanation_source", constraint_names)
        explanation_constraint = next(
            constraint
            for constraint in WorkflowRunRow.__table__.constraints
            if constraint.name == "ck_workflow_runs_explanation_source"
        )
        constraint_sql = str(
            explanation_constraint.sqltext.compile(
                dialect=postgresql.dialect()
            )
        )
        self.assertIn("'groq'", constraint_sql)

    def test_optional_json_snapshots_bind_none_as_sql_null(self) -> None:
        optional_json_columns = (
            WorkflowRunRow.github_facts,
            WorkflowRunRow.jira_facts,
            WorkflowRunRow.result,
            WorkflowRunRow.runtime_error,
            WorkflowStepRow.runtime_error,
        )
        dialect = postgresql.dialect()

        for column in optional_json_columns:
            with self.subTest(column=column.name):
                bind_value = column.type.bind_processor(dialect)(None)
                self.assertIsNone(bind_value)


def _known_investigation_fact_types() -> set[str]:
    (fact_union, _discriminator_field) = get_args(InvestigationFact)
    return {
        get_args(fact_class.model_fields["fact_type"].annotation)[0]
        for fact_class in get_args(fact_union)
    }


class RepositoryFactRecurrenceModelTests(unittest.TestCase):
    def test_composite_primary_key_is_owner_name_and_fact_type(self) -> None:
        primary_key_columns = {
            column.name for column in RepositoryFactRecurrenceRow.__table__.primary_key.columns
        }
        self.assertEqual(
            primary_key_columns,
            {"repository_owner", "repository_name", "fact_type"},
        )

    def test_promoted_at_is_the_only_nullable_column(self) -> None:
        table = RepositoryFactRecurrenceRow.__table__
        nullable_columns = {column.name for column in table.columns if column.nullable}
        self.assertEqual(nullable_columns, {"promoted_at"})

    def test_occurrence_count_check_requires_positive_values(self) -> None:
        constraint_names = {
            constraint.name for constraint in RepositoryFactRecurrenceRow.__table__.constraints
        }
        self.assertIn("ck_repository_fact_recurrence_count_positive", constraint_names)

    def test_fact_type_check_matches_every_known_investigation_fact_type(self) -> None:
        fact_type_constraint = next(
            constraint
            for constraint in RepositoryFactRecurrenceRow.__table__.constraints
            if constraint.name == "ck_repository_fact_recurrence_fact_type"
        )
        constraint_sql = str(
            fact_type_constraint.sqltext.compile(dialect=postgresql.dialect())
        )
        for fact_type in _known_investigation_fact_types():
            with self.subTest(fact_type=fact_type):
                self.assertIn(f"'{fact_type}'", constraint_sql)


if __name__ == "__main__":
    unittest.main()

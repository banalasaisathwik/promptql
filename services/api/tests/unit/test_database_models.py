import unittest

from sqlalchemy.dialects import postgresql

from app.database.models import WorkflowRunRow, WorkflowStepRow


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


if __name__ == "__main__":
    unittest.main()

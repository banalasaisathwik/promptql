pass

import unittest

from sqlalchemy.dialects import postgresql

from app.database.models import WorkflowRunRow, WorkflowStepRow


class DatabaseModelTests(unittest.TestCase):
    def test_optional_json_snapshots_bind_none_as_sql_null(self) -> None:
        pass

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

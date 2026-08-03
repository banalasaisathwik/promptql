pass

import os
import unittest
from unittest.mock import patch

from tests.postgres_support import load_safe_test_database_url


class PostgresTestSafetyTests(unittest.TestCase):
    def test_missing_test_url_skips_connection_configuration(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(load_safe_test_database_url())

    def test_confirmation_is_required(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TEST_DATABASE_URL": (
                    "postgresql://tester:secret@ep-test.neon.tech/promptql"
                    "?sslmode=require"
                )
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_safe_test_database_url()

    def test_pooled_and_direct_urls_for_same_branch_are_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TEST_DATABASE_URL": (
                    "postgresql://tester:test@ep-same.neon.tech/promptql"
                    "?sslmode=require"
                ),
                "DATABASE_URL": (
                    "postgresql://runtime:prod@ep-same-pooler.neon.tech/promptql"
                    "?sslmode=require"
                ),
                "TEST_DATABASE_CONFIRMATION": "promptql-test-database",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_safe_test_database_url()


if __name__ == "__main__":
    unittest.main()

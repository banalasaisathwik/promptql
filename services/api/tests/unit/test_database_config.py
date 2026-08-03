pass

import unittest
from types import SimpleNamespace

from app.api.v1.connector_router import get_run_repository
from app.config import DatabaseConfigurationError, parse_postgresql_url
from app.runtime import RunPersistenceError


class DatabaseConfigurationTests(unittest.TestCase):
    def test_neon_style_url_selects_psycopg_without_changing_parts(self) -> None:
        url = parse_postgresql_url(
            "postgresql://runtime:secret@ep-example-pooler.neon.tech/promptql"
            "?sslmode=require",
            "DATABASE_URL",
        )

        self.assertEqual(url.drivername, "postgresql+psycopg")
        self.assertEqual(url.host, "ep-example-pooler.neon.tech")
        self.assertEqual(url.password, "secret")

    def test_missing_tls_is_rejected_without_echoing_secret(self) -> None:
        secret_url = "postgresql://runtime:do-not-print@db.example/promptql"

        with self.assertRaises(DatabaseConfigurationError) as raised:
            parse_postgresql_url(secret_url, "DATABASE_URL")

        self.assertNotIn("do-not-print", str(raised.exception))

    def test_non_postgresql_url_is_rejected(self) -> None:
        with self.assertRaises(DatabaseConfigurationError):
            parse_postgresql_url(
                "sqlite:///runtime.db?sslmode=require",
                "DATABASE_URL",
            )

    def test_repository_dependency_never_falls_back_to_memory(self) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace())
        )

        with self.assertRaises(RunPersistenceError):
            get_run_repository(request)


if __name__ == "__main__":
    unittest.main()

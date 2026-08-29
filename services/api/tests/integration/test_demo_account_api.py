import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class DemoAccountApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_returns_the_configured_demo_email_and_password(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PROMPTQL_DEMO_ACCOUNT_EMAIL": "demo@promptql.dev",
                "PROMPTQL_DEMO_ACCOUNT_PASSWORD": "correct horse battery staple",
            },
            clear=False,
        ):
            response = self.client.get("/v1/demo-account")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"email": "demo@promptql.dev", "password": "correct horse battery staple"},
        )

    def test_unconfigured_demo_account_returns_a_sanitized_503(self) -> None:
        with patch.dict(
            os.environ,
            {"PROMPTQL_DEMO_ACCOUNT_EMAIL": "", "PROMPTQL_DEMO_ACCOUNT_PASSWORD": ""},
            clear=False,
        ):
            response = self.client.get("/v1/demo-account")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["message"], "Demo account is not configured.")


if __name__ == "__main__":
    unittest.main()

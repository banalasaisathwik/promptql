import os
import unittest
from unittest.mock import patch

import httpx

from app.config import SentryConnectorMode, SentrySettings
from app.connectors.errors import SentryConfigurationError
from app.connectors.factory import create_incident_source, create_sentry_http_client
from app.connectors.incident_fakes import FakeIncidentSource
from app.connectors.models import ConnectorSource
from app.connectors.sentry_http import HttpSentrySource
from app.observability import NoOpRuntimeTelemetry


class SentryConnectorFactoryTests(unittest.IsolatedAsyncioTestCase):
    def test_fake_is_the_default_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = SentrySettings.from_environment()

        incident_source = create_incident_source(settings, NoOpRuntimeTelemetry())

        self.assertEqual(settings.mode, SentryConnectorMode.FAKE)
        self.assertIsInstance(incident_source, FakeIncidentSource)
        self.assertEqual(incident_source.source, ConnectorSource.FAKE)

    async def test_sentry_mode_selects_http_source(self) -> None:
        settings = SentrySettings(
            mode=SentryConnectorMode.SENTRY,
            token="local-test-token",
            organization_slug="acme",
            api_base_url="https://sentry.io/api/0",
            request_timeout_seconds=10,
        )
        client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            transport=httpx.MockTransport(lambda _request: httpx.Response(500, json={})),
        )
        incident_source = create_incident_source(settings, NoOpRuntimeTelemetry(), client)
        try:
            self.assertIsInstance(incident_source, HttpSentrySource)
            self.assertEqual(incident_source.source, ConnectorSource.LIVE)
        finally:
            await incident_source.aclose()

    async def test_sentry_http_client_uses_bearer_token_and_timeout(self) -> None:
        settings = SentrySettings(
            mode=SentryConnectorMode.SENTRY,
            token="local-test-token",
            organization_slug="acme",
            api_base_url="https://sentry.io/api/0",
            request_timeout_seconds=7,
        )
        client = create_sentry_http_client(settings)
        try:
            self.assertEqual(
                client.headers["authorization"], "Bearer local-test-token"
            )
            self.assertEqual(client.timeout.read, 7)
        finally:
            await client.aclose()

    def test_missing_live_configuration_fails_clearly(self) -> None:
        required_cases = (
            ({"PROMPTQL_SENTRY_CONNECTOR": "sentry"}, "SENTRY_TOKEN"),
            (
                {
                    "PROMPTQL_SENTRY_CONNECTOR": "sentry",
                    "SENTRY_TOKEN": "local-test-token",
                },
                "SENTRY_ORGANIZATION_SLUG",
            ),
        )
        for environment, expected_name in required_cases:
            with self.subTest(variable=expected_name):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(SentryConfigurationError) as raised:
                        SentrySettings.from_environment()
                self.assertIn(expected_name, str(raised.exception))

    def test_unsupported_mode_and_invalid_organization_slug_fail(self) -> None:
        with patch.dict(
            os.environ,
            {"PROMPTQL_SENTRY_CONNECTOR": "mocked-http"},
            clear=True,
        ):
            with self.assertRaises(SentryConfigurationError) as raised:
                SentrySettings.from_environment()
        self.assertIn("fake or sentry", str(raised.exception))

        for unsafe_slug in ("Acme Inc", "-acme", "acme-", "acme/prod"):
            with self.subTest(slug=unsafe_slug):
                environment = {
                    "PROMPTQL_SENTRY_CONNECTOR": "sentry",
                    "SENTRY_TOKEN": "local-test-token",
                    "SENTRY_ORGANIZATION_SLUG": unsafe_slug,
                }
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(SentryConfigurationError):
                        SentrySettings.from_environment()

    def test_token_is_hidden_from_settings_representation(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PROMPTQL_SENTRY_CONNECTOR": "sentry",
                "SENTRY_TOKEN": "top-secret-token",
                "SENTRY_ORGANIZATION_SLUG": "acme",
            },
            clear=True,
        ):
            settings = SentrySettings.from_environment()

        self.assertNotIn("top-secret-token", repr(settings))


if __name__ == "__main__":
    unittest.main()

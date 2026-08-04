pass

import os
import unittest
from unittest.mock import patch

import httpx

from app.config import GitHubConnectorMode, GitHubSettings
from app.connectors.errors import GitHubConfigurationError
from app.connectors.factory import create_github_connector
from app.connectors.fakes import FakeGitHubConnector
from app.connectors.github_http import HttpGitHubConnector
from app.connectors.models import ConnectorSource
from app.observability import NoOpRuntimeTelemetry


class GitHubConnectorFactoryTests(unittest.IsolatedAsyncioTestCase):
    def test_fake_is_the_default_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = GitHubSettings.from_environment()

        connector = create_github_connector(settings, NoOpRuntimeTelemetry())

        self.assertEqual(settings.mode, GitHubConnectorMode.FAKE)
        self.assertIsInstance(connector, FakeGitHubConnector)
        self.assertEqual(connector.source, ConnectorSource.FAKE)

    async def test_github_mode_selects_http_connector(self) -> None:
        settings = GitHubSettings(
            mode=GitHubConnectorMode.GITHUB,
            token="local-test-token",
            api_base_url="https://api.github.test",
            request_timeout_seconds=10,
        )
        client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(500, json={})
            ),
        )

        connector = create_github_connector(
            settings,
            NoOpRuntimeTelemetry(),
            client,
        )
        try:
            self.assertIsInstance(connector, HttpGitHubConnector)
            self.assertEqual(connector.source, ConnectorSource.LIVE)
        finally:
            await connector.aclose()

    def test_missing_token_fails_in_github_mode(self) -> None:
        with patch.dict(
            os.environ,
            {"PROMPTQL_GITHUB_CONNECTOR": "github"},
            clear=True,
        ):
            with self.assertRaises(GitHubConfigurationError) as raised:
                GitHubSettings.from_environment()

        self.assertNotIn("token=", str(raised.exception).lower())

    def test_unsupported_mode_fails_clearly(self) -> None:
        with patch.dict(
            os.environ,
            {"PROMPTQL_GITHUB_CONNECTOR": "mocked-http"},
            clear=True,
        ):
            with self.assertRaises(GitHubConfigurationError) as raised:
                GitHubSettings.from_environment()

        self.assertIn("fake or github", str(raised.exception))

    def test_token_is_hidden_from_settings_representation(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PROMPTQL_GITHUB_CONNECTOR": "github",
                "GITHUB_TOKEN": "top-secret-token",
            },
            clear=True,
        ):
            settings = GitHubSettings.from_environment()

        self.assertNotIn("top-secret-token", repr(settings))

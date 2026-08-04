pass

import os
import unittest
from unittest.mock import patch

import httpx

from app.config import (
    GitHubConnectorMode,
    GitHubSettings,
    JiraConnectorMode,
    JiraSettings,
)
from app.connectors.errors import JiraConfigurationError
from app.connectors.factory import (
    create_github_connector,
    create_jira_connector,
    create_jira_http_client,
)
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.github_http import HttpGitHubConnector
from app.connectors.jira_http import HttpJiraConnector
from app.connectors.models import ConnectorSource
from app.observability import NoOpRuntimeTelemetry


class JiraConnectorFactoryTests(unittest.IsolatedAsyncioTestCase):
    def test_fake_is_the_default_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = JiraSettings.from_environment()

        connector = create_jira_connector(settings, NoOpRuntimeTelemetry())

        self.assertEqual(settings.mode, JiraConnectorMode.FAKE)
        self.assertIsInstance(connector, FakeJiraConnector)
        self.assertEqual(connector.source, ConnectorSource.FAKE)

    async def test_jira_mode_selects_http_connector(self) -> None:
        settings = JiraSettings(
            mode=JiraConnectorMode.JIRA,
            base_url="https://example.atlassian.net",
            email="connector-user@example.invalid",
            api_token="local-test-token",
            request_timeout_seconds=10,
        )
        client = httpx.AsyncClient(
            base_url=settings.base_url,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(500, json={})
            ),
        )
        connector = create_jira_connector(
            settings,
            NoOpRuntimeTelemetry(),
            client,
        )
        try:
            self.assertIsInstance(connector, HttpJiraConnector)
            self.assertEqual(connector.source, ConnectorSource.LIVE)
        finally:
            await connector.aclose()

    async def test_jira_http_client_uses_explicit_timeout_categories(self) -> None:
        settings = JiraSettings(
            mode=JiraConnectorMode.JIRA,
            base_url="https://example.atlassian.net",
            email="connector-user@example.invalid",
            api_token="local-test-token",
            request_timeout_seconds=7,
        )
        client = create_jira_http_client(settings)
        try:
            self.assertEqual(client.timeout.connect, 7)
            self.assertEqual(client.timeout.read, 7)
            self.assertEqual(client.timeout.write, 7)
            self.assertEqual(client.timeout.pool, 7)
        finally:
            await client.aclose()

    def test_missing_live_configuration_fails_clearly(self) -> None:
        required_cases = (
            ({"PROMPTQL_JIRA_CONNECTOR": "jira"}, "JIRA_BASE_URL"),
            (
                {
                    "PROMPTQL_JIRA_CONNECTOR": "jira",
                    "JIRA_BASE_URL": "https://example.atlassian.net",
                },
                "JIRA_EMAIL",
            ),
            (
                {
                    "PROMPTQL_JIRA_CONNECTOR": "jira",
                    "JIRA_BASE_URL": "https://example.atlassian.net",
                    "JIRA_EMAIL": "connector-user@example.invalid",
                },
                "JIRA_API_TOKEN",
            ),
        )
        for environment, expected_name in required_cases:
            with self.subTest(variable=expected_name):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(JiraConfigurationError) as raised:
                        JiraSettings.from_environment()
                self.assertIn(expected_name, str(raised.exception))

    def test_unsupported_mode_and_unsafe_base_urls_fail(self) -> None:
        with patch.dict(
            os.environ,
            {"PROMPTQL_JIRA_CONNECTOR": "mocked-http"},
            clear=True,
        ):
            with self.assertRaises(JiraConfigurationError) as raised:
                JiraSettings.from_environment()
        self.assertIn("fake or jira", str(raised.exception))

        for unsafe_url in (
            "http://example.atlassian.net",
            "https://user:secret@example.atlassian.net",
            "https://example.invalid",
            "https://example.atlassian.net/path",
        ):
            with self.subTest(url=unsafe_url):
                environment = {
                    "PROMPTQL_JIRA_CONNECTOR": "jira",
                    "JIRA_BASE_URL": unsafe_url,
                    "JIRA_EMAIL": "connector-user@example.invalid",
                    "JIRA_API_TOKEN": "local-test-token",
                }
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(JiraConfigurationError):
                        JiraSettings.from_environment()

    def test_invalid_account_email_fails_without_exposing_its_value(self) -> None:
        environment = {
            "PROMPTQL_JIRA_CONNECTOR": "jira",
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_EMAIL": "invalid private value",
            "JIRA_API_TOKEN": "local-test-token",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(JiraConfigurationError) as raised:
                JiraSettings.from_environment()

        self.assertNotIn("invalid private value", str(raised.exception))

    def test_base_url_is_normalized_and_secrets_are_hidden_from_repr(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PROMPTQL_JIRA_CONNECTOR": "jira",
                "JIRA_BASE_URL": "https://example.atlassian.net/",
                "JIRA_EMAIL": "connector-user@example.invalid",
                "JIRA_API_TOKEN": "local-test-token",
            },
            clear=True,
        ):
            settings = JiraSettings.from_environment()

        self.assertEqual(settings.base_url, "https://example.atlassian.net")
        self.assertNotIn("connector-user", repr(settings))
        self.assertNotIn("local-test-token", repr(settings))

    async def test_github_and_jira_sources_are_selected_independently(self) -> None:
        fake_github_settings = GitHubSettings(
            GitHubConnectorMode.FAKE,
            None,
            "https://api.github.com",
            10,
        )
        live_github_settings = GitHubSettings(
            GitHubConnectorMode.GITHUB,
            "local-github-token",
            "https://api.github.test",
            10,
        )
        fake_jira_settings = JiraSettings(
            JiraConnectorMode.FAKE,
            None,
            None,
            None,
            10,
        )
        live_jira_settings = JiraSettings(
            JiraConnectorMode.JIRA,
            "https://example.atlassian.net",
            "connector-user@example.invalid",
            "local-jira-token",
            10,
        )
        github_client = httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        )
        jira_client = httpx.AsyncClient(
            base_url="https://example.atlassian.net",
            transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        )
        try:
            combinations = (
                (fake_github_settings, fake_jira_settings, None, None, "fake", "fake"),
                (live_github_settings, fake_jira_settings, github_client, None, "live", "fake"),
                (fake_github_settings, live_jira_settings, None, jira_client, "fake", "live"),
                (live_github_settings, live_jira_settings, github_client, jira_client, "live", "live"),
            )
            for github_settings, jira_settings, github_http, jira_http, expected_github, expected_jira in combinations:
                with self.subTest(sources=(expected_github, expected_jira)):
                    github = create_github_connector(
                        github_settings,
                        NoOpRuntimeTelemetry(),
                        github_http,
                    )
                    jira = create_jira_connector(
                        jira_settings,
                        NoOpRuntimeTelemetry(),
                        jira_http,
                    )
                    self.assertEqual(github.source.value, expected_github)
                    self.assertEqual(jira.source.value, expected_jira)
        finally:
            await github_client.aclose()
            await jira_client.aclose()


if __name__ == "__main__":
    unittest.main()

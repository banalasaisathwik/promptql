import unittest

import httpx

from app.config import GitHubConnectorMode, GitHubSettings
from app.connectors.errors import GitHubConfigurationError
from app.connectors.factory import create_github_code_evidence_source
from app.connectors.github_code_fakes import FakeGitHubCodeEvidenceSource
from app.connectors.github_code_http import HttpGitHubCodeEvidenceSource
from app.observability import NoOpRuntimeTelemetry


class GitHubCodeEvidenceFactoryTests(unittest.IsolatedAsyncioTestCase):
    def test_fake_mode_selects_deterministic_code_evidence_source(self) -> None:
        settings = GitHubSettings(
            mode=GitHubConnectorMode.FAKE,
            token=None,
            api_base_url="https://api.github.com",
            request_timeout_seconds=10,
        )

        source = create_github_code_evidence_source(
            settings,
            NoOpRuntimeTelemetry(),
        )

        self.assertIsInstance(source, FakeGitHubCodeEvidenceSource)

    async def test_live_mode_reuses_application_scoped_http_client(self) -> None:
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

        source = create_github_code_evidence_source(
            settings,
            NoOpRuntimeTelemetry(),
            client,
        )
        try:
            self.assertIsInstance(source, HttpGitHubCodeEvidenceSource)
        finally:
            await source.aclose()

    def test_live_mode_requires_an_application_scoped_client(self) -> None:
        settings = GitHubSettings(
            mode=GitHubConnectorMode.GITHUB,
            token="local-test-token",
            api_base_url="https://api.github.test",
            request_timeout_seconds=10,
        )

        with self.assertRaises(GitHubConfigurationError):
            create_github_code_evidence_source(
                settings,
                NoOpRuntimeTelemetry(),
            )

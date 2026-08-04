pass

import io
import json
import logging
import unittest
from unittest.mock import MagicMock, patch

from app.config import (
    GitHubConnectorMode,
    GitHubSettings,
    JiraConnectorMode,
    JiraSettings,
)
from app.main import create_app
from app.observability import NoOpRuntimeTelemetry, Observability
from app.observability.structured_logging import StructuredEventLogger


class ApplicationStartupLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_logs_selected_github_and_jira_sources(self) -> None:
        log_stream = io.StringIO()
        logger = logging.Logger("promptql.startup.test")
        logger.addHandler(logging.StreamHandler(log_stream))
        observability = Observability(
            runtime_telemetry=NoOpRuntimeTelemetry(),
            event_logger=StructuredEventLogger(logger),
        )
        github_settings = GitHubSettings(
            mode=GitHubConnectorMode.GITHUB,
            token="startup-secret",
            api_base_url="https://api.github.com",
            request_timeout_seconds=10,
        )
        jira_settings = JiraSettings(
            mode=JiraConnectorMode.FAKE,
            base_url=None,
            email=None,
            api_token=None,
            request_timeout_seconds=10,
        )
        engine = MagicMock()

        with (
            patch("app.main.DatabaseSettings.from_environment"),
            patch("app.main.create_database_engine", return_value=engine),
            patch("app.main.verify_database_ready"),
            patch("app.main.create_session_factory", return_value=MagicMock()),
        ):
            application = create_app(
                observability=observability,
                github_settings=github_settings,
                jira_settings=jira_settings,
            )
            async with application.router.lifespan_context(application):
                pass

        event = json.loads(log_stream.getvalue())
        self.assertEqual(event["event"], "runtime.connector_sources.selected")
        self.assertEqual(event["github_source"], "live")
        self.assertEqual(event["jira_source"], "fake")
        serialized_event = log_stream.getvalue()
        self.assertNotIn("startup-secret", serialized_event)
        self.assertNotIn("api.github.com", serialized_event)


if __name__ == "__main__":
    unittest.main()

import unittest

from app.config import (
    GitHubConnectorMode,
    GitHubSettings,
    JiraConnectorMode,
    JiraSettings,
    SentryConnectorMode,
    SentrySettings,
)


class StoredCredentialSettingsTests(unittest.TestCase):
    def test_github_constructor_needs_no_environment_read(self) -> None:
        settings = GitHubSettings.from_stored_credential("stored-token")

        self.assertIs(settings.mode, GitHubConnectorMode.GITHUB)
        self.assertIsNotNone(settings.token)
        self.assertNotIn("stored-token", repr(settings))

    def test_jira_constructor_accepts_explicit_non_secret_context(self) -> None:
        settings = JiraSettings.from_stored_credential(
            "stored-token",
            base_url="https://promptql.atlassian.net",
            email="owner@example.com",
        )

        self.assertIs(settings.mode, JiraConnectorMode.JIRA)
        self.assertIsNotNone(settings.api_token)
        self.assertNotIn("stored-token", repr(settings))

    def test_sentry_constructor_accepts_explicit_non_secret_context(self) -> None:
        settings = SentrySettings.from_stored_credential(
            "stored-token", organization_slug="promptql"
        )

        self.assertIs(settings.mode, SentryConnectorMode.SENTRY)
        self.assertIsNotNone(settings.token)
        self.assertNotIn("stored-token", repr(settings))


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.v1.auth_router import (
    SESSION_COOKIE_NAME,
    get_current_user_optional,
    get_session_signer,
    get_user_repository,
)
from app.api.v1.credentials_router import get_credential_repository
from app.auth import (
    CredentialProvider,
    InMemoryCredentialRepository,
    InMemoryUserRepository,
    SessionSigner,
)
from app.connectors.errors import (
    GitHubUnauthorizedError,
    GitHubUpstreamUnavailableError,
    SentryUnauthorizedError,
    SentryUpstreamUnavailableError,
)
from app.main import app


class _GitHubDiscovery:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def get_authenticated_context(self):
        return "octocat", (
            SimpleNamespace(
                owner=SimpleNamespace(login="octo-org"),
                name="collaborator-repo",
                full_name="octo-org/collaborator-repo",
                private=True,
                default_branch="main",
            ),
        )


class _InvalidGitHubDiscovery:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def get_authenticated_context(self):
        raise GitHubUnauthorizedError()


class _UnavailableGitHubDiscovery:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def get_authenticated_context(self):
        raise GitHubUpstreamUnavailableError()


class _SentryDiscovery:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def list_accessible_projects(self):
        return (SimpleNamespace(slug="python-fastapi", name="Python FastAPI"),)


class _InvalidSentryDiscovery:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def list_accessible_projects(self):
        raise SentryUnauthorizedError()


class _UnavailableSentryDiscovery:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def list_accessible_projects(self):
        raise SentryUpstreamUnavailableError()


class SourceDiscoveryApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SENTRY_ORGANIZATION_SLUG": "student-whe",
            },
            clear=False,
        )
        self.environment.start()
        self.users = InMemoryUserRepository()
        self.user = self.users.create_user(
            "discovery@example.com", "correct horse battery staple"
        )
        self.credentials = InMemoryCredentialRepository()
        self.signer = SessionSigner(
            secret_key="test-only-secret-key-32-characters!!", max_age_seconds=3600
        )
        app.dependency_overrides[get_user_repository] = lambda: self.users
        app.dependency_overrides[get_session_signer] = lambda: self.signer


        app.dependency_overrides[get_current_user_optional] = lambda: self.user
        app.dependency_overrides[get_credential_repository] = lambda: self.credentials

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.environment.stop()

    def _headers(self) -> dict[str, str]:
        return {"cookie": f"{SESSION_COOKIE_NAME}={self.signer.sign(self.user.id)}"}

    def test_missing_credential_returns_409_before_a_provider_call(self) -> None:
        response = self.client.get("/v1/github/context", headers=self._headers())

        self.assertEqual(response.status_code, 409)
        self.assertNotIn("token", response.text.lower())

    def test_github_context_returns_only_selector_fields(self) -> None:
        self.credentials.store_credential(
            self.user.id, CredentialProvider.GITHUB, "test-github-token"
        )
        with patch(
            "app.api.v1.source_discovery_router.HttpGitHubConnector",
            _GitHubDiscovery,
        ):
            response = self.client.get("/v1/github/context", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["login"], "octocat")
        self.assertEqual(
            response.json()["repositories"][0]["full_name"],
            "octo-org/collaborator-repo",
        )
        self.assertNotIn("token", response.text.lower())

    def test_invalid_github_credential_is_a_typed_sanitized_error(self) -> None:
        self.credentials.store_credential(
            self.user.id, CredentialProvider.GITHUB, "test-github-token"
        )
        with patch(
            "app.api.v1.source_discovery_router.HttpGitHubConnector",
            _InvalidGitHubDiscovery,
        ):
            response = self.client.get("/v1/github/context", headers=self._headers())

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "credential_invalid")
        self.assertNotIn("token", response.text.lower())

    def test_github_provider_failure_is_sanitized(self) -> None:
        self.credentials.store_credential(
            self.user.id, CredentialProvider.GITHUB, "test-github-token"
        )
        with patch(
            "app.api.v1.source_discovery_router.HttpGitHubConnector",
            _UnavailableGitHubDiscovery,
        ):
            response = self.client.get("/v1/github/context", headers=self._headers())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "provider_unavailable")
        self.assertNotIn("token", response.text.lower())

    def test_missing_sentry_credential_returns_409(self) -> None:
        response = self.client.get("/v1/sentry/projects", headers=self._headers())

        self.assertEqual(response.status_code, 409)
        self.assertNotIn("token", response.text.lower())

    def test_sentry_projects_return_only_selector_fields(self) -> None:
        self.credentials.store_credential(
            self.user.id, CredentialProvider.SENTRY, "test-sentry-token"
        )
        with patch(
            "app.api.v1.source_discovery_router.HttpSentrySource", _SentryDiscovery
        ):
            response = self.client.get("/v1/sentry/projects", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{
                "organization_slug": "student-whe",
                "project_slug": "python-fastapi",
                "name": "Python FastAPI",
            }],
        )
        self.assertNotIn("token", response.text.lower())

    def test_sentry_missing_organization_configuration_is_unavailable(self) -> None:
        self.credentials.store_credential(
            self.user.id, CredentialProvider.SENTRY, "test-sentry-token"
        )
        with patch.dict(os.environ, {"SENTRY_ORGANIZATION_SLUG": ""}):
            response = self.client.get("/v1/sentry/projects", headers=self._headers())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "provider_unavailable")
        self.assertNotIn("token", response.text.lower())

    def test_invalid_sentry_credential_is_a_typed_sanitized_error(self) -> None:
        self.credentials.store_credential(
            self.user.id, CredentialProvider.SENTRY, "test-sentry-token"
        )
        with patch(
            "app.api.v1.source_discovery_router.HttpSentrySource", _InvalidSentryDiscovery
        ):
            response = self.client.get("/v1/sentry/projects", headers=self._headers())

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "credential_invalid")
        self.assertNotIn("token", response.text.lower())

    def test_sentry_provider_failure_is_sanitized(self) -> None:
        self.credentials.store_credential(
            self.user.id, CredentialProvider.SENTRY, "test-sentry-token"
        )
        with patch(
            "app.api.v1.source_discovery_router.HttpSentrySource",
            _UnavailableSentryDiscovery,
        ):
            response = self.client.get("/v1/sentry/projects", headers=self._headers())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "provider_unavailable")
        self.assertNotIn("token", response.text.lower())

import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.v1.auth_router import (
    SESSION_COOKIE_NAME,
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
from app.main import app


class CredentialsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {"PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode()},
            clear=False,
        )
        self.environment.start()
        self.user_repository = InMemoryUserRepository()
        self.current_user = self.user_repository.create_user(
            "credential@example.com", "correct horse battery staple"
        )
        self.session_signer = SessionSigner(
            secret_key="test-only-secret-key-32-characters!!",
            max_age_seconds=3600,
        )
        self.credential_repository = InMemoryCredentialRepository()
        app.dependency_overrides[get_user_repository] = lambda: self.user_repository
        app.dependency_overrides[get_session_signer] = lambda: self.session_signer
        app.dependency_overrides[get_credential_repository] = (
            lambda: self.credential_repository
        )

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.environment.stop()

    def _authenticated_headers(self) -> dict[str, str]:
        return {
            "cookie": (
                f"{SESSION_COOKIE_NAME}={self.session_signer.sign(self.current_user.id)}"
            )
        }

    def test_store_and_list_return_only_provider_connection_status(self) -> None:
        stored = self.client.post(
            "/v1/credentials",
            headers=self._authenticated_headers(),
            json={"provider": "github", "token": "test-token-value"},
        )

        self.assertEqual(stored.status_code, 200)
        self.assertEqual(
            stored.json(),
            {"provider": "github", "connected": True, "source": "real"},
        )
        self.assertNotIn("token", stored.text.lower())

        listed = self.client.get(
            "/v1/credentials", headers=self._authenticated_headers()
        )

        self.assertEqual(listed.status_code, 200)
        self.assertNotIn("token", listed.text.lower())
        providers = {item["provider"]: item["connected"] for item in listed.json()["providers"]}
        self.assertEqual(providers, {"github": True, "jira": False, "sentry": False})

    def test_delete_removes_only_the_requested_provider(self) -> None:
        self.credential_repository.store_credential(
            self.current_user.id, CredentialProvider.JIRA, "test-token-value"
        )

        deleted = self.client.delete(
            "/v1/credentials/jira", headers=self._authenticated_headers()
        )

        self.assertEqual(deleted.status_code, 204)
        self.assertNotIn("token", deleted.text.lower())
        self.assertEqual(
            self.credential_repository.list_connected_providers(self.current_user.id), ()
        )

    def test_all_three_provider_connection_routes_share_the_same_safe_contract(self) -> None:
        for provider in CredentialProvider:
            stored = self.client.post(
                "/v1/credentials",
                headers=self._authenticated_headers(),
                json={"provider": provider.value, "token": f"test-{provider.value}-token"},
            )
            self.assertEqual(stored.status_code, 200)
            self.assertEqual(stored.json()["provider"], provider.value)
            self.assertTrue(stored.json()["connected"])
            self.assertNotIn("token", stored.text.lower())

            deleted = self.client.delete(
                f"/v1/credentials/{provider.value}",
                headers=self._authenticated_headers(),
            )
            self.assertEqual(deleted.status_code, 204)

        listed = self.client.get("/v1/credentials", headers=self._authenticated_headers())
        self.assertEqual(
            {item["provider"]: item["connected"] for item in listed.json()["providers"]},
            {"github": False, "jira": False, "sentry": False},
        )

    def test_anonymous_requests_never_receive_credential_fields(self) -> None:
        response = self.client.get("/v1/credentials")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("token", response.text.lower())

    def test_missing_encryption_key_returns_a_sanitized_503(self) -> None:
        with patch.dict(os.environ, {"PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": ""}):
            response = self.client.post(
                "/v1/credentials",
                headers=self._authenticated_headers(),
                json={"provider": "github", "token": "test-token-value"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["message"], "Credential storage is unavailable.")
        self.assertNotIn("token", response.text.lower())


class _NeverCalledCredentialRepository:
    def store_credential(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("store_credential must not be called for a demo user")

    def get_decrypted_credential(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("get_decrypted_credential must not be called for a demo user")

    def list_connected_providers(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("list_connected_providers must not be called for a demo user")

    def delete_credential(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("delete_credential must not be called for a demo user")


class DemoAccountCredentialsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {"PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode()},
            clear=False,
        )
        self.environment.start()
        self.user_repository = InMemoryUserRepository()
        self.demo_user = self.user_repository.create_user(
            "demo@example.com", "correct horse battery staple", is_demo=True
        )
        self.session_signer = SessionSigner(
            secret_key="test-only-secret-key-32-characters!!",
            max_age_seconds=3600,
        )
        app.dependency_overrides[get_user_repository] = lambda: self.user_repository
        app.dependency_overrides[get_session_signer] = lambda: self.session_signer
        app.dependency_overrides[get_credential_repository] = (
            lambda: _NeverCalledCredentialRepository()
        )

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.environment.stop()

    def _authenticated_headers(self) -> dict[str, str]:
        return {
            "cookie": (
                f"{SESSION_COOKIE_NAME}={self.session_signer.sign(self.demo_user.id)}"
            )
        }

    def test_get_shows_all_three_providers_connected_with_demo_source(self) -> None:
        response = self.client.get(
            "/v1/credentials", headers=self._authenticated_headers()
        )

        self.assertEqual(response.status_code, 200)
        providers = {
            item["provider"]: (item["connected"], item["source"])
            for item in response.json()["providers"]
        }
        self.assertEqual(
            providers,
            {
                "github": (True, "demo"),
                "jira": (True, "demo"),
                "sentry": (True, "demo"),
            },
        )

    def test_post_is_rejected_with_403_and_does_not_touch_storage(self) -> None:
        response = self.client.post(
            "/v1/credentials",
            headers=self._authenticated_headers(),
            json={"provider": "github", "token": "irrelevant-token"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {
                "code": "demo_account_credentials_immutable",
                "message": "Demo workspace credentials cannot be changed.",
            },
        )

    def test_delete_is_rejected_with_403_and_does_not_touch_storage(self) -> None:
        response = self.client.delete(
            "/v1/credentials/github", headers=self._authenticated_headers()
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {
                "code": "demo_account_credentials_immutable",
                "message": "Demo workspace credentials cannot be changed.",
            },
        )


if __name__ == "__main__":
    unittest.main()

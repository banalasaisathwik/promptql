import unittest

from fastapi.testclient import TestClient

from app.api.v1.auth_router import SESSION_COOKIE_NAME, get_session_signer, get_user_repository
from app.auth import InMemoryUserRepository, SessionSigner
from app.main import app


class AuthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.client.cookies.clear()
        self.user_repository = InMemoryUserRepository()
        self.session_signer = SessionSigner(
            secret_key="test-only-secret-key-32-characters!!",
            max_age_seconds=3600,
        )
        app.dependency_overrides[get_user_repository] = lambda: self.user_repository
        app.dependency_overrides[get_session_signer] = lambda: self.session_signer

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_register_creates_a_user_and_sets_the_session_cookie(self) -> None:
        response = self.client.post(
            "/v1/auth/register",
            json={
                "email": "New.User@example.com",
                "password": "correct horse battery staple",
            },
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["email"], "new.user@example.com")
        self.assertIn(f"{SESSION_COOKIE_NAME}=", response.headers.get("set-cookie", ""))

    def test_duplicate_email_registration_returns_409(self) -> None:
        self.user_repository.create_user(
            "dup@example.com", "correct horse battery staple"
        )

        response = self.client.post(
            "/v1/auth/register",
            json={"email": "dup@example.com", "password": "another password"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "user_already_exists")

    def test_registering_with_a_short_password_returns_a_validation_error(self) -> None:
        response = self.client.post(
            "/v1/auth/register",
            json={"email": "short@example.com", "password": "short"},
        )

        self.assertEqual(response.status_code, 422)

    def test_login_with_correct_credentials_sets_the_session_cookie(self) -> None:
        self.user_repository.create_user(
            "login@example.com", "correct horse battery staple"
        )

        response = self.client.post(
            "/v1/auth/login",
            json={
                "email": "login@example.com",
                "password": "correct horse battery staple",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "login@example.com")
        self.assertIn(f"{SESSION_COOKIE_NAME}=", response.headers.get("set-cookie", ""))

    def test_login_with_incorrect_password_returns_401(self) -> None:
        self.user_repository.create_user(
            "login2@example.com", "correct horse battery staple"
        )

        response = self.client.post(
            "/v1/auth/login",
            json={"email": "login2@example.com", "password": "wrong password"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")

    def test_login_with_unknown_email_returns_401(self) -> None:
        response = self.client.post(
            "/v1/auth/login",
            json={"email": "unknown@example.com", "password": "whatever password"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")

    def test_logout_clears_the_session_cookie(self) -> None:
        response = self.client.post("/v1/auth/logout")

        self.assertEqual(response.status_code, 204)
        set_cookie_header = response.headers.get("set-cookie", "")
        self.assertIn(f"{SESSION_COOKIE_NAME}=", set_cookie_header)
        self.assertIn("Max-Age=0", set_cookie_header)

    def test_me_returns_the_current_public_user_for_a_valid_session(self) -> None:
        user = self.user_repository.create_user(
            "me@example.com", "correct horse battery staple"
        )

        response = self.client.get(
            "/v1/auth/me",
            headers={"cookie": f"{SESSION_COOKIE_NAME}={self.session_signer.sign(user.id)}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(user.id))
        self.assertEqual(response.json()["email"], "me@example.com")
        self.assertNotIn("password", response.text.lower())

    def test_me_rejects_a_missing_or_tampered_session(self) -> None:
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)
        self.assertEqual(
            self.client.get(
                "/v1/auth/me",
                headers={"cookie": f"{SESSION_COOKIE_NAME}=tampered-session"},
            ).status_code,
            401,
        )

    def test_me_is_unauthenticated_after_logout_clears_the_browser_cookie(self) -> None:
        self.user_repository.create_user(
            "logout@example.com", "correct horse battery staple"
        )
        login = self.client.post(
            "/v1/auth/login",
            json={"email": "logout@example.com", "password": "correct horse battery staple"},
        )
        self.assertEqual(login.status_code, 200)

        self.assertEqual(self.client.post("/v1/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)


if __name__ == "__main__":
    unittest.main()

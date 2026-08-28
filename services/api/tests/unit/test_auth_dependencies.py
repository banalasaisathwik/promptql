import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException

from app.api.v1.auth_router import SESSION_COOKIE_NAME, get_current_user
from app.auth import InMemoryUserRepository, SessionSigner


def _request_with_cookie(cookie_value: str | None) -> SimpleNamespace:
    cookies = {} if cookie_value is None else {SESSION_COOKIE_NAME: cookie_value}
    return SimpleNamespace(cookies=cookies)


class GetCurrentUserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_repository = InMemoryUserRepository()
        self.session_signer = SessionSigner(secret_key="a" * 32, max_age_seconds=3600)
        self.user = self.user_repository.create_user(
            "dep@example.com", "correct horse battery staple"
        )

    def test_a_valid_session_cookie_resolves_the_user(self) -> None:
        token = self.session_signer.sign(self.user.id)
        request = _request_with_cookie(token)

        resolved_user = get_current_user(
            request, self.user_repository, self.session_signer
        )

        self.assertEqual(resolved_user.id, self.user.id)

    def test_a_missing_cookie_raises_401(self) -> None:
        request = _request_with_cookie(None)

        with self.assertRaises(HTTPException) as raised:
            get_current_user(request, self.user_repository, self.session_signer)
        self.assertEqual(raised.exception.status_code, 401)

    def test_an_invalid_cookie_raises_401(self) -> None:
        request = _request_with_cookie("not-a-real-token")

        with self.assertRaises(HTTPException) as raised:
            get_current_user(request, self.user_repository, self.session_signer)
        self.assertEqual(raised.exception.status_code, 401)

    def test_a_validly_signed_token_for_a_nonexistent_user_raises_401(self) -> None:
        token = self.session_signer.sign(uuid4())
        request = _request_with_cookie(token)

        with self.assertRaises(HTTPException) as raised:
            get_current_user(request, self.user_repository, self.session_signer)
        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch
from uuid import uuid4

from itsdangerous import URLSafeTimedSerializer
from itsdangerous.timed import TimestampSigner

from app.auth.session import SessionSigner, _SESSION_SALT


class SessionSignerTests(unittest.TestCase):
    def test_a_freshly_signed_token_is_accepted(self) -> None:
        signer = SessionSigner(secret_key="a" * 32, max_age_seconds=60)
        user_id = uuid4()

        token = signer.sign(user_id)

        self.assertEqual(signer.unsign(token), user_id)

    def test_a_tampered_token_is_rejected(self) -> None:
        signer = SessionSigner(secret_key="a" * 32, max_age_seconds=60)
        token = signer.sign(uuid4())


        signature_start = token.rfind(".") + 1
        tamper_index = signature_start + 1
        replacement_character = "a" if token[tamper_index] != "a" else "b"
        tampered_token = (
            token[:tamper_index] + replacement_character + token[tamper_index + 1 :]
        )

        self.assertIsNone(signer.unsign(tampered_token))

    def test_a_token_signed_with_a_different_secret_is_rejected(self) -> None:
        signer = SessionSigner(secret_key="a" * 32, max_age_seconds=60)
        other_signer = SessionSigner(secret_key="b" * 32, max_age_seconds=60)
        token = other_signer.sign(uuid4())

        self.assertIsNone(signer.unsign(token))

    def test_an_expired_token_is_rejected(self) -> None:
        signer = SessionSigner(secret_key="a" * 32, max_age_seconds=60)


        long_ago_timestamp = 0
        with patch.object(
            TimestampSigner, "get_timestamp", return_value=long_ago_timestamp
        ):
            token = signer.sign(uuid4())

        self.assertIsNone(signer.unsign(token))

    def test_an_unsigned_garbage_string_is_rejected(self) -> None:
        signer = SessionSigner(secret_key="a" * 32, max_age_seconds=60)

        self.assertIsNone(signer.unsign("not-a-real-token"))

    def test_a_token_signed_for_a_non_uuid_payload_is_rejected(self) -> None:
        signer = SessionSigner(secret_key="a" * 32, max_age_seconds=60)
        raw_serializer = URLSafeTimedSerializer("a" * 32, salt=_SESSION_SALT)
        token = raw_serializer.dumps("not-a-uuid")

        self.assertIsNone(signer.unsign(token))


if __name__ == "__main__":
    unittest.main()

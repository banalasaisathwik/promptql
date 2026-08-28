import os
import secrets
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.auth import CredentialConfigurationError, TokenCipher


class TokenCipherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {"PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode()},
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()

    def test_encrypt_then_decrypt_round_trips_a_token(self) -> None:
        cipher = TokenCipher()

        ciphertext = cipher.encrypt("test-token-value")

        self.assertTrue(ciphertext.startswith(b"gAAAA"))
        self.assertTrue(secrets.compare_digest(cipher.decrypt(ciphertext), "test-token-value"))

    def test_missing_key_has_a_specific_configuration_error(self) -> None:
        with patch.dict(os.environ, {"PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": ""}):
            with self.assertRaisesRegex(
                CredentialConfigurationError,
                "PROMPTQL_CREDENTIAL_ENCRYPTION_KEY is required",
            ):
                TokenCipher().encrypt("test-token-value")

    def test_malformed_key_has_a_specific_configuration_error(self) -> None:
        with patch.dict(
            os.environ, {"PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": "not-a-fernet-key"}
        ):
            with self.assertRaisesRegex(
                CredentialConfigurationError,
                "PROMPTQL_CREDENTIAL_ENCRYPTION_KEY must be a well-formed Fernet key",
            ):
                TokenCipher().encrypt("test-token-value")


if __name__ == "__main__":
    unittest.main()

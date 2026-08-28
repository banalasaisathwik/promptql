import os

from cryptography.fernet import Fernet, InvalidToken

from app.auth.errors import CredentialConfigurationError, CredentialDecryptionError

_CREDENTIAL_ENCRYPTION_KEY_ENVIRONMENT_VARIABLE = (
    "PROMPTQL_CREDENTIAL_ENCRYPTION_KEY"
)


class TokenCipher:
    def _fernet(self) -> Fernet:
        key = os.environ.get(_CREDENTIAL_ENCRYPTION_KEY_ENVIRONMENT_VARIABLE, "").strip()
        if not key:
            raise CredentialConfigurationError(
                "PROMPTQL_CREDENTIAL_ENCRYPTION_KEY is required for credential storage."
            )
        try:
            return Fernet(key.encode("ascii"))
        except (UnicodeEncodeError, ValueError):
            raise CredentialConfigurationError(
                "PROMPTQL_CREDENTIAL_ENCRYPTION_KEY must be a well-formed Fernet key."
            ) from None

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet().encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet().decrypt(ciphertext).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            raise CredentialDecryptionError(
                "Stored credential ciphertext could not be decrypted."
            ) from None

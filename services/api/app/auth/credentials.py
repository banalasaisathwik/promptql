from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.auth.token_cipher import TokenCipher


class CredentialProvider(StrEnum):
    GITHUB = "github"
    JIRA = "jira"
    SENTRY = "sentry"


@dataclass(frozen=True)
class StoredCredential:
    user_id: UUID
    provider: CredentialProvider
    encrypted_token: bytes = field(repr=False)


class CredentialRepository(Protocol):
    def store_credential(
        self, user_id: UUID, provider: CredentialProvider, plaintext_token: str
    ) -> None: ...

    def get_decrypted_credential(
        self, user_id: UUID, provider: CredentialProvider
    ) -> str | None: ...

    def list_connected_providers(self, user_id: UUID) -> tuple[CredentialProvider, ...]: ...

    def delete_credential(self, user_id: UUID, provider: CredentialProvider) -> bool: ...


class InMemoryCredentialRepository:
    def __init__(self, cipher: TokenCipher | None = None) -> None:
        self._cipher = cipher or TokenCipher()
        self._credentials: dict[tuple[UUID, CredentialProvider], StoredCredential] = {}

    def store_credential(
        self, user_id: UUID, provider: CredentialProvider, plaintext_token: str
    ) -> None:
        self._credentials[(user_id, provider)] = StoredCredential(
            user_id=user_id,
            provider=provider,
            encrypted_token=self._cipher.encrypt(plaintext_token),
        )

    def get_decrypted_credential(
        self, user_id: UUID, provider: CredentialProvider
    ) -> str | None:
        credential = self._credentials.get((user_id, provider))
        if credential is None:
            return None
        return self._cipher.decrypt(credential.encrypted_token)

    def list_connected_providers(self, user_id: UUID) -> tuple[CredentialProvider, ...]:
        return tuple(
            provider
            for provider in CredentialProvider
            if (user_id, provider) in self._credentials
        )

    def delete_credential(self, user_id: UUID, provider: CredentialProvider) -> bool:
        return self._credentials.pop((user_id, provider), None) is not None

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.credentials import CredentialProvider, CredentialRepository
from app.auth.errors import AuthPersistenceError
from app.auth.token_cipher import TokenCipher
from app.database.models import CredentialRow


class PostgresCredentialRepository(CredentialRepository):
    def __init__(
        self, session_factory: sessionmaker[Session], cipher: TokenCipher | None = None
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher or TokenCipher()

    def store_credential(
        self, user_id: UUID, provider: CredentialProvider, plaintext_token: str
    ) -> None:
        encrypted_token = self._cipher.encrypt(plaintext_token)
        now = datetime.now(timezone.utc)
        statement = insert(CredentialRow).values(
            user_id=user_id,
            provider=provider.value,
            encrypted_token=encrypted_token,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_credentials_user_provider",
            set_={
                "encrypted_token": statement.excluded.encrypted_token,
                "updated_at": statement.excluded.updated_at,
            },
        )
        try:
            with self._session_factory.begin() as session:
                session.execute(statement)
        except SQLAlchemyError:
            raise AuthPersistenceError("Auth persistence is unavailable.") from None

    def get_decrypted_credential(
        self, user_id: UUID, provider: CredentialProvider
    ) -> str | None:
        try:
            with self._session_factory() as session:
                encrypted_token = session.execute(
                    select(CredentialRow.encrypted_token).where(
                        CredentialRow.user_id == user_id,
                        CredentialRow.provider == provider.value,
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError:
            raise AuthPersistenceError("Auth persistence is unavailable.") from None
        if encrypted_token is None:
            return None
        return self._cipher.decrypt(encrypted_token)

    def list_connected_providers(self, user_id: UUID) -> tuple[CredentialProvider, ...]:
        try:
            with self._session_factory() as session:
                stored_providers = session.execute(
                    select(CredentialRow.provider).where(CredentialRow.user_id == user_id)
                ).scalars()
                return tuple(CredentialProvider(provider) for provider in stored_providers)
        except SQLAlchemyError:
            raise AuthPersistenceError("Auth persistence is unavailable.") from None

    def delete_credential(self, user_id: UUID, provider: CredentialProvider) -> bool:
        try:
            with self._session_factory.begin() as session:
                result = session.execute(
                    delete(CredentialRow).where(
                        CredentialRow.user_id == user_id,
                        CredentialRow.provider == provider.value,
                    )
                )
        except SQLAlchemyError:
            raise AuthPersistenceError("Auth persistence is unavailable.") from None
        return result.rowcount > 0

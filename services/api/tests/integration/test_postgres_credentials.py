import os
import secrets
import unittest
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import delete, inspect, select

from app.auth import CredentialProvider
from app.config import DatabaseSettings
from app.database import (
    PostgresCredentialRepository,
    PostgresUserRepository,
    create_database_engine,
    create_session_factory,
)
from app.database.models import CredentialRow, UserRow
from tests.postgres_support import load_safe_test_database_url


TEST_DATABASE_URL = load_safe_test_database_url()


@unittest.skipUnless(
    TEST_DATABASE_URL is not None,
    "TEST_DATABASE_URL is not configured; PostgreSQL credential storage was not verified.",
)
class PostgresCredentialRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert TEST_DATABASE_URL is not None
        api_root = Path(__file__).resolve().parents[2]
        alembic_config = Config(str(api_root / "alembic.ini"))
        previous_migration_url = os.environ.get("DATABASE_MIGRATION_URL")
        previous_encryption_key = os.environ.get("PROMPTQL_CREDENTIAL_ENCRYPTION_KEY")
        cls._previous_encryption_key = previous_encryption_key
        os.environ["DATABASE_MIGRATION_URL"] = TEST_DATABASE_URL.render_as_string(
            hide_password=False
        )
        os.environ["PROMPTQL_CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        try:
            command.upgrade(alembic_config, "head")
        finally:
            if previous_migration_url is None:
                os.environ.pop("DATABASE_MIGRATION_URL", None)
            else:
                os.environ["DATABASE_MIGRATION_URL"] = previous_migration_url

        cls.engine = create_database_engine(DatabaseSettings(TEST_DATABASE_URL))
        cls.session_factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        if cls._previous_encryption_key is None:
            os.environ.pop("PROMPTQL_CREDENTIAL_ENCRYPTION_KEY", None)
        else:
            os.environ["PROMPTQL_CREDENTIAL_ENCRYPTION_KEY"] = cls._previous_encryption_key

    def setUp(self) -> None:
        self.user_repository = PostgresUserRepository(self.session_factory)
        self.credential_repository = PostgresCredentialRepository(self.session_factory)
        self.created_user_ids = []

    def tearDown(self) -> None:
        if not self.created_user_ids:
            return
        with self.session_factory.begin() as session:
            session.execute(delete(UserRow).where(UserRow.id.in_(self.created_user_ids)))

    def test_migration_creates_credential_table(self) -> None:
        self.assertIn("credentials", inspect(self.engine).get_table_names())

    def test_upsert_encrypts_and_replaces_a_users_provider_token(self) -> None:
        user = self.user_repository.create_user(
            f"credential-{uuid4()}@example.com", "correct horse battery staple"
        )
        self.created_user_ids.append(user.id)

        self.credential_repository.store_credential(
            user.id, CredentialProvider.GITHUB, "first-test-token"
        )
        self.credential_repository.store_credential(
            user.id, CredentialProvider.GITHUB, "replacement-test-token"
        )

        decrypted = self.credential_repository.get_decrypted_credential(
            user.id, CredentialProvider.GITHUB
        )
        self.assertIsNotNone(decrypted)
        self.assertTrue(secrets.compare_digest(decrypted or "", "replacement-test-token"))
        self.assertEqual(
            self.credential_repository.list_connected_providers(user.id),
            (CredentialProvider.GITHUB,),
        )
        with self.session_factory() as session:
            encrypted_tokens = session.execute(
                select(CredentialRow.encrypted_token).where(
                    CredentialRow.user_id == user.id,
                    CredentialRow.provider == CredentialProvider.GITHUB.value,
                )
            ).scalars().all()

        self.assertEqual(len(encrypted_tokens), 1)
        self.assertTrue(encrypted_tokens[0].startswith(b"gAAAA"))


if __name__ == "__main__":
    unittest.main()

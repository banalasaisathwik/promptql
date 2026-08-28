from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.errors import AuthPersistenceError, UserAlreadyExistsError
from app.auth.models import User
from app.auth.repository import normalize_email
from app.auth.security import hash_password, verify_password
from app.database.models import UserRow


def _read_user(row: UserRow) -> User:
    return User(id=row.id, email=row.email, created_at=row.created_at)


class PostgresUserRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_user(self, email: str, password: str) -> User:
        normalized_email = normalize_email(email)
        password_hash = hash_password(password)
        user_id = uuid4()
        created_at = datetime.now(timezone.utc)
        row = UserRow(
            id=user_id,
            email=normalized_email,
            password_hash=password_hash,
            created_at=created_at,
        )
        try:
            with self._session_factory.begin() as session:
                session.add(row)
        except IntegrityError:
            raise UserAlreadyExistsError(normalized_email) from None
        except SQLAlchemyError:
            raise AuthPersistenceError("Auth persistence is unavailable.") from None
        return User(id=user_id, email=normalized_email, created_at=created_at)

    def authenticate(self, email: str, password: str) -> User | None:
        normalized_email = normalize_email(email)
        try:
            with self._session_factory() as session:
                row = session.execute(
                    select(UserRow).where(UserRow.email == normalized_email)
                ).scalar_one_or_none()
        except SQLAlchemyError:
            raise AuthPersistenceError("Auth persistence is unavailable.") from None
        if row is None:
            return None
        if not verify_password(password, row.password_hash):
            return None
        return _read_user(row)

    def get_by_id(self, user_id: UUID) -> User | None:
        try:
            with self._session_factory() as session:
                row = session.get(UserRow, user_id)
        except SQLAlchemyError:
            raise AuthPersistenceError("Auth persistence is unavailable.") from None
        if row is None:
            return None
        return _read_user(row)

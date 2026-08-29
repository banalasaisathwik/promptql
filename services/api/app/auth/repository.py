from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from app.auth.errors import UserAlreadyExistsError
from app.auth.models import User
from app.auth.security import hash_password, verify_password


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserRepository(Protocol):
    def create_user(
        self, email: str, password: str, is_demo: bool = False
    ) -> User: ...

    def authenticate(self, email: str, password: str) -> User | None: ...

    def get_by_id(self, user_id: UUID) -> User | None: ...


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users_by_id: dict[UUID, User] = {}
        self._password_hashes_by_id: dict[UUID, str] = {}
        self._user_ids_by_email: dict[str, UUID] = {}

    def create_user(self, email: str, password: str, is_demo: bool = False) -> User:
        normalized_email = normalize_email(email)
        if normalized_email in self._user_ids_by_email:
            raise UserAlreadyExistsError(normalized_email)
        user = User(
            id=uuid4(),
            email=normalized_email,
            created_at=datetime.now(timezone.utc),
            is_demo=is_demo,
        )
        self._users_by_id[user.id] = user
        self._password_hashes_by_id[user.id] = hash_password(password)
        self._user_ids_by_email[normalized_email] = user.id
        return user

    def authenticate(self, email: str, password: str) -> User | None:
        user_id = self._user_ids_by_email.get(normalize_email(email))
        if user_id is None:
            return None
        if not verify_password(password, self._password_hashes_by_id[user_id]):
            return None
        return self._users_by_id[user_id]

    def get_by_id(self, user_id: UUID) -> User | None:
        return self._users_by_id.get(user_id)

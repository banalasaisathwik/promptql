from uuid import UUID

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SESSION_SALT = "promptql.auth.session"


class SessionSigner:
    def __init__(self, secret_key: str, max_age_seconds: int) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key, salt=_SESSION_SALT)
        self.max_age_seconds = max_age_seconds

    def sign(self, user_id: UUID) -> str:
        return self._serializer.dumps(str(user_id))

    def unsign(self, token: str) -> UUID | None:
        try:
            raw_user_id = self._serializer.loads(token, max_age=self.max_age_seconds)
        except (BadSignature, SignatureExpired):
            return None
        try:
            return UUID(raw_user_id)
        except (ValueError, TypeError):
            return None

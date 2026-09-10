from uuid import UUID

from pydantic import AwareDatetime

from app.connectors.models import ContractModel, NonEmptyString


class User(ContractModel):
    id: UUID
    email: NonEmptyString
    created_at: AwareDatetime
    is_demo: bool = False

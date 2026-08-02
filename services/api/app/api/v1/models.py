pass

from enum import StrEnum

from app.connectors.models import ContractModel, NonEmptyString


class ApiErrorCode(StrEnum):
    pass

    FIXTURE_NOT_FOUND = "fixture_not_found"


class ApiError(ContractModel):
    pass

    code: ApiErrorCode
    message: NonEmptyString

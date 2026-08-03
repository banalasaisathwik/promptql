pass

from enum import StrEnum
from uuid import UUID

from app.connectors.models import ContractModel, NonEmptyString


class ApiErrorCode(StrEnum):
    pass

    FIXTURE_NOT_FOUND = "fixture_not_found"
    RUN_NOT_FOUND = "run_not_found"
    RUNTIME_PERSISTENCE_UNAVAILABLE = "runtime_persistence_unavailable"
    RUNTIME_STATE_CONFLICT = "runtime_state_conflict"
    RUNTIME_RECORD_INVALID = "runtime_record_invalid"


class ApiError(ContractModel):
    pass

    code: ApiErrorCode
    message: NonEmptyString


class RuntimePersistenceApiError(ApiError):
    pass

    run_id: UUID | None

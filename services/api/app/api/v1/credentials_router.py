from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints

from app.api.v1.auth_router import get_current_user
from app.api.v1.models import ApiError, ApiErrorCode
from app.auth import (
    AuthPersistenceError,
    CredentialProvider,
    CredentialRepository,
    User,
)
from app.connectors.models import ContractModel
from app.database import PostgresCredentialRepository

router = APIRouter(prefix="/v1/credentials", tags=["credentials"])
_MAX_TOKEN_LENGTH = 10_000


class StoreCredentialRequest(ContractModel):
    provider: CredentialProvider
    token: Annotated[
        str,
        StringConstraints(min_length=1, max_length=_MAX_TOKEN_LENGTH),
        Field(repr=False),
    ]


class CredentialSource(StrEnum):
    REAL = "real"
    DEMO = "demo"


class CredentialConnectionResponse(ContractModel):
    provider: CredentialProvider
    connected: bool
    source: CredentialSource = CredentialSource.REAL


class ConnectedProvidersResponse(ContractModel):
    providers: tuple[CredentialConnectionResponse, ...]


def get_credential_repository(request: Request) -> CredentialRepository:
    session_factory = getattr(request.app.state, "run_session_factory", None)
    if session_factory is None:
        raise AuthPersistenceError("Auth persistence is unavailable.")
    return PostgresCredentialRepository(session_factory)


def _connected_providers_response(
    connected_providers: tuple[CredentialProvider, ...],
) -> ConnectedProvidersResponse:
    connected_provider_set = set(connected_providers)
    return ConnectedProvidersResponse(
        providers=tuple(
            CredentialConnectionResponse(
                provider=provider,
                connected=provider in connected_provider_set,
                source=CredentialSource.REAL,
            )
            for provider in CredentialProvider
        )
    )


def _demo_connected_providers_response() -> ConnectedProvidersResponse:
    return ConnectedProvidersResponse(
        providers=tuple(
            CredentialConnectionResponse(
                provider=provider, connected=True, source=CredentialSource.DEMO
            )
            for provider in CredentialProvider
        )
    )


def _demo_credentials_immutable_response() -> JSONResponse:
    error = ApiError(
        code=ApiErrorCode.DEMO_ACCOUNT_CREDENTIALS_IMMUTABLE,
        message="Demo workspace credentials cannot be changed.",
    )
    return JSONResponse(status_code=403, content=error.model_dump(mode="json"))


@router.post(
    "",
    response_model=CredentialConnectionResponse,
    responses={403: {"model": ApiError}},
)
def store_credential(
    body: StoreCredentialRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> CredentialConnectionResponse | JSONResponse:
    if current_user.is_demo:
        return _demo_credentials_immutable_response()
    credential_repository.store_credential(current_user.id, body.provider, body.token)
    return CredentialConnectionResponse(provider=body.provider, connected=True)


@router.get("", response_model=ConnectedProvidersResponse)
def list_credentials(
    current_user: Annotated[User, Depends(get_current_user)],
    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> ConnectedProvidersResponse:
    if current_user.is_demo:
        return _demo_connected_providers_response()
    return _connected_providers_response(
        credential_repository.list_connected_providers(current_user.id)
    )


@router.delete(
    "/{provider}",
    status_code=204,
    responses={403: {"model": ApiError}},
)
def delete_credential(
    provider: CredentialProvider,
    current_user: Annotated[User, Depends(get_current_user)],
    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> Response:
    if current_user.is_demo:
        return _demo_credentials_immutable_response()
    credential_repository.delete_credential(current_user.id, provider)
    return Response(status_code=204)

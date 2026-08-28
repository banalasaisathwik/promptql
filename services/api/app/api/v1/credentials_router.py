from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, StringConstraints

from app.api.v1.auth_router import get_current_user
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


class CredentialConnectionResponse(ContractModel):
    provider: CredentialProvider
    connected: bool


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
            )
            for provider in CredentialProvider
        )
    )


@router.post("", response_model=CredentialConnectionResponse)
def store_credential(
    body: StoreCredentialRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> CredentialConnectionResponse:
    credential_repository.store_credential(current_user.id, body.provider, body.token)
    return CredentialConnectionResponse(provider=body.provider, connected=True)


@router.get("", response_model=ConnectedProvidersResponse)
def list_credentials(
    current_user: Annotated[User, Depends(get_current_user)],
    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> ConnectedProvidersResponse:
    return _connected_providers_response(
        credential_repository.list_connected_providers(current_user.id)
    )


@router.delete("/{provider}", status_code=204)
def delete_credential(
    provider: CredentialProvider,
    current_user: Annotated[User, Depends(get_current_user)],
    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> Response:
    credential_repository.delete_credential(current_user.id, provider)
    return Response(status_code=204)

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.v1.auth_router import get_current_user_optional
from app.api.v1.connector_router import get_runtime_telemetry
from app.api.v1.credentials_router import get_credential_repository
from app.api.v1.request_lifecycle import request_scoped_http_client
from app.auth import CredentialProvider, CredentialRepository, User
from app.config import GitHubSettings, SentrySettings
from app.connectors.errors import (
    ConnectorErrorCategory,
    GitHubConnectorError,
    SentryConnectorError,
)
from app.connectors.factory import create_github_http_client, create_sentry_http_client
from app.connectors.github_http import HttpGitHubConnector
from app.connectors.models import ContractModel, NonEmptyString
from app.connectors.sentry_http import HttpSentrySource


router = APIRouter(prefix="/v1", tags=["source-discovery"])


MAX_DISCOVERY_PAGES = 3


class GitHubRepositoryContext(ContractModel):
    owner: NonEmptyString
    name: NonEmptyString
    full_name: NonEmptyString
    private: bool
    default_branch: NonEmptyString | None = None


class GitHubContextResponse(ContractModel):
    login: NonEmptyString
    repositories: tuple[GitHubRepositoryContext, ...]


class SentryProjectContext(ContractModel):
    organization_slug: NonEmptyString
    project_slug: NonEmptyString
    name: NonEmptyString


def _require_credential(
    current_user: User | None,
    repository: CredentialRepository,
    provider: CredentialProvider,
) -> str:
    if current_user is None or current_user.is_demo:
        raise HTTPException(
            status_code=409, detail=f"Connect your {provider.value.title()} account first."
        )
    token = repository.get_decrypted_credential(current_user.id, provider)
    if token is None:
        raise HTTPException(
            status_code=409, detail=f"Connect your {provider.value.title()} account first."
        )
    return token


def _provider_failure(error: GitHubConnectorError | SentryConnectorError) -> JSONResponse:
    invalid_credential = error.category in {
        ConnectorErrorCategory.UNAUTHORIZED,
        ConnectorErrorCategory.FORBIDDEN,
    }
    return JSONResponse(
        status_code=401 if invalid_credential else 503,
        content={
            "code": "credential_invalid" if invalid_credential else "provider_unavailable",
            "message": (
                "The connected provider credential is invalid. Reconnect it and try again."
                if invalid_credential
                else "The connected provider is unavailable. Try again shortly."
            ),
        },
    )


@router.get(
    "/github/context",
    response_model=GitHubContextResponse,
    responses={401: {}, 409: {}, 503: {}},
)
async def get_github_context(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> GitHubContextResponse | JSONResponse:
    token = _require_credential(
        current_user, credential_repository, CredentialProvider.GITHUB
    )
    settings = GitHubSettings.from_stored_credential(token)
    async for client in request_scoped_http_client(
        lambda: create_github_http_client(settings)
    ):
        try:
            login, repositories = await HttpGitHubConnector(
                client, get_runtime_telemetry(request), max_pages=MAX_DISCOVERY_PAGES
            ).get_authenticated_context()
        except GitHubConnectorError as error:
            return _provider_failure(error)
    return GitHubContextResponse(
        login=login,
        repositories=tuple(
            GitHubRepositoryContext(
                owner=repository.owner.login,
                name=repository.name,
                full_name=repository.full_name,
                private=repository.private,
                default_branch=repository.default_branch,
            )
            for repository in repositories
        ),
    )


@router.get(
    "/sentry/projects",
    response_model=tuple[SentryProjectContext, ...],
    responses={401: {}, 409: {}, 503: {}},
)
async def get_sentry_projects(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> tuple[SentryProjectContext, ...] | JSONResponse:
    token = _require_credential(
        current_user, credential_repository, CredentialProvider.SENTRY
    )
    organization_slug = os.environ.get("SENTRY_ORGANIZATION_SLUG", "").strip()
    if not organization_slug:
        return JSONResponse(
            status_code=503,
            content={
                "code": "provider_unavailable",
                "message": "The connected provider is unavailable. Try again shortly.",
            },
        )
    settings = SentrySettings.from_stored_credential(
        token, organization_slug=organization_slug
    )
    async for client in request_scoped_http_client(
        lambda: create_sentry_http_client(settings)
    ):
        try:
            projects = await HttpSentrySource(
                client, settings.organization_slug, get_runtime_telemetry(request)
            ).list_accessible_projects()
        except SentryConnectorError as error:
            return _provider_failure(error)
    return tuple(
        SentryProjectContext(
            organization_slug=organization_slug,
            project_slug=project.slug,
            name=project.name,
        )
        for project in projects
    )

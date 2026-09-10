import os
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.v1.connector_router import get_github_code_evidence_source, get_runtime_telemetry
from app.api.v1.auth_router import get_current_user_optional
from app.api.v1.credentials_router import get_credential_repository
from app.api.v1.models import ApiError, ApiErrorCode
from app.api.v1.request_lifecycle import request_scoped_http_client
from app.auth import CredentialProvider, CredentialRepository, User
from app.config import SentrySettings
from app.connectors.errors import ConnectorErrorCategory, SentryConnectorError
from app.connectors.factory import create_sentry_http_client
from app.connectors.models import ContractModel, NonEmptyString
from app.connectors.protocols import GitHubCodeEvidenceSource
from app.connectors.sentry_http import HttpSentrySource
from app.observability import RuntimeTelemetry
from app.workflows.correlation_scan import RepositoryCorrelationScanResult, scan_repository_for_correlations


router = APIRouter(prefix="/v1", tags=["correlation-scans"])


class CorrelationScanRequest(ContractModel):
    repository_owner: NonEmptyString
    repository_name: NonEmptyString


    sentry_project_slug: NonEmptyString


_UPSTREAM_UNAVAILABLE_CATEGORIES = frozenset(
    {
        ConnectorErrorCategory.RATE_LIMITED,
        ConnectorErrorCategory.TIMEOUT,
        ConnectorErrorCategory.UPSTREAM_UNAVAILABLE,
        ConnectorErrorCategory.CONFIGURATION_ERROR,
    }
)


async def get_sentry_source_for_scan(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],


    credential_repository: Annotated[
        CredentialRepository, Depends(get_credential_repository)
    ],
) -> AsyncIterator[HttpSentrySource]:
    if current_user is None or current_user.is_demo:
        raise HTTPException(
            status_code=409,
            detail="Connect your Sentry account before running a correlation scan.",
        )

    token = credential_repository.get_decrypted_credential(
        current_user.id, CredentialProvider.SENTRY
    )
    if token is None:
        raise HTTPException(
            status_code=409,
            detail="Connect your Sentry account before running a correlation scan.",
        )

    settings = SentrySettings.from_stored_credential(
        token,
        organization_slug=os.environ.get("SENTRY_ORGANIZATION_SLUG", ""),
    )
    telemetry: RuntimeTelemetry = get_runtime_telemetry(request)
    async for http_client in request_scoped_http_client(
        lambda: create_sentry_http_client(settings)
    ):
        yield HttpSentrySource(http_client, settings.organization_slug, telemetry)


@router.post(
    "/correlation-scans",
    response_model=RepositoryCorrelationScanResult,
    responses={409: {"model": ApiError}, 502: {"model": ApiError}, 503: {"model": ApiError}},
)
async def start_correlation_scan(
    scan_request: CorrelationScanRequest,
    sentry_source: Annotated[HttpSentrySource, Depends(get_sentry_source_for_scan)],
    github_source: Annotated[
        GitHubCodeEvidenceSource, Depends(get_github_code_evidence_source)
    ],
) -> RepositoryCorrelationScanResult | JSONResponse:
    try:
        return await scan_repository_for_correlations(
            repository_owner=scan_request.repository_owner,
            repository_name=scan_request.repository_name,
            sentry_project_slug=scan_request.sentry_project_slug,
            sentry_source=sentry_source,
            github_source=github_source,
        )
    except SentryConnectorError as error:
        status_code = 503 if error.category in _UPSTREAM_UNAVAILABLE_CATEGORIES else 502
        return JSONResponse(
            status_code=status_code,
            content=ApiError(
                code=ApiErrorCode.CORRELATION_SCAN_UPSTREAM_FAILED,
                message="Could not list open Sentry issues for the requested project.",
            ).model_dump(mode="json"),
        )

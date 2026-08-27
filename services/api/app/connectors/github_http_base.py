from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from app.connectors.errors import (
    GitHubForbiddenError,
    GitHubIncompleteResultError,
    GitHubInvalidResponseError,
    GitHubNotFoundError,
    GitHubRateLimitedError,
    GitHubTimeoutError,
    GitHubUnauthorizedError,
    GitHubUpstreamUnavailableError,
)
from app.observability import NoOpRuntimeTelemetry, RuntimeTelemetry


PAGE_SIZE = 100
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


@dataclass
class GitHubRequestObservation:
    page_count: int = 0
    status_class: str = "none"


class BaseHttpGitHubConnector:
    def __init__(
        self,
        client: httpx.AsyncClient,
        telemetry: RuntimeTelemetry | None,
        max_pages: int,
    ) -> None:
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self._client = client
        self._telemetry = telemetry or NoOpRuntimeTelemetry()
        self._max_pages = max_pages

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _repository_path(repository_owner: str, repository_name: str) -> str:
        owner = quote(repository_owner, safe="")
        repository = quote(repository_name, safe="")
        return f"/repos/{owner}/{repository}"

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        rate_limited = (
            status in {403, 429}
            and (
                response.headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in response.headers
                or status == 429
            )
        )
        if rate_limited:
            raise GitHubRateLimitedError()
        if status == 401:
            raise GitHubUnauthorizedError()
        if status == 403:
            raise GitHubForbiddenError()
        if status == 404:
            raise GitHubNotFoundError()
        if 500 <= status <= 599:
            raise GitHubUpstreamUnavailableError()
        if not 200 <= status <= 299:
            raise GitHubInvalidResponseError()

    async def _request_json(
        self,
        path: str,
        observation: GitHubRequestObservation,
        params: dict[str, int | str] | None = None,
    ) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException:
            raise GitHubTimeoutError() from None
        except httpx.RequestError:
            raise GitHubUpstreamUnavailableError() from None

        observation.status_class = f"{response.status_code // 100}xx"
        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError:
            raise GitHubInvalidResponseError() from None

    async def _get_model(
        self,
        path: str,
        model_type: type[ResponseModel],
        observation: GitHubRequestObservation,
        params: dict[str, int | str] | None = None,
    ) -> ResponseModel:
        payload = await self._request_json(path, observation, params)
        try:
            return model_type.model_validate(payload)
        except ValidationError:
            raise GitHubInvalidResponseError() from None

    async def _get_paginated_list(
        self,
        path: str,
        model_type: type[ResponseModel],
        observation: GitHubRequestObservation,
    ) -> tuple[ResponseModel, ...]:
        results: list[ResponseModel] = []
        for page in range(1, self._max_pages + 1):
            observation.page_count += 1
            payload = await self._request_json(
                path,
                observation,
                {"per_page": PAGE_SIZE, "page": page},
            )
            if not isinstance(payload, list):
                raise GitHubInvalidResponseError()
            try:
                page_results = [model_type.model_validate(value) for value in payload]
            except ValidationError:
                raise GitHubInvalidResponseError() from None
            results.extend(page_results)
            if len(page_results) < PAGE_SIZE:
                return tuple(results)


        raise GitHubIncompleteResultError()

    async def _get_paginated_object_list(
        self,
        path: str,
        page_model: type[BaseModel],
        list_field: str,
        observation: GitHubRequestObservation,
    ) -> tuple[Any, ...]:
        results: list[Any] = []
        total_count: int | None = None
        for page in range(1, self._max_pages + 1):
            observation.page_count += 1
            response_page = await self._get_model(
                path,
                page_model,
                observation,
                {"per_page": PAGE_SIZE, "page": page},
            )
            page_results = getattr(response_page, list_field)
            total_count = response_page.total_count
            results.extend(page_results)
            if len(results) >= total_count or len(page_results) < PAGE_SIZE:
                return tuple(results)
        raise GitHubIncompleteResultError()

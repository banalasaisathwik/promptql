import asyncio
import unittest
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.auth_router import get_current_user_optional
from app.api.v1 import auth_router as auth_router_module
from app.api.v1 import connector_router as connector_router_module
from app.api.v1.connector_router import (
    get_fact_recurrence_repository,
    get_github_connector,
    get_investigation_workflow,
    get_incident_source,
    get_jira_connector,
    get_live_run_task_registry,
    get_run_repository,
)
from app.api.v1.request_lifecycle import request_scoped_http_client
from app.auth import CredentialProvider, InMemoryCredentialRepository, User
from app.auth import InMemoryUserRepository, SessionSigner
from app.explanations import FakeLLMClient
from app.investigations.models import InvestigationRequest
from app.main import app
from app.runtime import InMemoryFactRecurrenceRepository, InMemoryRunRepository
from app.workflows import InvestigationWorkflowService


class RequestScopedHttpClientTests(unittest.TestCase):
    def test_client_is_closed_when_dependency_consumer_raises(self) -> None:
        client = httpx.AsyncClient()

        async def consume_and_fail() -> None:
            async for _ in request_scoped_http_client(lambda: client):
                raise RuntimeError("request failed")

        with self.assertRaisesRegex(RuntimeError, "request failed"):
            asyncio.run(consume_and_fail())

        self.assertTrue(client.is_closed)

    def test_client_is_closed_after_a_fastapi_request_completes(self) -> None:
        application = FastAPI()
        clients: list[httpx.AsyncClient] = []

        async def client_dependency() -> AsyncIterator[httpx.AsyncClient]:
            async for client in request_scoped_http_client(httpx.AsyncClient):
                clients.append(client)
                yield client

        @application.get("/")
        async def endpoint(
            client: httpx.AsyncClient = Depends(client_dependency),
        ) -> dict[str, bool]:
            self.assertFalse(client.is_closed)
            return {"ok": True}

        with TestClient(application) as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(clients), 1)
        self.assertTrue(clients[0].is_closed)

    def test_optional_current_user_returns_none_without_a_cookie(self) -> None:
        request = SimpleNamespace(cookies={})

        self.assertIsNone(get_current_user_optional(request))


class GitHubConnectorDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            "os.environ",
            {"PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode()},
        )
        self.environment.start()
        self.first_user = User(
            id=uuid4(),
            email="first@example.com",
            created_at=datetime.now(timezone.utc),
        )
        self.second_user = User(
            id=uuid4(),
            email="second@example.com",
            created_at=datetime.now(timezone.utc),
        )
        self.credentials = InMemoryCredentialRepository()
        self.credentials.store_credential(
            self.first_user.id, CredentialProvider.GITHUB, "first-user-token"
        )
        self.credentials.store_credential(
            self.second_user.id, CredentialProvider.GITHUB, "second-user-token"
        )

    def tearDown(self) -> None:
        self.environment.stop()

    def test_authenticated_users_receive_distinct_token_scoped_clients(self) -> None:
        clients: list[httpx.AsyncClient] = []
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

        async def resolve_client(user: User) -> httpx.AsyncClient:
            dependency = get_github_connector(request, user)
            connector = await anext(dependency)
            client = connector._client
            clients.append(client)
            await dependency.aclose()
            return client

        with patch(
            "app.api.v1.connector_router.get_credential_repository",
            return_value=self.credentials,
        ):
            first_client, second_client = asyncio.run(
                _resolve_two(resolve_client, self.first_user, self.second_user)
            )

        self.assertEqual(first_client.headers["Authorization"], "Bearer first-user-token")
        self.assertEqual(second_client.headers["Authorization"], "Bearer second-user-token")
        self.assertIsNot(first_client, second_client)
        self.assertTrue(all(client.is_closed for client in clients))

    def test_authenticated_user_without_github_credential_is_rejected(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        user = User(
            id=uuid4(),
            email="missing@example.com",
            created_at=datetime.now(timezone.utc),
        )

        async def resolve() -> None:
            dependency = get_github_connector(request, user)
            await anext(dependency)

        with patch(
            "app.api.v1.connector_router.get_credential_repository",
            return_value=self.credentials,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(resolve())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail,
            "Connect your GitHub account before starting an investigation that needs it.",
        )

    def test_authenticated_user_without_jira_credential_is_rejected(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

        async def resolve() -> None:
            dependency = get_jira_connector(request, self.first_user)
            await anext(dependency)

        with patch(
            "app.api.v1.connector_router.get_credential_repository",
            return_value=InMemoryCredentialRepository(),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(resolve())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail,
            "Connect your Jira account before starting an investigation that needs it.",
        )

    def test_authenticated_user_without_sentry_credential_is_rejected(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

        async def resolve() -> None:
            dependency = get_incident_source(request, self.first_user)
            await anext(dependency)

        with patch(
            "app.api.v1.connector_router.get_credential_repository",
            return_value=InMemoryCredentialRepository(),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(resolve())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail,
            "Connect your Sentry account before starting an investigation that needs it.",
        )

    def test_anonymous_request_yields_the_existing_app_state_connector(self) -> None:
        anonymous_connector = object()
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(github_connector=anonymous_connector)
            )
        )

        async def resolve() -> object:
            dependency = get_github_connector(request, None)
            connector = await anext(dependency)
            await dependency.aclose()
            return connector

        self.assertIs(asyncio.run(resolve()), anonymous_connector)


class _HoldingLiveRunTaskRegistry:
    def start(self, coroutine: object) -> None:
        coroutine.close()


class InvestigationWorkflowDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            "os.environ",
            {
                "PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "JIRA_BASE_URL": "https://promptql.atlassian.net",
                "JIRA_EMAIL": "tester@example.com",
                "SENTRY_ORGANIZATION_SLUG": "promptql",
            },
            clear=False,
        )
        self.environment.start()
        self.user_repository = InMemoryUserRepository()
        self.current_user = self.user_repository.create_user(
            "workflow@example.com", "correct horse battery staple"
        )
        self.session_signer = SessionSigner("test-only-session-secret", 3600)
        self.credentials = InMemoryCredentialRepository()
        self.credentials.store_credential(
            self.current_user.id, CredentialProvider.GITHUB, "user-github-token"
        )
        self.credentials.store_credential(
            self.current_user.id, CredentialProvider.JIRA, "user-jira-token"
        )
        self.credentials.store_credential(
            self.current_user.id, CredentialProvider.SENTRY, "user-sentry-token"
        )
        self.repository = InMemoryRunRepository()
        self.recurrence_repository = InMemoryFactRecurrenceRepository()
        self.task_registry = _HoldingLiveRunTaskRegistry()
        self.captured_workflows: list[InvestigationWorkflowService] = []

        def capture_workflow(*args: object, **kwargs: object) -> InvestigationWorkflowService:
            workflow = InvestigationWorkflowService(*args, **kwargs)
            self.captured_workflows.append(workflow)
            return workflow

        self.workflow_patch = patch(
            "app.api.v1.connector_router.InvestigationWorkflowService",
            side_effect=capture_workflow,
        )
        self.workflow_patch.start()
        self.auth_user_repository_patch = patch.object(
            auth_router_module,
            "get_user_repository",
            return_value=self.user_repository,
        )
        self.auth_session_signer_patch = patch.object(
            auth_router_module,
            "get_session_signer",
            return_value=self.session_signer,
        )
        self.credential_repository_patch = patch.object(
            connector_router_module,
            "get_credential_repository",
            return_value=self.credentials,
        )
        self.auth_user_repository_patch.start()
        self.auth_session_signer_patch.start()
        self.credential_repository_patch.start()
        app.dependency_overrides[get_run_repository] = lambda: self.repository
        app.dependency_overrides[get_fact_recurrence_repository] = (
            lambda: self.recurrence_repository
        )
        app.dependency_overrides[get_live_run_task_registry] = lambda: self.task_registry

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.credential_repository_patch.stop()
        self.auth_session_signer_patch.stop()
        self.auth_user_repository_patch.stop()
        self.workflow_patch.stop()
        self.environment.stop()

    def test_authenticated_investigation_uses_the_stored_github_credential(self) -> None:
        request = InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout failures increase?",
            incident_reference="incident:checkout-500",
        )
        session_cookie = self.session_signer.sign(self.current_user.id)

        client = TestClient(app)
        try:
            response = client.post(
                "/v1/investigations",
                headers={"cookie": f"promptql_session={session_cookie}"},
                json=request.model_dump(mode="json"),
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(self.captured_workflows), 1)
        workflow = self.captured_workflows[0]
        self.assertEqual(
            workflow._github_code_source._client.headers["Authorization"],
            "Bearer user-github-token",
        )
        self.assertEqual(
            workflow._incident_source._client.headers["Authorization"],
            "Bearer user-sentry-token",
        )
        self.assertIsNot(
            workflow._github_code_source, app.state.github_code_source
        )
        self.assertIsNot(workflow._incident_source, app.state.incident_source)
        self.assertIsNot(workflow._jira_connector, app.state.jira_connector)


async def _resolve_two(
    resolve_client: Callable[[User], Awaitable[httpx.AsyncClient]],
    first_user: User,
    second_user: User,
) -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
    first_client = await resolve_client(first_user)
    second_client = await resolve_client(second_user)
    return first_client, second_client


if __name__ == "__main__":
    unittest.main()

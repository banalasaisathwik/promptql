import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.v1.connector_router import (
    get_github_code_evidence_source,
    get_github_connector,
    get_incident_source,
    get_jira_connector,
)
from app.auth import InMemoryCredentialRepository, User


def _fail_if_called(*_args: object, **_kwargs: object) -> None:
    raise AssertionError(
        "get_credential_repository must not be called when current_user.is_demo is True"
    )


def _demo_user() -> User:
    return User(
        id=uuid4(),
        email="demo@example.com",
        created_at=datetime.now(timezone.utc),
        is_demo=True,
    )


def _non_demo_user() -> User:
    return User(
        id=uuid4(),
        email="real-user@example.com",
        created_at=datetime.now(timezone.utc),
    )


def _request_with_state(**state: object) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)))


class DemoAccountConnectorBypassTests(unittest.TestCase):
    def test_github_connector_bypasses_credential_lookup_for_demo_user(self) -> None:
        anonymous_connector = object()
        request = _request_with_state(github_connector=anonymous_connector)

        async def resolve() -> object:
            dependency = get_github_connector(request, _demo_user())
            connector = await anext(dependency)
            await dependency.aclose()
            return connector

        with patch(
            "app.api.v1.connector_router.get_credential_repository",
            side_effect=_fail_if_called,
        ):
            self.assertIs(asyncio.run(resolve()), anonymous_connector)

    def test_github_code_evidence_source_bypasses_credential_lookup_for_demo_user(
        self,
    ) -> None:
        anonymous_source = object()
        request = _request_with_state(github_code_source=anonymous_source)

        async def resolve() -> object:
            dependency = get_github_code_evidence_source(request, _demo_user())
            source = await anext(dependency)
            await dependency.aclose()
            return source

        with patch(
            "app.api.v1.connector_router.get_credential_repository",
            side_effect=_fail_if_called,
        ):
            self.assertIs(asyncio.run(resolve()), anonymous_source)

    def test_jira_connector_bypasses_credential_lookup_for_demo_user(self) -> None:
        anonymous_connector = object()
        request = _request_with_state(jira_connector=anonymous_connector)

        async def resolve() -> object:
            dependency = get_jira_connector(request, _demo_user())
            connector = await anext(dependency)
            await dependency.aclose()
            return connector

        with patch(
            "app.api.v1.connector_router.get_credential_repository",
            side_effect=_fail_if_called,
        ):
            self.assertIs(asyncio.run(resolve()), anonymous_connector)

    def test_incident_source_bypasses_credential_lookup_for_demo_user(self) -> None:
        anonymous_source = object()
        request = _request_with_state(incident_source=anonymous_source)

        async def resolve() -> object:
            dependency = get_incident_source(request, _demo_user())
            source = await anext(dependency)
            await dependency.aclose()
            return source

        with patch(
            "app.api.v1.connector_router.get_credential_repository",
            side_effect=_fail_if_called,
        ):
            self.assertIs(asyncio.run(resolve()), anonymous_source)


class NonDemoUserRegressionTests(unittest.TestCase):
    def test_non_demo_user_without_credential_still_rejected_after_demo_bypass_added(
        self,
    ) -> None:
        request = _request_with_state()
        user = _non_demo_user()

        async def resolve() -> None:
            dependency = get_github_connector(request, user)
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
            "Connect your GitHub account before starting an investigation that needs it.",
        )

    def test_non_demo_user_without_jira_credential_still_rejected_after_demo_bypass_added(
        self,
    ) -> None:
        request = _request_with_state()
        user = _non_demo_user()

        async def resolve() -> None:
            dependency = get_jira_connector(request, user)
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

    def test_non_demo_user_without_sentry_credential_still_rejected_after_demo_bypass_added(
        self,
    ) -> None:
        request = _request_with_state()
        user = _non_demo_user()

        async def resolve() -> None:
            dependency = get_incident_source(request, user)
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


if __name__ == "__main__":
    unittest.main()

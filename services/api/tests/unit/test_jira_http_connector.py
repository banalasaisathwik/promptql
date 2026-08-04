pass

import base64
import unittest

import httpx

from app.connectors.errors import (
    JiraForbiddenError,
    JiraInvalidIssueKeyError,
    JiraInvalidResponseError,
    JiraIssueUnavailableError,
    JiraRateLimitedError,
    JiraTimeoutError,
    JiraUnauthorizedError,
    JiraUpstreamUnavailableError,
)
from app.connectors.jira_http import HttpJiraConnector, JIRA_REQUIRED_FIELDS
from app.connectors.fakes import FakeGitHubConnector
from app.connectors.fixture_catalog import MERGE_READY_REQUEST
from app.connectors.models import BlockerState, JiraIssueStatus
from tests.telemetry_support import create_telemetry_harness
from app.policy import PolicyReasonCode, evaluate_merge_readiness
from app.runtime import InMemoryRunRepository, RunStatus, RuntimeErrorCode
from app.workflows import MergeReadinessWorkflowService


JIRA_BASE_URL = "https://example.atlassian.net"
TEST_EMAIL = "connector-user@example.invalid"
TEST_TOKEN = "local-test-api-token"


def jira_issue_payload(
    *,
    category: str = "done",
    status_name: str = "Released",
    resolved: bool = True,
    assignee: bool = True,
) -> dict:
    pass

    return {
        "id": "10001",
        "key": "ENG-101",
        "fields": {
            "status": {
                "id": "10003",
                "name": status_name,
                "statusCategory": {
                    "id": 3,
                    "key": category,
                    "name": "Complete" if category == "done" else "In Progress",
                },
            },
            "assignee": (
                {
                    "accountId": "account-123",
                    "displayName": "Example Engineer",
                }
                if assignee
                else None
            ),
            "resolution": (
                {"id": "1", "name": "Fixed"} if resolved else None
            ),
        },
    }


def create_connector(handler, telemetry=None):
    client = httpx.AsyncClient(
        base_url=JIRA_BASE_URL,
        headers={"Accept": "application/json"},
        auth=httpx.BasicAuth(TEST_EMAIL, TEST_TOKEN),
        transport=httpx.MockTransport(handler),
    )
    return HttpJiraConnector(client, telemetry), client


class HttpJiraConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_issue_normalization_and_request_shape(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=jira_issue_payload())

        connector, client = create_connector(handler)
        try:
            issue = await connector.get_issue("ENG-101")
        finally:
            await client.aclose()

        self.assertEqual(issue.issue_key, "ENG-101")
        self.assertEqual(issue.status, JiraIssueStatus.DONE)
        self.assertEqual(issue.status_name, "Released")
        self.assertEqual(issue.status_id, "10003")
        self.assertTrue(issue.is_resolved)
        self.assertEqual(issue.blocker_state, BlockerState.UNKNOWN)
        self.assertEqual(issue.assignee.account_id, "account-123")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/rest/api/3/issue/ENG-101")
        self.assertEqual(requests[0].url.params["fields"], JIRA_REQUIRED_FIELDS)
        basic_value = requests[0].headers["authorization"].removeprefix("Basic ")
        self.assertEqual(
            base64.b64decode(basic_value).decode(),
            f"{TEST_EMAIL}:{TEST_TOKEN}",
        )

    async def test_status_categories_normalize_independently_of_custom_names(self) -> None:
        cases = (
            ("new", "Backlog", JiraIssueStatus.TO_DO),
            ("indeterminate", "Ready for QA", JiraIssueStatus.IN_PROGRESS),
            ("done", "Deployed to Production", JiraIssueStatus.DONE),
        )
        for category, custom_name, expected in cases:
            with self.subTest(category=category):
                connector, client = create_connector(
                    lambda _request, category=category, custom_name=custom_name: (
                        httpx.Response(
                            200,
                            json=jira_issue_payload(
                                category=category,
                                status_name=custom_name,
                            ),
                        )
                    )
                )
                try:
                    issue = await connector.get_issue("ENG-101")
                finally:
                    await client.aclose()
                self.assertEqual(issue.status, expected)
                self.assertEqual(issue.status_name, custom_name)

    async def test_normalized_category_not_custom_name_drives_policy(self) -> None:
        github = await FakeGitHubConnector().get_pull_request(MERGE_READY_REQUEST)
        cases = (
            ("indeterminate", "Done", True),
            ("done", "Still Testing", False),
        )
        for category, misleading_name, expects_incomplete_blocker in cases:
            with self.subTest(category=category):
                connector, client = create_connector(
                    lambda _request, category=category, misleading_name=misleading_name: (
                        httpx.Response(
                            200,
                            json=jira_issue_payload(
                                category=category,
                                status_name=misleading_name,
                            ),
                        )
                    )
                )
                try:
                    jira = await connector.get_issue("ENG-101")
                finally:
                    await client.aclose()
                result = evaluate_merge_readiness(github, jira)
                reason_codes = {blocker.reason_code for blocker in result.blockers}
                self.assertEqual(
                    PolicyReasonCode.JIRA_NOT_COMPLETE in reason_codes,
                    expects_incomplete_blocker,
                )

    async def test_resolution_and_unassigned_issue_are_normalized(self) -> None:
        connector, client = create_connector(
            lambda _request: httpx.Response(
                200,
                json=jira_issue_payload(resolved=False, assignee=False),
            )
        )
        try:
            issue = await connector.get_issue("ENG-101")
        finally:
            await client.aclose()

        self.assertFalse(issue.is_resolved)
        self.assertIsNone(issue.assignee)

    async def test_malformed_issue_key_is_rejected_before_http(self) -> None:
        request_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json=jira_issue_payload())

        connector, client = create_connector(handler)
        try:
            for invalid_key in ("eng-101", "ENG-0", "https://jira/ENG-1", "../ENG-1"):
                with self.subTest(issue_key=invalid_key):
                    with self.assertRaises(JiraInvalidIssueKeyError):
                        await connector.get_issue(invalid_key)
        finally:
            await client.aclose()

        self.assertEqual(request_count, 0)

    async def test_http_error_taxonomy_is_sanitized(self) -> None:
        cases = (
            (401, {}, JiraUnauthorizedError),
            (403, {}, JiraForbiddenError),
            (404, {}, JiraIssueUnavailableError),
            (429, {"Retry-After": "12"}, JiraRateLimitedError),
            (503, {}, JiraUpstreamUnavailableError),
        )
        for status, headers, expected_error in cases:
            with self.subTest(status=status):
                connector, client = create_connector(
                    lambda _request, status=status, headers=headers: httpx.Response(
                        status,
                        headers=headers,
                        text="provider body must remain private",
                    )
                )
                try:
                    with self.assertRaises(expected_error) as raised:
                        await connector.get_issue("ENG-101")
                finally:
                    await client.aclose()
                self.assertNotIn("provider body", str(raised.exception))
                if isinstance(raised.exception, JiraRateLimitedError):
                    self.assertEqual(raised.exception.retry_after_seconds, 12)

    async def test_timeout_and_network_failure_are_distinct(self) -> None:
        failures = (
            (
                lambda request: (_ for _ in ()).throw(
                    httpx.ReadTimeout("private timeout", request=request)
                ),
                JiraTimeoutError,
            ),
            (
                lambda request: (_ for _ in ()).throw(
                    httpx.ConnectError("private network", request=request)
                ),
                JiraUpstreamUnavailableError,
            ),
        )
        for handler, expected_error in failures:
            with self.subTest(error=expected_error.__name__):
                connector, client = create_connector(handler)
                try:
                    with self.assertRaises(expected_error) as raised:
                        await connector.get_issue("ENG-101")
                finally:
                    await client.aclose()
                self.assertNotIn("private", str(raised.exception))

    async def test_malformed_json_and_response_shapes_are_invalid(self) -> None:
        payloads = (
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"id": "10001", "fields": {}}),
            httpx.Response(
                200,
                json={
                    **jira_issue_payload(),
                    "fields": {
                        "assignee": None,
                        "resolution": None,
                    },
                },
            ),
            httpx.Response(
                200,
                json={
                    **jira_issue_payload(),
                    "fields": {
                        **jira_issue_payload()["fields"],
                        "status": {
                            "id": "3",
                            "name": "Testing",
                        },
                    },
                },
            ),
        )
        for response in payloads:
            with self.subTest(payload=response.content[:20]):
                connector, client = create_connector(lambda _request: response)
                try:
                    with self.assertRaises(JiraInvalidResponseError):
                        await connector.get_issue("ENG-101")
                finally:
                    await client.aclose()

    async def test_secrets_and_external_values_are_absent_from_telemetry(self) -> None:
        harness = create_telemetry_harness()

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                text=(
                    f"email={TEST_EMAIL} token={TEST_TOKEN} "
                    "issue=ENG-101 host=example.atlassian.net"
                ),
            )

        connector, client = create_connector(handler, harness.telemetry)
        try:
            with self.assertRaises(JiraUnauthorizedError) as raised:
                await connector.get_issue("ENG-101")
            spans = harness.span_exporter.get_finished_spans()
            serialized = repr(
                tuple((span.name, dict(span.attributes), span.events) for span in spans)
            )
            combined = serialized + str(raised.exception) + harness.log_stream.getvalue()
            for secret_or_input in (
                TEST_EMAIL,
                TEST_TOKEN,
                "Basic ",
                "ENG-101",
                "example.atlassian.net",
            ):
                self.assertNotIn(secret_or_input, combined)
            connector_span = next(
                span for span in spans if span.name == "connector.jira.get_issue"
            )
            self.assertEqual(
                connector_span.attributes["promptql.connector.result"],
                "unauthorized",
            )
            self.assertEqual(
                connector_span.attributes["promptql.connector.source"],
                "live",
            )
        finally:
            await client.aclose()
            harness.shutdown()

    async def test_live_jira_failure_uses_sanitized_runtime_failure(self) -> None:
        connector, client = create_connector(
            lambda _request: httpx.Response(
                401,
                text=f"email={TEST_EMAIL} token={TEST_TOKEN}",
            )
        )
        workflow = MergeReadinessWorkflowService(
            FakeGitHubConnector(),
            connector,
            InMemoryRunRepository(),
        )
        try:
            run = await workflow.execute(MERGE_READY_REQUEST)
        finally:
            await client.aclose()

        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(len(run.steps), 2)
        self.assertEqual(
            run.error.code,
            RuntimeErrorCode.CONNECTOR_EXECUTION_FAILED,
        )
        serialized = run.model_dump_json()
        self.assertNotIn(TEST_EMAIL, serialized)
        self.assertNotIn(TEST_TOKEN, serialized)


if __name__ == "__main__":
    unittest.main()

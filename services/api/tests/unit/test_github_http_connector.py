pass

from copy import deepcopy
import unittest

import httpx

from app.connectors.errors import (
    GitHubForbiddenError,
    GitHubInvalidResponseError,
    GitHubNotFoundError,
    GitHubRateLimitedError,
    GitHubTimeoutError,
    GitHubUnauthorizedError,
    GitHubUpstreamUnavailableError,
)
from app.connectors.github_http import HttpGitHubConnector
from app.connectors.models import CheckStatus, ConnectorRequest, Mergeability
from tests.telemetry_support import create_telemetry_harness


REQUEST = ConnectorRequest(
    repository_owner="octo-org",
    repository_name="analytics",
    pr_number=42,
)
SHA = "a" * 40


def pull_response(**updates):
    response = {
        "number": 42,
        "title": "ENG-42 Add live connector",
        "body": "Implements the connector.",
        "html_url": "https://github.com/octo-org/analytics/pull/42",
        "state": "open",
        "draft": False,
        "merged": False,
        "mergeable": True,
        "user": {"login": "author"},
        "assignees": [{"login": "assignee"}],
        "requested_reviewers": [{"login": "reviewer"}],
        "head": {"ref": "feature/ENG-42", "sha": SHA},
        "base": {"ref": "main", "sha": "b" * 40},
    }
    response.update(updates)
    return response


def protection_response():
    return {
        "required_status_checks": None,
        "required_pull_request_reviews": None,
    }


class GitHubResponses:
    pass

    def __init__(self) -> None:
        self.pull = pull_response()
        self.reviews: list[dict] = []
        self.rules: list[dict] = []
        self.protection = protection_response()
        self.check_runs: list[dict] = []
        self.statuses: list[dict] = []
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/pulls/42"):
            return httpx.Response(200, json=self.pull)
        if path.endswith("/pulls/42/reviews"):
            return httpx.Response(200, json=self._page(self.reviews, request))
        if "/rules/branches/" in path:
            return httpx.Response(200, json=self._page(self.rules, request))
        if path.endswith("/branches/main/protection"):
            return httpx.Response(200, json=self.protection)
        if path.endswith(f"/commits/{SHA}/check-runs"):
            page = self._page(self.check_runs, request)
            return httpx.Response(
                200,
                json={"total_count": len(self.check_runs), "check_runs": page},
            )
        if path.endswith(f"/commits/{SHA}/status"):
            page = self._page(self.statuses, request)
            return httpx.Response(
                200,
                json={"total_count": len(self.statuses), "statuses": page},
            )
        return httpx.Response(404, json={"message": "not found"})

    @staticmethod
    def _page(values: list[dict], request: httpx.Request) -> list[dict]:
        page = int(request.url.params.get("page", "1"))
        per_page = int(request.url.params.get("per_page", "100"))
        start = (page - 1) * per_page
        return values[start : start + per_page]


async def load_facts(
    responses: GitHubResponses,
    telemetry=None,
    max_pages: int = 10,
):
    client = httpx.AsyncClient(
        base_url="https://api.github.test",
        transport=httpx.MockTransport(responses),
        headers={"Authorization": "Bearer test-secret"},
    )
    connector = HttpGitHubConnector(client, telemetry, max_pages=max_pages)
    try:
        return await connector.get_pull_request(REQUEST)
    finally:
        await connector.aclose()


class HttpGitHubConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_pull_request_normalization(self) -> None:
        facts = await load_facts(GitHubResponses())

        self.assertEqual(facts.pr_number, 42)
        self.assertEqual(facts.title, "ENG-42 Add live connector")
        self.assertEqual(facts.head_branch, "feature/ENG-42")
        self.assertEqual(facts.base_branch, "main")
        self.assertEqual(facts.author.login, "author")
        self.assertEqual(facts.linked_jira_key, "ENG-42")
        self.assertTrue(facts.required_checks_known)
        self.assertEqual(facts.required_approval_count, 0)

    async def test_draft_pull_request(self) -> None:
        responses = GitHubResponses()
        responses.pull["draft"] = True

        facts = await load_facts(responses)

        self.assertTrue(facts.is_draft)

    async def test_merge_conflict(self) -> None:
        responses = GitHubResponses()
        responses.pull["mergeable"] = False

        facts = await load_facts(responses)

        self.assertEqual(facts.mergeability, Mergeability.CONFLICTING)

    async def test_null_mergeability_is_unknown(self) -> None:
        responses = GitHubResponses()
        responses.pull["mergeable"] = None

        facts = await load_facts(responses)

        self.assertEqual(facts.mergeability, Mergeability.UNKNOWN)

    async def test_latest_approved_review_is_normalized(self) -> None:
        responses = GitHubResponses()
        responses.reviews = [
            {"user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED"},
            {"user": {"login": "reviewer"}, "state": "COMMENTED"},
            {"user": {"login": "reviewer"}, "state": "APPROVED"},
        ]
        responses.rules = [
            {
                "type": "pull_request",
                "parameters": {"required_approving_review_count": 1},
            }
        ]

        facts = await load_facts(responses)

        self.assertEqual(tuple(user.login for user in facts.approvals), ("reviewer",))
        self.assertFalse(facts.changes_requested)
        self.assertEqual(facts.required_approval_count, 1)

    async def test_latest_decisive_review_preserves_active_change_request(self) -> None:
        responses = GitHubResponses()
        responses.reviews = [
            {"user": {"login": "alice"}, "state": "APPROVED"},
            {"user": {"login": "bob"}, "state": "CHANGES_REQUESTED"},
            {"user": {"login": "bob"}, "state": "COMMENTED"},
        ]

        facts = await load_facts(responses)

        self.assertEqual(tuple(user.login for user in facts.approvals), ("alice",))
        self.assertTrue(facts.changes_requested)

    async def test_dismissed_change_request_is_not_active(self) -> None:
        responses = GitHubResponses()
        responses.reviews = [
            {"user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED"},
            {"user": {"login": "reviewer"}, "state": "DISMISSED"},
        ]

        facts = await load_facts(responses)

        self.assertFalse(facts.changes_requested)
        self.assertEqual(facts.approvals, ())

    async def test_successful_required_check(self) -> None:
        responses = self._responses_with_required_check()
        responses.check_runs = [
            {"name": "unit-tests", "status": "completed", "conclusion": "success"}
        ]

        facts = await load_facts(responses)

        self.assertEqual(facts.required_checks[0].status, CheckStatus.PASSED)

    async def test_failed_required_check(self) -> None:
        responses = self._responses_with_required_check()
        responses.check_runs = [
            {"name": "unit-tests", "status": "completed", "conclusion": "failure"}
        ]

        facts = await load_facts(responses)

        self.assertEqual(facts.required_checks[0].status, CheckStatus.FAILED)

    async def test_pending_required_check(self) -> None:
        responses = self._responses_with_required_check()
        responses.check_runs = [
            {"name": "unit-tests", "status": "in_progress", "conclusion": None}
        ]

        facts = await load_facts(responses)

        self.assertEqual(facts.required_checks[0].status, CheckStatus.PENDING)

    async def test_reviews_are_bounded_and_paginated(self) -> None:
        responses = GitHubResponses()
        responses.reviews = [
            {"user": {"login": f"reviewer-{index:03}"}, "state": "APPROVED"}
            for index in range(101)
        ]

        facts = await load_facts(responses)

        review_requests = [
            request
            for request in responses.requests
            if request.url.path.endswith("/reviews")
        ]
        self.assertEqual(len(review_requests), 2)
        self.assertEqual(len(facts.approvals), 101)
        self.assertEqual(
            [request.url.params["page"] for request in review_requests],
            ["1", "2"],
        )

    async def test_unavailable_rules_are_explicitly_unknown(self) -> None:
        responses = GitHubResponses()

        def handler(request: httpx.Request) -> httpx.Response:
            if "/rules/branches/" in request.url.path:
                return httpx.Response(403, json={"message": "private detail"})
            return responses(request)

        client = httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        )
        connector = HttpGitHubConnector(client)
        try:
            facts = await connector.get_pull_request(REQUEST)
        finally:
            await connector.aclose()

        self.assertFalse(facts.required_checks_known)
        self.assertIsNone(facts.required_approval_count)

    async def test_http_error_taxonomy(self) -> None:
        cases = (
            (401, {}, GitHubUnauthorizedError),
            (403, {}, GitHubForbiddenError),
            (403, {"x-ratelimit-remaining": "0"}, GitHubRateLimitedError),
            (429, {}, GitHubRateLimitedError),
            (404, {}, GitHubNotFoundError),
            (503, {}, GitHubUpstreamUnavailableError),
        )
        for status, headers, expected_error in cases:
            with self.subTest(status=status, error=expected_error.__name__):
                async with httpx.AsyncClient(
                    base_url="https://api.github.test",
                    transport=httpx.MockTransport(
                        lambda _request: httpx.Response(
                            status,
                            headers=headers,
                            json={"message": "token=raw-provider-secret"},
                        )
                    ),
                ) as client:
                    connector = HttpGitHubConnector(client)
                    with self.assertRaises(expected_error) as raised:
                        await connector.get_pull_request(REQUEST)
                    self.assertNotIn("raw-provider-secret", str(raised.exception))

    async def test_timeout_is_sanitized(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("token=timeout-secret", request=request)

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(timeout),
        ) as client:
            connector = HttpGitHubConnector(client)
            with self.assertRaises(GitHubTimeoutError) as raised:
                await connector.get_pull_request(REQUEST)

        self.assertNotIn("timeout-secret", str(raised.exception))

    async def test_malformed_json_and_missing_fields_are_invalid(self) -> None:
        responses = (
            httpx.Response(200, content=b"{"),
            httpx.Response(200, json={"number": 42}),
        )
        for response in responses:
            with self.subTest(response=response):
                async with httpx.AsyncClient(
                    base_url="https://api.github.test",
                    transport=httpx.MockTransport(lambda _request: response),
                ) as client:
                    connector = HttpGitHubConnector(client)
                    with self.assertRaises(GitHubInvalidResponseError):
                        await connector.get_pull_request(REQUEST)

    async def test_secrets_and_inputs_are_absent_from_telemetry(self) -> None:
        harness = create_telemetry_harness()

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500,
                json={"message": "token=super-secret repo=octo-org/analytics"},
            )

        client = httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer super-secret"},
        )
        connector = HttpGitHubConnector(client, harness.telemetry)
        try:
            with self.assertRaises(GitHubUpstreamUnavailableError):
                await connector.get_pull_request(REQUEST)
            spans = harness.span_exporter.get_finished_spans()
            exported = repr(spans)
            exported += harness.log_stream.getvalue()
        finally:
            await connector.aclose()
            harness.shutdown()

        self.assertNotIn("super-secret", exported)
        self.assertNotIn("octo-org", exported)
        span = spans[0]
        self.assertEqual(span.attributes["promptql.connector.source"], "live")
        self.assertEqual(span.attributes["promptql.connector.result"], "upstream_unavailable")

    @staticmethod
    def _responses_with_required_check() -> GitHubResponses:
        responses = GitHubResponses()
        responses.rules = [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "unit-tests"}]
                },
            }
        ]
        return responses

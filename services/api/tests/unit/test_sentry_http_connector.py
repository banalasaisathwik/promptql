from datetime import UTC, datetime
import re
import unittest

import httpx

from app.connectors.errors import (
    SentryDeployNotFoundError,
    SentryForbiddenError,
    SentryIncompleteResultError,
    SentryInvalidDeploymentReferenceError,
    SentryInvalidResponseError,
    SentryNotFoundError,
    SentryRateLimitedError,
    SentryReleaseMissingCommitError,
    SentryTimeoutError,
    SentryUnauthorizedError,
    SentryUnsupportedTelemetrySignalError,
    SentryUpstreamUnavailableError,
)
from app.connectors.models import (
    DeploymentEvidenceRequest,
    FailureLocationEvidenceRequest,
    IncidentEvidenceRequest,
    SentryOpenIssuesRequest,
    TelemetryFilter,
    TelemetrySignal,
    TelemetryWindowEvidenceRequest,
)
from app.connectors.sentry_http import HttpSentrySource
from app.investigations import IncidentStatus
from tests.telemetry_support import create_telemetry_harness


ORGANIZATION_SLUG = "acme"
TEST_TOKEN = "local-test-sentry-token"
BASE_URL = "https://sentry.io/api/0"


EVIDENCE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def issue_payload(**updates) -> dict:
    payload = {
        "id": "6507332222",
        "shortId": "CHECKOUT-1",
        "status": "unresolved",
        "firstSeen": "2026-08-17T11:42:00Z",
        "lastSeen": "2026-08-17T11:50:00Z",
        "project": {"id": "9", "slug": "checkout-api"},
    }
    payload.update(updates)
    return payload


def event_payload(**updates) -> dict:
    payload = {
        "eventID": "abc123def456",
        "entries": [
            {
                "type": "exception",
                "data": {
                    "values": [
                        {
                            "type": "ValueError",
                            "stacktrace": {
                                "frames": [
                                    {
                                        "filename": "a.py",
                                        "function": "outer",
                                        "lineNo": 1,
                                    },
                                    {
                                        "filename": "services/checkout.py",
                                        "function": "create_order",
                                        "lineNo": 87,
                                    },
                                ]
                            },
                        }
                    ]
                },
            }
        ],
    }
    payload.update(updates)
    return payload


def release_payload(**updates) -> dict:
    payload = {
        "version": "checkout@1.0.0",
        "dateCreated": "2026-08-17T11:29:00Z",
        "dateReleased": "2026-08-17T11:30:00Z",
        "lastCommit": {"id": "a" * 40},
        "projects": [{"slug": "checkout-api"}],
    }
    payload.update(updates)
    return payload


def deploys_payload() -> list:
    return [
        {"id": "d1", "environment": "production", "dateFinished": "2026-08-17T11:30:00Z"},
        {"id": "d2", "environment": "staging", "dateFinished": "2026-08-17T11:20:00Z"},
    ]


def stats_payload() -> dict:
    return {
        "data": [
            [1755428400, [{"count": 5}]],
            [1755432000, [{"count": 12}]],
        ],
        "start": 1755428400,
        "end": 1755432000,
    }


def short_id_payload(**updates) -> dict:
    payload = {
        "group": issue_payload(id="6507332222"),
        "groupId": "6507332222",
        "organizationSlug": ORGANIZATION_SLUG,
        "projectSlug": "checkout-api",
        "shortId": "PYTHON-FASTAPI-1",
    }
    payload.update(updates)
    return payload


def open_issue_list_item(**updates) -> dict:
    payload = {
        "id": "7699024952",
        "shortId": "PYTHON-FASTAPI-1",
        "title": "KeyError: 0",
        "status": "unresolved",
        "firstSeen": "2026-08-29T05:54:44.826751Z",
        "lastSeen": "2026-08-29T05:59:31.353765Z",
        "project": {"id": "4511988894531584", "slug": "python-fastapi"},
    }
    payload.update(updates)
    return payload


def jira_integration_payload(*, external_issues=None, **updates) -> dict:
    payload = {
        "id": "502008",
        "name": "JIRA",
        "status": "active",
        "provider": {"key": "jira", "slug": "jira", "name": "Jira"},
        "externalIssues": (
            [{"id": "4715209", "key": "KAN-5", "url": "https://x/browse/KAN-5"}]
            if external_issues is None
            else external_issues
        ),
    }
    payload.update(updates)
    return payload


def link_header(*, next_cursor: str | None, next_results: bool) -> str:
    previous = (
        '<https://sentry.io/api/0/x/?cursor=1:0:1>; rel="previous"; '
        'results="false"; cursor="1:0:1"'
    )
    cursor = next_cursor or "1:100:0"
    next_ = (
        f'<https://sentry.io/api/0/x/?cursor={cursor}>; rel="next"; '
        f'results="{"true" if next_results else "false"}"; cursor="{cursor}"'
    )
    return f"{previous}, {next_}"


class SentryResponses:
    def __init__(self) -> None:
        self.issue = issue_payload()
        self.event = event_payload()
        self.release = release_payload()
        self.deploys = deploys_payload()
        self.stats = stats_payload()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/events/latest/"):
            return httpx.Response(200, json=self.event)
        if path.endswith("/deploys/"):
            return httpx.Response(200, json=self.deploys)
        if "/releases/" in path:
            return httpx.Response(200, json=self.release)
        if path.endswith("/events-stats/"):
            return httpx.Response(200, json=self.stats)
        if "/issues/" in path:
            return httpx.Response(200, json=self.issue)
        raise AssertionError(f"unexpected path {path}")


def create_source(handler, telemetry=None):
    client = httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        transport=httpx.MockTransport(handler),
    )
    return HttpSentrySource(client, ORGANIZATION_SLUG, telemetry), client


class HttpSentrySourceSuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_accessible_projects_without_exposing_provider_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/0/organizations/acme/projects/")
            return httpx.Response(200, json=[{
                "slug": "python-fastapi", "name": "Python FastAPI",
                "id": "secret-provider-id", "platform": "python",
            }])

        source, client = create_source(handler)
        try:
            projects = await source.list_accessible_projects()
        finally:
            await client.aclose()

        self.assertEqual(projects[0].slug, "python-fastapi")
        self.assertEqual(projects[0].name, "Python FastAPI")
    async def test_incident_evidence_normalizes_and_never_fabricates_environment_or_category(
        self,
    ) -> None:
        responses = SentryResponses()
        source, client = create_source(responses)
        try:
            evidence = await source.get_incident_evidence(
                IncidentEvidenceRequest(incident_reference="CHECKOUT-1")
            )
        finally:
            await client.aclose()

        self.assertEqual(evidence.content.status, IncidentStatus.ACTIVE)
        self.assertEqual(evidence.content.service, "checkout-api")
        self.assertIsNone(evidence.content.environment)
        self.assertIsNone(evidence.content.category)
        self.assertEqual(
            evidence.content.started_at,
            datetime(2026, 8, 17, 11, 42, tzinfo=UTC),
        )

    async def test_issue_status_values_map_to_documented_incident_statuses(self) -> None:
        cases = (
            ("unresolved", IncidentStatus.ACTIVE),
            ("resolved", IncidentStatus.RESOLVED),
            ("ignored", IncidentStatus.UNKNOWN),
        )
        for raw_status, expected in cases:
            with self.subTest(raw_status=raw_status):
                responses = SentryResponses()
                responses.issue = issue_payload(status=raw_status)
                source, client = create_source(responses)
                try:
                    evidence = await source.get_incident_evidence(
                        IncidentEvidenceRequest(incident_reference="CHECKOUT-1")
                    )
                finally:
                    await client.aclose()
                self.assertEqual(evidence.content.status, expected)

    async def test_failure_location_uses_last_frame_not_first(self) -> None:
        responses = SentryResponses()
        source, client = create_source(responses)
        try:
            evidence = await source.get_failure_location_evidence(
                FailureLocationEvidenceRequest(incident_reference="CHECKOUT-1")
            )
        finally:
            await client.aclose()

        self.assertEqual(evidence.content.file_path, "services/checkout.py")
        self.assertEqual(evidence.content.function_name, "create_order")
        self.assertEqual(evidence.content.line_number, 87)
        self.assertEqual(evidence.content.error_category, "ValueError")

    async def test_short_id_resolves_before_issue_and_event_requests(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            path = request.url.path
            if path.endswith("/issues/PYTHON-FASTAPI-1/"):
                return httpx.Response(404)
            if path.endswith("/shortids/PYTHON-FASTAPI-1/"):
                return httpx.Response(200, json=short_id_payload())
            if path.endswith("/issues/6507332222/events/latest/"):
                return httpx.Response(200, json=event_payload())
            raise AssertionError(f"unexpected path {path}")

        source, client = create_source(handler)
        try:
            incident = await source.get_incident_evidence(
                IncidentEvidenceRequest(incident_reference="PYTHON-FASTAPI-1")
            )
            location = await source.get_failure_location_evidence(
                FailureLocationEvidenceRequest(
                    incident_reference="PYTHON-FASTAPI-1"
                )
            )
        finally:
            await client.aclose()

        self.assertEqual(incident.content.service, "checkout-api")
        self.assertEqual(location.content.file_path, "services/checkout.py")
        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/api/0/organizations/acme/issues/PYTHON-FASTAPI-1/",
                "/api/0/organizations/acme/shortids/PYTHON-FASTAPI-1/",
                "/api/0/organizations/acme/issues/PYTHON-FASTAPI-1/",
                "/api/0/organizations/acme/shortids/PYTHON-FASTAPI-1/",
                "/api/0/organizations/acme/issues/6507332222/events/latest/",
            ],
        )

    async def test_frame_line_number_uses_sentrys_actual_camelcase_field(self) -> None:
        responses = SentryResponses()
        responses.event = event_payload(
            entries=[
                {
                    "type": "exception",
                    "data": {
                        "values": [
                            {
                                "type": "ValueError",
                                "stacktrace": {
                                    "frames": [
                                        {
                                            "filename": "checkout.py",
                                            "function": "create_order",
                                            "lineNo": 87,
                                            "absPath": "/app/checkout.py",
                                            "inApp": True,
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            ]
        )
        source, client = create_source(responses)
        try:
            evidence = await source.get_failure_location_evidence(
                FailureLocationEvidenceRequest(incident_reference="CHECKOUT-1")
            )
        finally:
            await client.aclose()

        self.assertEqual(evidence.content.line_number, 87)

    async def test_deployment_evidence_resolves_the_matching_environment_deploy(self) -> None:
        responses = SentryResponses()
        source, client = create_source(responses)
        try:
            evidence = await source.get_deployment_evidence(
                DeploymentEvidenceRequest(
                    deployment_reference="checkout@1.0.0:production"
                )
            )
        finally:
            await client.aclose()

        self.assertEqual(evidence.content.environment, "production")
        self.assertEqual(evidence.content.service, "checkout-api")
        self.assertEqual(evidence.content.commit_sha, "a" * 40)
        self.assertEqual(
            evidence.content.deployed_at,
            datetime(2026, 8, 17, 11, 30, tzinfo=UTC),
        )

    async def test_telemetry_window_sums_stats_buckets(self) -> None:
        responses = SentryResponses()
        source, client = create_source(responses)
        try:
            evidence = await source.get_telemetry_window_evidence(
                TelemetryWindowEvidenceRequest(
                    service="checkout-api",
                    signal=TelemetrySignal.ERROR_EVENTS,
                    start_time=datetime(2026, 8, 17, 11, 40, tzinfo=UTC),
                    end_time=datetime(2026, 8, 17, 11, 45, tzinfo=UTC),
                    filters=(TelemetryFilter(key="environment", value="production"),),
                )
            )
        finally:
            await client.aclose()

        self.assertEqual(evidence.content.event_count, 17)

    async def test_telemetry_request_shape_carries_project_query_and_window(self) -> None:
        requests: list[httpx.Request] = []
        responses = SentryResponses()

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return responses(request)

        source, client = create_source(handler)
        try:
            await source.get_telemetry_window_evidence(
                TelemetryWindowEvidenceRequest(
                    service="checkout-api",
                    signal=TelemetrySignal.ERROR_EVENTS,
                    start_time=datetime(2026, 8, 17, 11, 40, tzinfo=UTC),
                    end_time=datetime(2026, 8, 17, 11, 45, tzinfo=UTC),
                    filters=(TelemetryFilter(key="environment", value="production"),),
                )
            )
        finally:
            await client.aclose()

        self.assertEqual(len(requests), 1)
        params = requests[0].url.params
        self.assertEqual(params["project"], "checkout-api")
        self.assertIn("event.type:error", params["query"])
        self.assertIn("environment:production", params["query"])
        self.assertEqual(params["yAxis"], "count()")


class HttpSentrySourceOpenIssuesTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_open_issues_and_normalizes_the_verified_fields(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json=[open_issue_list_item()],
                headers={"link": link_header(next_cursor=None, next_results=False)},
            )

        source, client = create_source(handler)
        try:
            issues = await source.list_open_issues(
                SentryOpenIssuesRequest(project_slug="python-fastapi")
            )
        finally:
            await client.aclose()

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_id, "7699024952")
        self.assertEqual(issues[0].short_id, "PYTHON-FASTAPI-1")
        self.assertEqual(issues[0].title, "KeyError: 0")
        self.assertEqual(issues[0].project_slug, "python-fastapi")
        self.assertEqual(
            issues[0].first_seen,
            datetime(2026, 8, 29, 5, 54, 44, 826751, tzinfo=UTC),
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].url.path,
            "/api/0/projects/acme/python-fastapi/issues/",
        )
        self.assertEqual(requests[0].url.params["query"], "is:unresolved")

    async def test_release_filter_is_appended_to_the_query_parameter(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json=[],
                headers={"link": link_header(next_cursor=None, next_results=False)},
            )

        source, client = create_source(handler)
        try:
            issues = await source.list_open_issues(
                SentryOpenIssuesRequest(
                    project_slug="python-fastapi",
                    release="e1448f6171fd009aca9f8136f7e6ec8120a9e515",
                )
            )
        finally:
            await client.aclose()

        self.assertEqual(issues, ())
        self.assertEqual(
            requests[0].url.params["query"],
            "is:unresolved release:e1448f6171fd009aca9f8136f7e6ec8120a9e515",
        )

    async def test_missing_issue_title_is_normalized_as_none(self) -> None:
        payload = open_issue_list_item()
        payload.pop("title")
        source, client = create_source(
            lambda _request: httpx.Response(
                200,
                json=[payload],
                headers={"link": link_header(next_cursor=None, next_results=False)},
            )
        )
        try:
            issues = await source.list_open_issues(
                SentryOpenIssuesRequest(project_slug="python-fastapi")
            )
        finally:
            await client.aclose()

        self.assertEqual(issues[0].title, None)

    async def test_follows_the_next_cursor_until_results_is_false(self) -> None:
        pages = [
            httpx.Response(
                200,
                json=[open_issue_list_item(id="1", shortId="PYTHON-FASTAPI-1")],
                headers={"link": link_header(next_cursor="page-2", next_results=True)},
            ),
            httpx.Response(
                200,
                json=[open_issue_list_item(id="2", shortId="PYTHON-FASTAPI-2")],
                headers={"link": link_header(next_cursor=None, next_results=False)},
            ),
        ]
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return pages[len(requests) - 1]

        source, client = create_source(handler)
        try:
            issues = await source.list_open_issues(
                SentryOpenIssuesRequest(project_slug="python-fastapi")
            )
        finally:
            await client.aclose()

        self.assertEqual([issue.issue_id for issue in issues], ["1", "2"])
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1].url.params["cursor"], "page-2")

    async def test_pagination_bound_is_a_typed_incomplete_result_not_a_silent_truncation(
        self,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[open_issue_list_item()],
                headers={"link": link_header(next_cursor="always-more", next_results=True)},
            )

        source, client = create_source(handler)
        try:
            with self.assertRaises(SentryIncompleteResultError):
                await source.list_open_issues(
                    SentryOpenIssuesRequest(project_slug="python-fastapi")
                )
        finally:
            await client.aclose()

    async def test_non_list_payload_is_rejected(self) -> None:
        source, client = create_source(
            lambda _request: httpx.Response(200, json={"not": "a-list"})
        )
        try:
            with self.assertRaises(SentryInvalidResponseError):
                await source.list_open_issues(
                    SentryOpenIssuesRequest(project_slug="python-fastapi")
                )
        finally:
            await client.aclose()


class HttpSentrySourceLinkedJiraKeyTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_linked_jira_key_from_the_verified_field_path(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=[jira_integration_payload()])

        source, client = create_source(handler)
        try:
            linked_jira_key = await source.get_linked_jira_key("7699024952")
        finally:
            await client.aclose()

        self.assertEqual(linked_jira_key, "KAN-5")
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].url.path,
            "/api/0/organizations/acme/issues/7699024952/integrations/",
        )

    async def test_returns_none_when_external_issues_is_empty(self) -> None:
        source, client = create_source(
            lambda _request: httpx.Response(
                200, json=[jira_integration_payload(external_issues=[])]
            )
        )
        try:
            linked_jira_key = await source.get_linked_jira_key("7697191065")
        finally:
            await client.aclose()

        self.assertIsNone(linked_jira_key)

    async def test_returns_none_when_no_integrations_are_configured_at_all(self) -> None:
        source, client = create_source(lambda _request: httpx.Response(200, json=[]))
        try:
            linked_jira_key = await source.get_linked_jira_key("7697191065")
        finally:
            await client.aclose()

        self.assertIsNone(linked_jira_key)

    async def test_non_jira_integrations_are_filtered_out_not_assumed_to_be_jira(
        self,
    ) -> None:
        source, client = create_source(
            lambda _request: httpx.Response(
                200,
                json=[
                    jira_integration_payload(
                        id="1",
                        provider={"key": "github", "slug": "github", "name": "GitHub"},
                        externalIssues=[{"id": "9", "key": "org/repo#42"}],
                    )
                ],
            )
        )
        try:
            linked_jira_key = await source.get_linked_jira_key("7699024952")
        finally:
            await client.aclose()

        self.assertIsNone(linked_jira_key)

    async def test_multiple_jira_integrations_take_the_first_documented_choice(
        self,
    ) -> None:
        source, client = create_source(
            lambda _request: httpx.Response(
                200,
                json=[
                    jira_integration_payload(
                        id="1", externalIssues=[{"id": "1", "key": "KAN-5"}]
                    ),
                    jira_integration_payload(
                        id="2", externalIssues=[{"id": "2", "key": "KAN-9"}]
                    ),
                ],
            )
        )
        try:
            linked_jira_key = await source.get_linked_jira_key("7699024952")
        finally:
            await client.aclose()

        self.assertEqual(linked_jira_key, "KAN-5")

    async def test_multiple_external_issues_take_the_first_documented_choice(
        self,
    ) -> None:
        source, client = create_source(
            lambda _request: httpx.Response(
                200,
                json=[
                    jira_integration_payload(
                        external_issues=[
                            {"id": "1", "key": "KAN-5"},
                            {"id": "2", "key": "KAN-6"},
                        ]
                    )
                ],
            )
        )
        try:
            linked_jira_key = await source.get_linked_jira_key("7699024952")
        finally:
            await client.aclose()

        self.assertEqual(linked_jira_key, "KAN-5")

    async def test_malformed_jira_key_shape_is_rejected_not_silently_dropped(self) -> None:
        source, client = create_source(
            lambda _request: httpx.Response(
                200,
                json=[
                    jira_integration_payload(
                        externalIssues=[{"id": "1", "key": "not-a-valid-jira-key"}]
                    )
                ],
            )
        )
        try:
            with self.assertRaises(SentryInvalidResponseError):
                await source.get_linked_jira_key("7699024952")
        finally:
            await client.aclose()

    async def test_non_list_payload_is_rejected(self) -> None:
        source, client = create_source(
            lambda _request: httpx.Response(200, json={"not": "a-list"})
        )
        try:
            with self.assertRaises(SentryInvalidResponseError):
                await source.get_linked_jira_key("7699024952")
        finally:
            await client.aclose()


class HttpSentrySourceIssueCommitShaTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_lastcommit_when_the_release_tracks_one(self) -> None:
        responses = SentryResponses()
        responses.issue = issue_payload(
            firstRelease={
                "version": "checkout@1.0.0",
                "lastCommit": {"id": "a" * 40},
            }
        )
        source, client = create_source(responses)
        try:
            commit_sha = await source.get_issue_commit_sha("6507332222")
        finally:
            await client.aclose()

        self.assertEqual(commit_sha, "a" * 40)

    async def test_falls_back_to_release_version_shaped_like_a_commit_sha(self) -> None:
        responses = SentryResponses()
        responses.issue = issue_payload(
            firstRelease={"version": "e" * 40, "lastCommit": None}
        )
        source, client = create_source(responses)
        try:
            commit_sha = await source.get_issue_commit_sha("6507332222")
        finally:
            await client.aclose()

        self.assertEqual(commit_sha, "e" * 40)

    async def test_returns_none_when_version_does_not_look_like_a_commit_sha(self) -> None:
        responses = SentryResponses()
        responses.issue = issue_payload(
            firstRelease={"version": "checkout@1.0.0", "lastCommit": None}
        )
        source, client = create_source(responses)
        try:
            commit_sha = await source.get_issue_commit_sha("6507332222")
        finally:
            await client.aclose()

        self.assertIsNone(commit_sha)

    async def test_returns_none_when_the_issue_has_no_release_at_all(self) -> None:
        responses = SentryResponses()
        responses.issue = issue_payload(firstRelease=None)
        source, client = create_source(responses)
        try:
            commit_sha = await source.get_issue_commit_sha("6507332222")
        finally:
            await client.aclose()

        self.assertIsNone(commit_sha)

    async def test_malformed_lastcommit_id_is_rejected_not_silently_dropped(self) -> None:
        responses = SentryResponses()
        responses.issue = issue_payload(
            firstRelease={"version": "checkout@1.0.0", "lastCommit": {"id": "not-a-sha"}}
        )
        source, client = create_source(responses)
        try:
            with self.assertRaises(SentryInvalidResponseError):
                await source.get_issue_commit_sha("6507332222")
        finally:
            await client.aclose()

    async def test_resolves_via_short_id_the_same_as_other_issue_lookups(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            path = request.url.path
            if path.endswith("/issues/PYTHON-FASTAPI-1/"):
                return httpx.Response(404)
            if path.endswith("/shortids/PYTHON-FASTAPI-1/"):
                return httpx.Response(
                    200,
                    json=short_id_payload(
                        group=issue_payload(
                            id="6507332222",
                            firstRelease={"version": "f" * 40, "lastCommit": None},
                        )
                    ),
                )
            raise AssertionError(f"unexpected path {path}")

        source, client = create_source(handler)
        try:
            commit_sha = await source.get_issue_commit_sha("PYTHON-FASTAPI-1")
        finally:
            await client.aclose()

        self.assertEqual(commit_sha, "f" * 40)


class HttpSentrySourceValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsupported_telemetry_signal_is_rejected_before_http(self) -> None:
        request_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json=stats_payload())

        source, client = create_source(handler)
        try:
            with self.assertRaises(SentryUnsupportedTelemetrySignalError):
                await source.get_telemetry_window_evidence(
                    TelemetryWindowEvidenceRequest(
                        service="checkout-api",
                        signal=TelemetrySignal.LOG_EVENTS,
                        start_time=datetime(2026, 8, 17, 11, 40, tzinfo=UTC),
                        end_time=datetime(2026, 8, 17, 11, 45, tzinfo=UTC),
                    )
                )
        finally:
            await client.aclose()
        self.assertEqual(request_count, 0)

    async def test_malformed_deployment_reference_is_rejected_before_http(self) -> None:
        request_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json=release_payload())

        source, client = create_source(handler)
        try:
            for invalid_reference in ("checkout@1.0.0", ":production", "checkout@1.0.0:"):
                with self.subTest(deployment_reference=invalid_reference):
                    with self.assertRaises(SentryInvalidDeploymentReferenceError):
                        await source.get_deployment_evidence(
                            DeploymentEvidenceRequest(
                                deployment_reference=invalid_reference
                            )
                        )
        finally:
            await client.aclose()
        self.assertEqual(request_count, 0)

    async def test_release_with_no_commit_raises_typed_error_not_invalid_content(
        self,
    ) -> None:
        responses = SentryResponses()
        responses.release = release_payload(lastCommit=None)
        source, client = create_source(responses)
        try:
            with self.assertRaises(SentryReleaseMissingCommitError):
                await source.get_deployment_evidence(
                    DeploymentEvidenceRequest(
                        deployment_reference="checkout@1.0.0:production"
                    )
                )
        finally:
            await client.aclose()

    async def test_zero_or_multiple_matching_deploys_are_rejected(self) -> None:
        cases = (
            [],
            [
                {"id": "d1", "environment": "production", "dateFinished": "2026-08-17T11:30:00Z"},
                {"id": "d2", "environment": "production", "dateFinished": "2026-08-17T11:31:00Z"},
            ],
        )
        for deploys in cases:
            with self.subTest(deploy_count=len(deploys)):
                responses = SentryResponses()
                responses.deploys = deploys
                source, client = create_source(responses)
                try:
                    with self.assertRaises(SentryDeployNotFoundError):
                        await source.get_deployment_evidence(
                            DeploymentEvidenceRequest(
                                deployment_reference="checkout@1.0.0:production"
                            )
                        )
                finally:
                    await client.aclose()

    async def test_stats_bucket_summation_handles_multiple_values_per_bucket(self) -> None:
        responses = SentryResponses()
        responses.stats = {
            "data": [
                [1755428400, [{"count": 3}, {"count": 4}]],
                [1755432000, [{"count": 10}]],
            ],
            "start": 1755428400,
            "end": 1755432000,
        }
        source, client = create_source(responses)
        try:
            evidence = await source.get_telemetry_window_evidence(
                TelemetryWindowEvidenceRequest(
                    service="checkout-api",
                    signal=TelemetrySignal.ERROR_EVENTS,
                    start_time=datetime(2026, 8, 17, 11, 40, tzinfo=UTC),
                    end_time=datetime(2026, 8, 17, 11, 45, tzinfo=UTC),
                )
            )
        finally:
            await client.aclose()
        self.assertEqual(evidence.content.event_count, 17)

    async def test_malformed_response_shapes_are_rejected(self) -> None:
        payloads = (
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"id": "1"}),
            httpx.Response(
                200,
                json={**issue_payload(), "status": "muted-legacy-alias"},
            ),
        )
        for response in payloads:
            with self.subTest(payload=response.content[:30]):
                source, client = create_source(lambda _request: response)
                try:
                    with self.assertRaises(SentryInvalidResponseError):
                        await source.get_incident_evidence(
                            IncidentEvidenceRequest(incident_reference="CHECKOUT-1")
                        )
                finally:
                    await client.aclose()

    async def test_event_with_no_exception_entry_is_rejected(self) -> None:
        responses = SentryResponses()
        responses.event = event_payload(
            entries=[{"type": "breadcrumbs", "data": {"values": []}}]
        )
        source, client = create_source(responses)
        try:
            with self.assertRaises(SentryInvalidResponseError):
                await source.get_failure_location_evidence(
                    FailureLocationEvidenceRequest(incident_reference="CHECKOUT-1")
                )
        finally:
            await client.aclose()


class HttpSentrySourceHttpErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_error_taxonomy_is_sanitized(self) -> None:
        cases = (
            (401, SentryUnauthorizedError),
            (403, SentryForbiddenError),
            (404, SentryNotFoundError),
            (429, SentryRateLimitedError),
            (503, SentryUpstreamUnavailableError),
        )
        for status, expected_error in cases:
            with self.subTest(status=status):
                source, client = create_source(
                    lambda _request, status=status: httpx.Response(
                        status,
                        text="provider body must remain private",
                    )
                )
                try:
                    with self.assertRaises(expected_error) as raised:
                        await source.get_incident_evidence(
                            IncidentEvidenceRequest(incident_reference="CHECKOUT-1")
                        )
                finally:
                    await client.aclose()
                self.assertNotIn("provider body", str(raised.exception))

    async def test_timeout_and_network_failure_are_distinct(self) -> None:
        failures = (
            (
                lambda request: (_ for _ in ()).throw(
                    httpx.ReadTimeout("private timeout", request=request)
                ),
                SentryTimeoutError,
            ),
            (
                lambda request: (_ for _ in ()).throw(
                    httpx.ConnectError("private network", request=request)
                ),
                SentryUpstreamUnavailableError,
            ),
        )
        for handler, expected_error in failures:
            with self.subTest(error=expected_error.__name__):
                source, client = create_source(handler)
                try:
                    with self.assertRaises(expected_error) as raised:
                        await source.get_incident_evidence(
                            IncidentEvidenceRequest(incident_reference="CHECKOUT-1")
                        )
                finally:
                    await client.aclose()
                self.assertNotIn("private", str(raised.exception))

    async def test_secrets_and_external_values_are_absent_from_telemetry(self) -> None:
        harness = create_telemetry_harness()

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                text=f"token={TEST_TOKEN} org={ORGANIZATION_SLUG} issue=CHECKOUT-1",
            )

        source, client = create_source(handler, harness.telemetry)
        try:
            with self.assertRaises(SentryUnauthorizedError):
                await source.get_incident_evidence(
                    IncidentEvidenceRequest(incident_reference="CHECKOUT-1")
                )
            spans = harness.span_exporter.get_finished_spans()
            serialized = repr(
                tuple((span.name, dict(span.attributes), span.events) for span in spans)
            )
            combined = serialized + harness.log_stream.getvalue()
            for secret_or_input in (TEST_TOKEN, "CHECKOUT-1"):
                self.assertNotIn(secret_or_input, combined)
            connector_span = next(
                span
                for span in spans
                if span.name == "connector.sentry.get_incident_evidence"
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


class EvidenceIdentifierSanitizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deployment_evidence_id_survives_unsafe_release_version_characters(
        self,
    ) -> None:
        responses = SentryResponses()
        responses.release = release_payload(version="checkout@1.0.0+build.5")
        source, client = create_source(responses)
        try:
            evidence = await source.get_deployment_evidence(
                DeploymentEvidenceRequest(
                    deployment_reference="checkout@1.0.0+build.5:production"
                )
            )
        finally:
            await client.aclose()

        self.assertRegex(evidence.evidence_id, EVIDENCE_IDENTIFIER_PATTERN)
        self.assertIn(
            "checkout@1.0.0+build.5", evidence.provenance.source_reference
        )

    async def test_failure_location_evidence_id_survives_unsafe_incident_reference(
        self,
    ) -> None:
        responses = SentryResponses()
        source, client = create_source(responses)
        try:
            evidence = await source.get_failure_location_evidence(
                FailureLocationEvidenceRequest(
                    incident_reference="CHECKOUT/1@risky%ref"
                )
            )
        finally:
            await client.aclose()

        self.assertRegex(evidence.evidence_id, EVIDENCE_IDENTIFIER_PATTERN)

    async def test_telemetry_evidence_id_survives_unsafe_service_characters(
        self,
    ) -> None:
        responses = SentryResponses()
        source, client = create_source(responses)
        try:
            evidence = await source.get_telemetry_window_evidence(
                TelemetryWindowEvidenceRequest(
                    service="checkout/api@v2%draft",
                    signal=TelemetrySignal.ERROR_EVENTS,
                    start_time=datetime(2026, 8, 17, 11, 40, tzinfo=UTC),
                    end_time=datetime(2026, 8, 17, 11, 45, tzinfo=UTC),
                )
            )
        finally:
            await client.aclose()

        self.assertRegex(evidence.evidence_id, EVIDENCE_IDENTIFIER_PATTERN)
        self.assertIn("checkout/api@v2%draft", evidence.provenance.source_reference)

    async def test_incident_evidence_id_uses_canonical_numeric_issue_id(self) -> None:
        responses = SentryResponses()
        responses.issue = issue_payload(id="987654321")
        source, client = create_source(responses)
        try:
            evidence = await source.get_incident_evidence(
                IncidentEvidenceRequest(incident_reference="CHECKOUT-1")
            )
        finally:
            await client.aclose()

        self.assertEqual(evidence.evidence_id, "sentry:issue:987654321")
        self.assertRegex(evidence.evidence_id, EVIDENCE_IDENTIFIER_PATTERN)


if __name__ == "__main__":
    unittest.main()

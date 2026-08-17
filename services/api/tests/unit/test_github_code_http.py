from datetime import UTC, datetime
import unittest

import httpx

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
from app.connectors.github_code_http import HttpGitHubCodeEvidenceSource
from app.connectors.models import (
    GitHubCommitEvidenceRequest,
    GitHubPullRequestEvidenceRequest,
)
from app.investigations import (
    ChangedFileEvidenceContent,
    CommitEvidenceContent,
    DiffHunkEvidenceContent,
    EvidenceKind,
    FileChangeType,
    PullRequestEvidenceContent,
)
from tests.telemetry_support import create_telemetry_harness


SHA = "a" * 40
PARENT_SHA = "b" * 40
BASE_SHA = "c" * 40
MERGE_SHA = "d" * 40
RETRIEVED_AT = datetime(2026, 8, 17, 12, 30, tzinfo=UTC)
COMMIT_REQUEST = GitHubCommitEvidenceRequest(
    repository_owner="octo-org",
    repository_name="analytics",
    commit_sha=SHA,
)
PULL_REQUEST = GitHubPullRequestEvidenceRequest(
    repository_owner="octo-org",
    repository_name="analytics",
    pr_number=42,
)


def commit_response(**updates):
    response = {
        "sha": SHA,
        "commit": {
            "message": "Guard checkout totals",
            "author": {
                "name": "Private Author",
                "email": "private@example.test",
                "date": "2026-08-17T11:45:00Z",
            },
        },
        "parents": [{"sha": PARENT_SHA, "url": "https://private.test"}],
        "author": {"login": "private-login"},
    }
    response.update(updates)
    return response


def pull_response(**updates):
    response = {
        "number": 42,
        "title": "Guard checkout totals",
        "state": "closed",
        "merged": True,
        "merge_commit_sha": MERGE_SHA,
        "head": {"sha": SHA, "ref": "private-branch"},
        "base": {"sha": BASE_SHA, "ref": "main"},
        "user": {"login": "private-login"},
    }
    response.update(updates)
    return response


def file_response(path: str = "services/checkout.py", **updates):
    response = {
        "filename": path,
        "status": "modified",
        "additions": 2,
        "deletions": 1,
        "changes": 3,
        "patch": (
            "@@ -10,2 +10,3 @@ def checkout():\n"
            " context\n"
            "-old value\n"
            "+new value\n"
            "+extra value"
        ),
        "raw_url": "https://temporary.example.test/signed-secret",
    }
    response.update(updates)
    return response


class GitHubCodeResponses:
    def __init__(self) -> None:
        self.commit = commit_response()
        self.pull = pull_response()
        self.files = [file_response()]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith(f"/commits/{SHA}"):
            return httpx.Response(200, json=self.commit)
        if path.endswith("/pulls/42"):
            return httpx.Response(200, json=self.pull)
        if path.endswith("/pulls/42/files"):
            page = int(request.url.params.get("page", "1"))
            per_page = int(request.url.params.get("per_page", "100"))
            start = (page - 1) * per_page
            return httpx.Response(200, json=self.files[start : start + per_page])
        return httpx.Response(404, json={"message": "private provider detail"})


def create_source(
    responses,
    *,
    telemetry=None,
    max_file_pages: int = 10,
) -> HttpGitHubCodeEvidenceSource:
    client = httpx.AsyncClient(
        base_url="https://api.github.test",
        transport=httpx.MockTransport(responses),
        headers={"Authorization": "Bearer test-secret"},
    )
    return HttpGitHubCodeEvidenceSource(
        client,
        telemetry,
        max_file_pages=max_file_pages,
        clock=lambda: RETRIEVED_AT,
    )


class HttpGitHubCodeEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_commit_response_normalizes_metadata_parents_and_provenance(self) -> None:
        source = create_source(GitHubCodeResponses())
        try:
            evidence = await source.get_commit_evidence(COMMIT_REQUEST)
        finally:
            await source.aclose()

        self.assertIs(evidence.kind, EvidenceKind.COMMIT)
        self.assertIsInstance(evidence.content, CommitEvidenceContent)
        self.assertEqual(evidence.content.commit_sha, SHA)
        self.assertEqual(evidence.content.parent_shas, (PARENT_SHA,))
        self.assertEqual(evidence.content.message, "Guard checkout totals")
        self.assertEqual(
            evidence.provenance.observed_at,
            datetime(2026, 8, 17, 11, 45, tzinfo=UTC),
        )
        self.assertEqual(evidence.provenance.retrieved_at, RETRIEVED_AT)

    async def test_commit_output_excludes_profiles_email_urls_and_raw_payload(self) -> None:
        source = create_source(GitHubCodeResponses())
        try:
            evidence = await source.get_commit_evidence(COMMIT_REQUEST)
        finally:
            await source.aclose()

        serialized = evidence.model_dump_json()
        for forbidden in (
            "private@example.test",
            "private-login",
            "https://private.test",
            "test-secret",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, serialized)

    async def test_invalid_commit_identity_fields_and_timestamp_fail_safely(self) -> None:
        cases = (
            {"sha": "e" * 40},
            {"parents": [{"sha": "short"}]},
            {
                "commit": {
                    "message": "Guard checkout totals",
                    "author": {"date": "not-a-date"},
                }
            },
        )
        for updates in cases:
            with self.subTest(updates=updates):
                responses = GitHubCodeResponses()
                responses.commit = commit_response(**updates)
                source = create_source(responses)
                try:
                    with self.assertRaises(GitHubInvalidResponseError):
                        await source.get_commit_evidence(COMMIT_REQUEST)
                finally:
                    await source.aclose()

    async def test_missing_commit_author_time_is_preserved_as_unknown(self) -> None:
        responses = GitHubCodeResponses()
        responses.commit = commit_response(
            commit={
                "message": "Guard checkout totals",
                "author": None,
            }
        )
        source = create_source(responses)
        try:
            evidence = await source.get_commit_evidence(COMMIT_REQUEST)
        finally:
            await source.aclose()

        self.assertIsNone(evidence.content.authored_at)
        self.assertIsNone(evidence.provenance.observed_at)

    async def test_commit_message_and_parent_bounds_fail_as_incomplete(self) -> None:
        cases = (
            {
                "commit": {
                    "message": "x" * 4097,
                    "author": None,
                }
            },
            {"parents": [{"sha": PARENT_SHA}] * 101},
        )
        for updates in cases:
            with self.subTest(bound=tuple(updates)):
                responses = GitHubCodeResponses()
                responses.commit = commit_response(**updates)
                source = create_source(responses)
                try:
                    with self.assertRaises(GitHubIncompleteResultError):
                        await source.get_commit_evidence(COMMIT_REQUEST)
                finally:
                    await source.aclose()

    async def test_pull_request_normalizes_base_head_state_and_merge_commit(self) -> None:
        source = create_source(GitHubCodeResponses())
        try:
            evidence = await source.get_pull_request_evidence(PULL_REQUEST)
        finally:
            await source.aclose()

        self.assertIs(evidence.kind, EvidenceKind.PULL_REQUEST)
        self.assertIsInstance(evidence.content, PullRequestEvidenceContent)
        self.assertEqual(evidence.content.base_sha, BASE_SHA)
        self.assertEqual(evidence.content.head_sha, SHA)
        self.assertEqual(evidence.content.merge_commit_sha, MERGE_SHA)
        self.assertEqual(evidence.content.state.value, "merged")
        self.assertIsNone(evidence.provenance.observed_at)

    async def test_optional_merge_commit_is_preserved_as_absent(self) -> None:
        responses = GitHubCodeResponses()
        responses.pull = pull_response(
            state="open",
            merged=False,
            merge_commit_sha=None,
        )
        source = create_source(responses)
        try:
            evidence = await source.get_pull_request_evidence(PULL_REQUEST)
        finally:
            await source.aclose()

        self.assertEqual(evidence.content.state.value, "open")
        self.assertIsNone(evidence.content.merge_commit_sha)

    async def test_file_statuses_normalize_to_domain_change_types(self) -> None:
        cases = (
            ("modified", None, FileChangeType.MODIFIED),
            ("added", None, FileChangeType.ADDED),
            ("removed", None, FileChangeType.DELETED),
            ("renamed", "old.py", FileChangeType.RENAMED),
        )
        for status, previous_path, expected in cases:
            with self.subTest(status=status):
                responses = GitHubCodeResponses()
                updates = {
                    "status": status,
                    "patch": None,
                    "additions": 1,
                    "deletions": 0,
                    "changes": 1,
                }
                if previous_path is not None:
                    updates["previous_filename"] = previous_path
                responses.files = [file_response("new.py", **updates)]
                source = create_source(responses)
                try:
                    evidence = await source.get_changed_file_evidence(PULL_REQUEST)
                finally:
                    await source.aclose()

                self.assertEqual(len(evidence), 1)
                self.assertEqual(evidence[0].content.change_type, expected)
                self.assertEqual(evidence[0].content.previous_path, previous_path)

    async def test_missing_patch_is_explicit_and_produces_no_hunk(self) -> None:
        responses = GitHubCodeResponses()
        responses.files = [file_response(patch=None)]
        source = create_source(responses)
        try:
            evidence = await source.get_changed_file_evidence(PULL_REQUEST)
        finally:
            await source.aclose()

        self.assertEqual(len(evidence), 1)
        self.assertIsInstance(evidence[0].content, ChangedFileEvidenceContent)
        self.assertFalse(evidence[0].content.patch_available)

    async def test_patch_normalizes_file_then_bounded_hunk_with_same_path(self) -> None:
        source = create_source(GitHubCodeResponses())
        try:
            evidence = await source.get_changed_file_evidence(PULL_REQUEST)
        finally:
            await source.aclose()

        self.assertEqual(
            tuple(item.kind for item in evidence),
            (EvidenceKind.CHANGED_FILE, EvidenceKind.DIFF_HUNK),
        )
        file_content = evidence[0].content
        hunk_content = evidence[1].content
        self.assertIsInstance(file_content, ChangedFileEvidenceContent)
        self.assertIsInstance(hunk_content, DiffHunkEvidenceContent)
        self.assertEqual(hunk_content.file_path, file_content.path)
        self.assertEqual((hunk_content.old_count, hunk_content.new_count), (2, 3))

    async def test_multiple_hunks_are_normalized_in_patch_order(self) -> None:
        responses = GitHubCodeResponses()
        responses.files = [
            file_response(
                patch=(
                    "@@ -1 +1 @@\n-old\n+new\n"
                    "@@ -20,0 +21,2 @@\n+first\n+second"
                )
            )
        ]
        source = create_source(responses)
        try:
            evidence = await source.get_changed_file_evidence(PULL_REQUEST)
        finally:
            await source.aclose()

        self.assertEqual(len(evidence), 3)
        self.assertEqual(
            tuple(item.content.new_start for item in evidence[1:]),
            (1, 21),
        )

    async def test_malformed_or_truncated_patch_fails_without_partial_evidence(self) -> None:
        cases = (
            ("not-a-hunk", GitHubInvalidResponseError),
            ("@@ -1,2 +1,2 @@\n-old\n+new", GitHubIncompleteResultError),
        )
        for patch, expected_error in cases:
            with self.subTest(error=expected_error.__name__):
                responses = GitHubCodeResponses()
                responses.files = [file_response(patch=patch)]
                source = create_source(responses)
                try:
                    with self.assertRaises(expected_error):
                        await source.get_changed_file_evidence(PULL_REQUEST)
                finally:
                    await source.aclose()

    async def test_invalid_counts_or_unknown_status_are_rejected(self) -> None:
        cases = (
            {"changes": 99},
            {"additions": -1},
            {"status": "copied"},
            {"status": "renamed", "previous_filename": None},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                responses = GitHubCodeResponses()
                responses.files = [file_response(patch=None, **updates)]
                source = create_source(responses)
                try:
                    with self.assertRaises(GitHubInvalidResponseError):
                        await source.get_changed_file_evidence(PULL_REQUEST)
                finally:
                    await source.aclose()

    async def test_changed_files_are_paginated_in_provider_order(self) -> None:
        responses = GitHubCodeResponses()
        responses.files = [
            file_response(
                f"src/file_{index:03}.py",
                patch=None,
                additions=1,
                deletions=0,
                changes=1,
            )
            for index in range(101)
        ]
        source = create_source(responses)
        try:
            evidence = await source.get_changed_file_evidence(PULL_REQUEST)
        finally:
            await source.aclose()

        file_requests = [
            request
            for request in responses.requests
            if request.url.path.endswith("/pulls/42/files")
        ]
        self.assertEqual(len(file_requests), 2)
        self.assertEqual(len(evidence), 101)
        self.assertEqual(evidence[0].content.path, "src/file_000.py")
        self.assertEqual(evidence[-1].content.path, "src/file_100.py")

    async def test_empty_changed_files_differs_from_bounded_incomplete_result(self) -> None:
        empty = GitHubCodeResponses()
        empty.files = []
        source = create_source(empty, max_file_pages=1)
        try:
            self.assertEqual(
                await source.get_changed_file_evidence(PULL_REQUEST),
                (),
            )
        finally:
            await source.aclose()

        full_page = GitHubCodeResponses()
        full_page.files = [
            file_response(
                f"src/file_{index:03}.py",
                patch=None,
                additions=1,
                deletions=0,
                changes=1,
            )
            for index in range(100)
        ]
        source = create_source(full_page, max_file_pages=1)
        try:
            with self.assertRaises(GitHubIncompleteResultError):
                await source.get_changed_file_evidence(PULL_REQUEST)
        finally:
            await source.aclose()

    async def test_http_failure_taxonomy_is_sanitized(self) -> None:
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
                source = create_source(
                    lambda _request: httpx.Response(
                        status,
                        headers=headers,
                        json={"message": "token=raw-provider-secret"},
                    )
                )
                try:
                    with self.assertRaises(expected_error) as raised:
                        await source.get_commit_evidence(COMMIT_REQUEST)
                finally:
                    await source.aclose()
                self.assertNotIn("raw-provider-secret", str(raised.exception))

    async def test_timeout_and_network_failures_are_distinct_and_sanitized(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout-secret", request=request)

        def network_failure(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("network-secret", request=request)

        cases = (
            (
                timeout,
                GitHubTimeoutError,
                "timeout-secret",
            ),
            (
                network_failure,
                GitHubUpstreamUnavailableError,
                "network-secret",
            ),
        )
        for handler, expected_error, secret in cases:
            with self.subTest(error=expected_error.__name__):
                source = create_source(handler)
                try:
                    with self.assertRaises(expected_error) as raised:
                        await source.get_commit_evidence(COMMIT_REQUEST)
                finally:
                    await source.aclose()
                self.assertNotIn(secret, str(raised.exception))

    async def test_malformed_json_and_missing_provider_fields_are_rejected(self) -> None:
        responses = (
            httpx.Response(200, content=b"{"),
            httpx.Response(200, json={"sha": SHA}),
        )
        for response in responses:
            with self.subTest(response=response):
                source = create_source(lambda _request: response)
                try:
                    with self.assertRaises(GitHubInvalidResponseError):
                        await source.get_commit_evidence(COMMIT_REQUEST)
                finally:
                    await source.aclose()

    async def test_telemetry_is_bounded_and_excludes_inputs_or_patch_content(self) -> None:
        harness = create_telemetry_harness()
        source = create_source(GitHubCodeResponses(), telemetry=harness.telemetry)
        try:
            await source.get_changed_file_evidence(PULL_REQUEST)
            spans = harness.span_exporter.get_finished_spans()
            exported = repr(spans) + harness.log_stream.getvalue()
        finally:
            await source.aclose()
            harness.shutdown()

        self.assertEqual(spans[0].name, "connector.github.get_changed_file_evidence")
        self.assertEqual(spans[0].attributes["promptql.connector.result"], "success")
        for forbidden in ("octo-org", SHA, "services/checkout.py", "old value"):
            self.assertNotIn(forbidden, exported)

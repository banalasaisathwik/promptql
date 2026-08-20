from datetime import UTC, datetime
import unittest

from pydantic import ValidationError

from app.connectors.errors import FixtureNotFoundError
from app.connectors.github_code_fakes import (
    FIXTURE_COMMIT_REQUEST,
    FIXTURE_PULL_REQUEST,
    FakeGitHubCodeEvidenceSource,
)
from app.connectors.models import (
    GitHubCommitEvidenceRequest,
    GitHubPullRequestEvidenceRequest,
)
from app.investigations import (
    ChangedFileEvidenceContent,
    DiffHunkEvidenceContent,
    DiffLine,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    FileChangeType,
)


RETRIEVED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


class GitHubCodeEvidenceContractTests(unittest.IsolatedAsyncioTestCase):
    def test_commit_and_pull_request_requests_reject_invalid_identifiers(self) -> None:
        with self.assertRaises(ValidationError):
            GitHubCommitEvidenceRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                commit_sha="short-sha",
            )
        with self.assertRaises(ValidationError):
            GitHubPullRequestEvidenceRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                pr_number=0,
            )

    def test_changed_file_counts_and_rename_semantics_are_validated(self) -> None:
        base = {
            "repository_owner": "octo-org",
            "repository_name": "analytics",
            "pull_request_number": 42,
            "path": "new.py",
            "additions": 2,
            "deletions": 1,
            "changes": 3,
            "patch_available": False,
        }
        renamed = ChangedFileEvidenceContent(
            **base,
            change_type=FileChangeType.RENAMED,
            previous_path="old.py",
        )

        self.assertEqual(renamed.previous_path, "old.py")
        with self.assertRaises(ValidationError):
            ChangedFileEvidenceContent(
                **base,
                change_type=FileChangeType.RENAMED,
            )
        with self.assertRaises(ValidationError):
            ChangedFileEvidenceContent(
                **{**base, "changes": 99},
                change_type=FileChangeType.MODIFIED,
            )

    def test_diff_hunk_ranges_must_match_typed_lines(self) -> None:
        with self.assertRaises(ValidationError):
            DiffHunkEvidenceContent(
                repository_owner="octo-org",
                repository_name="analytics",
                pull_request_number=42,
                file_path="checkout.py",
                old_start=1,
                old_count=2,
                new_start=1,
                new_count=1,
                lines=(
                    DiffLine(kind="deletion", text="old"),
                    DiffLine(kind="addition", text="new"),
                ),
            )

    async def test_fake_returns_deterministic_v2_evidence(self) -> None:
        source = FakeGitHubCodeEvidenceSource()

        first = await source.get_commit_evidence(FIXTURE_COMMIT_REQUEST)
        second = await source.get_commit_evidence(FIXTURE_COMMIT_REQUEST)
        pull = await source.get_pull_request_evidence(FIXTURE_PULL_REQUEST)
        files = await source.get_changed_file_evidence(FIXTURE_PULL_REQUEST)

        self.assertEqual(first, second)
        self.assertIs(first.kind, EvidenceKind.COMMIT)
        self.assertIs(pull.kind, EvidenceKind.PULL_REQUEST)
        self.assertEqual(
            tuple(evidence.kind for evidence in files),
            (EvidenceKind.CHANGED_FILE, EvidenceKind.DIFF_HUNK),
        )
        for evidence in (first, pull, *files):
            self.assertIsInstance(evidence, Evidence)
            self.assertEqual(evidence.provenance.retrieved_at, RETRIEVED_AT)

    async def test_fake_unknown_identity_raises_typed_lookup_error(self) -> None:
        source = FakeGitHubCodeEvidenceSource()
        unknown = GitHubPullRequestEvidenceRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            pr_number=99,
        )

        with self.assertRaises(FixtureNotFoundError):
            await source.get_pull_request_evidence(unknown)

    def test_v2_evidence_still_rejects_raw_provider_fields(self) -> None:
        values = {
            "evidence_id": "github:test:pr:42",
            "source": "github",
            "kind": "pull_request",
            "provenance": EvidenceProvenance(
                source_reference="github:octo-org/analytics:pull:42",
                retrieved_at=RETRIEVED_AT,
            ).model_dump(),
            "content": {
                "content_type": "pull_request",
                "repository_owner": "octo-org",
                "repository_name": "analytics",
                "pull_request_number": 42,
                "title": "Guard checkout totals",
                "state": "open",
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
            },
            "raw_response": {"token": "secret"},
        }

        with self.assertRaises(ValidationError):
            Evidence.model_validate(values)

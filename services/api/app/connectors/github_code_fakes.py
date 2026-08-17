from collections.abc import Mapping
from datetime import UTC, datetime

from app.connectors.errors import FixtureNotFoundError
from app.connectors.models import (
    ConnectorSource,
    GitHubCommitEvidenceRequest,
    GitHubPullRequestEvidenceRequest,
)
from app.investigations import (
    ChangedFileEvidenceContent,
    CommitEvidenceContent,
    DiffHunkEvidenceContent,
    DiffLine,
    DiffLineKind,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    FileChangeType,
    PullRequestEvidenceContent,
)


FIXTURE_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
FIXTURE_SHA = "a" * 40
FIXTURE_PARENT_SHA = "b" * 40
FIXTURE_BASE_SHA = "c" * 40
FIXTURE_REPOSITORY_DIGEST = "849ca9275d431a5c"
FIXTURE_FILE_DIGEST = "562617adbcdb5398"
FIXTURE_COMMIT_REQUEST = GitHubCommitEvidenceRequest(
    repository_owner="octo-org",
    repository_name="analytics",
    commit_sha=FIXTURE_SHA,
)
FIXTURE_PULL_REQUEST = GitHubPullRequestEvidenceRequest(
    repository_owner="octo-org",
    repository_name="analytics",
    pr_number=42,
)


COMMIT_EVIDENCE_FIXTURES: Mapping[GitHubCommitEvidenceRequest, Evidence] = {
    FIXTURE_COMMIT_REQUEST: Evidence(
        evidence_id=f"github:{FIXTURE_REPOSITORY_DIGEST}:commit:{FIXTURE_SHA}",
        source=EvidenceSource.GITHUB,
        kind=EvidenceKind.COMMIT,
        provenance=EvidenceProvenance(
            source_reference=f"github:octo-org/analytics:commit:{FIXTURE_SHA}",
            observed_at=FIXTURE_TIME,
            retrieved_at=FIXTURE_TIME,
        ),
        content=CommitEvidenceContent(
            repository_owner="octo-org",
            repository_name="analytics",
            commit_sha=FIXTURE_SHA,
            message="Guard checkout totals",
            authored_at=FIXTURE_TIME,
            parent_shas=(FIXTURE_PARENT_SHA,),
        ),
    )
}


PULL_REQUEST_EVIDENCE_FIXTURES: Mapping[
    GitHubPullRequestEvidenceRequest,
    Evidence,
] = {
    FIXTURE_PULL_REQUEST: Evidence(
        evidence_id=f"github:{FIXTURE_REPOSITORY_DIGEST}:pr:42",
        source=EvidenceSource.GITHUB,
        kind=EvidenceKind.PULL_REQUEST,
        provenance=EvidenceProvenance(
            source_reference="github:octo-org/analytics:pull:42",
            observed_at=None,
            retrieved_at=FIXTURE_TIME,
        ),
        content=PullRequestEvidenceContent(
            repository_owner="octo-org",
            repository_name="analytics",
            pull_request_number=42,
            title="Guard checkout totals",
            state="merged",
            base_sha=FIXTURE_BASE_SHA,
            head_sha=FIXTURE_SHA,
            merge_commit_sha=FIXTURE_SHA,
        ),
    )
}


CHANGED_FILE_EVIDENCE_FIXTURES: Mapping[
    GitHubPullRequestEvidenceRequest,
    tuple[Evidence, ...],
] = {
    FIXTURE_PULL_REQUEST: (
        Evidence(
            evidence_id=(
                f"github:{FIXTURE_REPOSITORY_DIGEST}:pr:42:file:{FIXTURE_FILE_DIGEST}"
            ),
            source=EvidenceSource.GITHUB,
            kind=EvidenceKind.CHANGED_FILE,
            provenance=EvidenceProvenance(
                source_reference=(
                    "github:octo-org/analytics:pull:42:"
                    f"file-sha256:{FIXTURE_FILE_DIGEST}"
                ),
                observed_at=None,
                retrieved_at=FIXTURE_TIME,
            ),
            content=ChangedFileEvidenceContent(
                repository_owner="octo-org",
                repository_name="analytics",
                pull_request_number=42,
                path="services/checkout.py",
                change_type=FileChangeType.MODIFIED,
                additions=1,
                deletions=1,
                changes=2,
                patch_available=True,
            ),
        ),
        Evidence(
            evidence_id=(
                f"github:{FIXTURE_REPOSITORY_DIGEST}:pr:42:"
                f"hunk:{FIXTURE_FILE_DIGEST}:1"
            ),
            source=EvidenceSource.GITHUB,
            kind=EvidenceKind.DIFF_HUNK,
            provenance=EvidenceProvenance(
                source_reference=(
                    f"github:{FIXTURE_REPOSITORY_DIGEST}:pr:42:"
                    f"hunk:{FIXTURE_FILE_DIGEST}:1"
                ),
                observed_at=None,
                retrieved_at=FIXTURE_TIME,
            ),
            content=DiffHunkEvidenceContent(
                repository_owner="octo-org",
                repository_name="analytics",
                pull_request_number=42,
                file_path="services/checkout.py",
                old_start=10,
                old_count=1,
                new_start=10,
                new_count=1,
                lines=(
                    DiffLine(kind=DiffLineKind.DELETION, text="return total"),
                    DiffLine(kind=DiffLineKind.ADDITION, text="return total or 0"),
                ),
            ),
        ),
    )
}


class FakeGitHubCodeEvidenceSource:
    source = ConnectorSource.FAKE

    def __init__(
        self,
        commit_fixtures: Mapping[
            GitHubCommitEvidenceRequest,
            Evidence,
        ] = COMMIT_EVIDENCE_FIXTURES,
        pull_request_fixtures: Mapping[
            GitHubPullRequestEvidenceRequest,
            Evidence,
        ] = PULL_REQUEST_EVIDENCE_FIXTURES,
        changed_file_fixtures: Mapping[
            GitHubPullRequestEvidenceRequest,
            tuple[Evidence, ...],
        ] = CHANGED_FILE_EVIDENCE_FIXTURES,
    ) -> None:
        self._commit_fixtures = commit_fixtures
        self._pull_request_fixtures = pull_request_fixtures
        self._changed_file_fixtures = changed_file_fixtures

    async def get_commit_evidence(
        self,
        request: GitHubCommitEvidenceRequest,
    ) -> Evidence:
        try:
            return self._commit_fixtures[request]
        except KeyError:
            raise FixtureNotFoundError("github_code") from None

    async def get_pull_request_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
    ) -> Evidence:
        try:
            return self._pull_request_fixtures[request]
        except KeyError:
            raise FixtureNotFoundError("github_code") from None

    async def get_changed_file_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
    ) -> tuple[Evidence, ...]:
        try:
            return self._changed_file_fixtures[request]
        except KeyError:
            raise FixtureNotFoundError("github_code") from None

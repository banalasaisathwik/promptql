import unittest
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from app.investigations import (
    ChangedFileEvidenceContent,
    ChangedFileFact,
    CommitEvidenceContent,
    DeploymentEvidenceContent,
    DiffHunkEvidenceContent,
    DiffLine,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    FileChangeType,
    Hypothesis,
    InvestigationResult,
    JiraIssueEvidenceContent,
    MissingInformation,
    PullRequestEvidenceContent,
    StackFrameEvidenceContent,
)


RETRIEVED_AT = datetime(2026, 8, 17, 10, 18, tzinfo=UTC)


def provenance(
    source_reference: str = "github:acme/checkout:pr:42:file:services/checkout.py",
    *,
    observed_at: datetime | None = None,
    retrieved_at: datetime = RETRIEVED_AT,
) -> EvidenceProvenance:
    return EvidenceProvenance(
        source_reference=source_reference,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
    )


def changed_file_evidence(
    evidence_id: str = "evidence:changed-file",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source=EvidenceSource.GITHUB,
        kind=EvidenceKind.CHANGED_FILE,
        provenance=provenance(),
        content=ChangedFileEvidenceContent(
            repository_owner="acme",
            repository_name="checkout",
            pull_request_number=42,
            path="services/checkout.py",
            change_type=FileChangeType.MODIFIED,
            additions=4,
            deletions=2,
            changes=6,
            patch_available=True,
        ),
    )


def result_with(
    *,
    evidence: tuple[Evidence, ...] = (),
    facts: tuple[ChangedFileFact, ...] = (),
    hypotheses: tuple[Hypothesis, ...] = (),
    missing_information: tuple[MissingInformation, ...] = (),
) -> InvestigationResult:
    return InvestigationResult(
        evidence=evidence,
        facts=facts,
        hypotheses=hypotheses,
        missing_information=missing_information,
        recommended_actions=(),
    )


class EvidenceModelTests(unittest.TestCase):
    def test_valid_evidence_construction_preserves_provenance(self) -> None:
        observed_at = RETRIEVED_AT - timedelta(minutes=15)
        evidence = changed_file_evidence()
        evidence = Evidence.model_validate(
            {
                **evidence.model_dump(mode="json"),
                "provenance": {
                    **evidence.provenance.model_dump(mode="json"),
                    "observed_at": observed_at.isoformat(),
                },
            }
        )

        self.assertEqual(evidence.evidence_id, "evidence:changed-file")
        self.assertIs(evidence.source, EvidenceSource.GITHUB)
        self.assertEqual(evidence.provenance.observed_at, observed_at)
        self.assertEqual(evidence.provenance.retrieved_at, RETRIEVED_AT)

    def test_empty_evidence_id_is_rejected(self) -> None:
        values = changed_file_evidence().model_dump()
        values["evidence_id"] = "   "

        with self.assertRaises(ValidationError):
            Evidence.model_validate(values)

    def test_unknown_fields_and_raw_payloads_are_rejected(self) -> None:
        values = changed_file_evidence().model_dump(mode="json")
        values["raw_payload"] = {"authorization": "not-domain-data"}

        with self.assertRaises(ValidationError):
            Evidence.model_validate(values)

    def test_evidence_is_immutable(self) -> None:
        evidence = changed_file_evidence()

        with self.assertRaises(ValidationError):
            evidence.kind = EvidenceKind.COMMIT  # type: ignore[misc]

    def test_each_initial_source_kind_content_pair_is_valid(self) -> None:
        cases = (
            changed_file_evidence(),
            Evidence(
                evidence_id="evidence:commit",
                source="github",
                kind="commit",
                provenance=provenance(f"github:acme/checkout:commit:{'a' * 40}"),
                content=CommitEvidenceContent(
                    repository_owner="acme",
                    repository_name="checkout",
                    commit_sha="a" * 40,
                    message="Guard checkout totals",
                    parent_shas=("b" * 40,),
                ),
            ),
            Evidence(
                evidence_id="evidence:pull-request",
                source="github",
                kind="pull_request",
                provenance=provenance("github:acme/checkout:pull:42"),
                content=PullRequestEvidenceContent(
                    repository_owner="acme",
                    repository_name="checkout",
                    pull_request_number=42,
                    title="Guard checkout totals",
                    state="merged",
                    base_sha="b" * 40,
                    head_sha="a" * 40,
                    merge_commit_sha="c" * 40,
                ),
            ),
            Evidence(
                evidence_id="evidence:diff-hunk",
                source="github",
                kind="diff_hunk",
                provenance=provenance("github:acme/checkout:pull:42:hunk:1"),
                content=DiffHunkEvidenceContent(
                    repository_owner="acme",
                    repository_name="checkout",
                    pull_request_number=42,
                    file_path="services/checkout.py",
                    old_start=10,
                    old_count=1,
                    new_start=10,
                    new_count=1,
                    lines=(
                        DiffLine(kind="deletion", text="return total"),
                        DiffLine(kind="addition", text="return total or 0"),
                    ),
                ),
            ),
            Evidence(
                evidence_id="evidence:jira",
                source="jira",
                kind="jira_issue",
                provenance=provenance("jira:ENG-42"),
                content=JiraIssueEvidenceContent(
                    issue_key="ENG-42",
                    status="done",
                ),
            ),
            Evidence(
                evidence_id="evidence:stack",
                source="incident",
                kind="stack_frame",
                provenance=provenance("incident:checkout-500:stack:0"),
                content=StackFrameEvidenceContent(
                    service="checkout-api",
                    file_path="services/checkout.py",
                    function_name="create_order",
                    line_number=87,
                ),
            ),
            Evidence(
                evidence_id="evidence:deployment",
                source="deployment",
                kind="deployment",
                provenance=provenance("deployment:deploy-1042"),
                content=DeploymentEvidenceContent(
                    deployment_reference="deploy-1042",
                    environment="production",
                    revision="4f3a91c",
                ),
            ),
        )

        self.assertEqual(
            tuple(evidence.kind for evidence in cases),
            tuple(EvidenceKind),
        )

    def test_invalid_evidence_source_is_rejected(self) -> None:
        values = changed_file_evidence().model_dump()
        values["source"] = "sentry"

        with self.assertRaises(ValidationError):
            Evidence.model_validate(values)

    def test_kind_must_match_discriminated_content(self) -> None:
        values = changed_file_evidence().model_dump(mode="json")
        values["kind"] = "commit"

        with self.assertRaises(ValidationError):
            Evidence.model_validate(values)

    def test_unknown_content_discriminator_is_rejected(self) -> None:
        values = changed_file_evidence().model_dump(mode="json")
        values["content"] = {
            "content_type": "raw_provider_response",
            "value": "unvalidated",
        }

        with self.assertRaises(ValidationError):
            Evidence.model_validate(values)

    def test_source_must_match_the_current_kind_semantics(self) -> None:
        values = changed_file_evidence().model_dump(mode="json")
        values["source"] = "jira"

        with self.assertRaises(ValidationError):
            Evidence.model_validate(values)

    def test_timezone_aware_timestamps_are_required(self) -> None:
        naive_timestamp = datetime(2026, 8, 17, 10, 18)

        with self.assertRaises(ValidationError):
            provenance(retrieved_at=naive_timestamp)
        with self.assertRaises(ValidationError):
            provenance(observed_at=naive_timestamp)

    def test_clock_skew_does_not_invalidate_truthful_provenance(self) -> None:
        source_clock_time = RETRIEVED_AT + timedelta(seconds=2)


        value = provenance(observed_at=source_clock_time)

        self.assertGreater(value.observed_at, value.retrieved_at)

    def test_duplicate_evidence_ids_are_rejected_in_result(self) -> None:
        first = changed_file_evidence()
        second = changed_file_evidence()

        with self.assertRaises(ValidationError):
            result_with(evidence=(first, second))

    def test_fact_reference_to_existing_evidence_is_accepted(self) -> None:
        evidence = changed_file_evidence()
        fact = ChangedFileFact(
            fact_id="fact:changed-file",
            evidence_reference_ids=(evidence.evidence_id,),
            path="services/checkout.py",
            change_type="modified",
        )

        result = result_with(evidence=(evidence,), facts=(fact,))

        self.assertEqual(result.facts[0].evidence_reference_ids, (evidence.evidence_id,))

    def test_fact_reference_to_nonexistent_evidence_is_rejected(self) -> None:
        fact = ChangedFileFact(
            fact_id="fact:changed-file",
            evidence_reference_ids=("evidence:not-present",),
            path="services/checkout.py",
            change_type="modified",
        )

        with self.assertRaises(ValidationError):
            result_with(facts=(fact,))

    def test_hypothesis_evidence_references_must_resolve(self) -> None:
        evidence = changed_file_evidence()
        hypothesis = Hypothesis(
            hypothesis_id="hypothesis:recent-change",
            code="recent_checkout_change",
            claim="A recent checkout change may have caused the incident.",
            evidence_reference_ids=(evidence.evidence_id,),
            confidence="medium",
            grounding_status="supported",
        )

        accepted = result_with(evidence=(evidence,), hypotheses=(hypothesis,))
        self.assertEqual(accepted.hypotheses, (hypothesis,))

        with self.assertRaises(ValidationError):
            result_with(hypotheses=(hypothesis,))

    def test_result_may_contain_evidence_without_hypotheses(self) -> None:
        result = result_with(evidence=(changed_file_evidence(),))

        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.hypotheses, ())

    def test_missing_information_requires_no_fake_evidence(self) -> None:
        missing = MissingInformation(
            missing_information_id="missing:deployment-map",
            kind="deployment_mapping_unavailable",
            detail="No deployment record was available.",
        )


        result = result_with(missing_information=(missing,))

        self.assertEqual(result.evidence, ())
        self.assertEqual(result.missing_information, (missing,))


if __name__ == "__main__":
    unittest.main()

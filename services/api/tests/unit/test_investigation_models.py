import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from app.investigations import (
    ChangedFileFact,
    DeploymentFact,
    FileChangeType,
    Hypothesis,
    HypothesisConfidence,
    HypothesisGroundingStatus,
    InvestigationRequest,
    InvestigationResult,
    MissingInformation,
    MissingInformationKind,
    RecommendedAction,
    RecommendedActionCode,
    StackFrameFact,
)


def changed_file_fact(fact_id: str = "fact:file-change") -> ChangedFileFact:
    return ChangedFileFact(
        fact_id=fact_id,
        evidence_reference_ids=("evidence:github-diff",),
        path="services/checkout.py",
        change_type=FileChangeType.MODIFIED,
    )


def supported_hypothesis(
    hypothesis_id: str = "hypothesis:checkout-change",
    fact_id: str = "fact:file-change",
) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        code="recent_checkout_change",
        claim="A recent checkout change may have caused the incident.",
        related_fact_ids=(fact_id,),
        evidence_reference_ids=(),
        confidence=HypothesisConfidence.MEDIUM,
        grounding_status=HypothesisGroundingStatus.SUPPORTED,
    )


def missing_timeline(
    missing_information_id: str = "missing:timeline",
) -> MissingInformation:
    return MissingInformation(
        missing_information_id=missing_information_id,
        kind=MissingInformationKind.INCIDENT_TIMELINE_INCOMPLETE,
        detail="The first failing request timestamp is unavailable.",
    )


class InvestigationModelTests(unittest.TestCase):
    def test_valid_investigation_request(self) -> None:
        request = InvestigationRequest(
            repository_owner="acme",
            repository_name="checkout",
            incident_summary="Checkout requests started returning HTTP 500.",
            incident_started_at=datetime(2026, 8, 16, 10, 30, tzinfo=UTC),
            service="checkout-api",
            environment="production",
        )

        self.assertEqual(request.repository_name, "checkout")
        self.assertEqual(request.environment, "production")

    def test_empty_required_request_strings_are_rejected(self) -> None:
        required_fields = (
            "repository_owner",
            "repository_name",
            "incident_summary",
        )
        valid_values = {
            "repository_owner": "acme",
            "repository_name": "checkout",
            "incident_summary": "Checkout is failing.",
        }

        for field_name in required_fields:
            with self.subTest(field_name=field_name):
                values = {**valid_values, field_name: "   "}
                with self.assertRaises(ValidationError):
                    InvestigationRequest.model_validate(values)

    def test_unexpected_request_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            InvestigationRequest.model_validate(
                {
                    "repository_owner": "acme",
                    "repository_name": "checkout",
                    "incident_summary": "Checkout is failing.",
                    "planner_prompt": "Investigate everything",
                }
            )

    def test_contracts_are_immutable(self) -> None:
        request = InvestigationRequest(
            repository_owner="acme",
            repository_name="checkout",
            incident_summary="Checkout is failing.",
        )

        with self.assertRaises(ValidationError):
            request.incident_summary = "Changed after validation."  # type: ignore[misc]

    def test_valid_typed_facts_preserve_machine_readable_meaning(self) -> None:
        facts = (
            changed_file_fact(),
            DeploymentFact(
                fact_id="fact:deployment",
                evidence_reference_ids=("evidence:deployment",),
                deployment_reference="deploy-1042",
                environment="production",
                deployed_at=datetime(2026, 8, 16, 10, 20, tzinfo=UTC),
                revision="4f3a91c",
            ),
            StackFrameFact(
                fact_id="fact:stack-frame",
                evidence_reference_ids=("evidence:incident-stack",),
                file_path="services/checkout.py",
                function_name="create_order",
                line_number=87,
            ),
        )


        parsed = InvestigationResult.model_validate(
            {
                "facts": [fact.model_dump(mode="json") for fact in facts],
                "hypotheses": [],
                "missing_information": [],
                "recommended_actions": [],
            }
        )

        self.assertIsInstance(parsed.facts[0], ChangedFileFact)
        self.assertIsInstance(parsed.facts[1], DeploymentFact)
        self.assertIsInstance(parsed.facts[2], StackFrameFact)

    def test_invalid_fact_specific_values_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ChangedFileFact(
                fact_id="fact:file-change",
                evidence_reference_ids=("evidence:github-diff",),
                path="services/checkout.py",
                change_type="rewritten",
            )
        with self.assertRaises(ValidationError):
            StackFrameFact(
                fact_id="fact:stack-frame",
                evidence_reference_ids=("evidence:incident-stack",),
                file_path="services/checkout.py",
                function_name="create_order",
                line_number=0,
            )
        with self.assertRaises(ValidationError):
            ChangedFileFact(
                fact_id="fact:file-change",
                evidence_reference_ids=(),
                path="services/checkout.py",
                change_type="modified",
            )

    def test_duplicate_fact_evidence_references_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ChangedFileFact(
                fact_id="fact:file-change",
                evidence_reference_ids=(
                    "evidence:github-diff",
                    "evidence:github-diff",
                ),
                path="services/checkout.py",
                change_type="modified",
            )

    def test_hypothesis_with_valid_fact_reference_is_accepted(self) -> None:
        result = InvestigationResult(
            facts=(changed_file_fact(),),
            hypotheses=(supported_hypothesis(),),
            missing_information=(),
            recommended_actions=(),
        )

        self.assertEqual(result.hypotheses[0].confidence, HypothesisConfidence.MEDIUM)

    def test_missing_hypothesis_fact_reference_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            InvestigationResult(
                facts=(),
                hypotheses=(supported_hypothesis(),),
                missing_information=(),
                recommended_actions=(),
            )

    def test_grounded_hypothesis_requires_a_fact_or_evidence_reference(self) -> None:
        with self.assertRaises(ValidationError):
            Hypothesis(
                hypothesis_id="hypothesis:checkout-change",
                code="recent_checkout_change",
                claim="A recent checkout change may have caused the incident.",
                confidence="high",
                grounding_status="supported",
            )

    def test_categorical_confidence_rejects_unvalidated_probability(self) -> None:
        values = supported_hypothesis().model_dump()
        values["confidence"] = 0.93

        with self.assertRaises(ValidationError):
            Hypothesis.model_validate(values)

    def test_missing_information_uses_a_bounded_code(self) -> None:
        item = missing_timeline()
        self.assertIs(item.kind, MissingInformationKind.INCIDENT_TIMELINE_INCOMPLETE)

        with self.assertRaises(ValidationError):
            MissingInformation(
                missing_information_id="missing:unknown",
                kind="ask_whatever",
            )

    def test_valid_result_checks_action_and_missing_information_references(self) -> None:
        result = InvestigationResult(
            facts=(changed_file_fact(),),
            hypotheses=(supported_hypothesis(),),
            missing_information=(missing_timeline(),),
            recommended_actions=(
                RecommendedAction(
                    action_id="action:collect-timeline",
                    action_code=RecommendedActionCode.COLLECT_INCIDENT_TIMELINE,
                    message="Collect the first failing request timestamp.",
                    related_missing_information_ids=("missing:timeline",),
                    related_hypothesis_ids=("hypothesis:checkout-change",),
                ),
            ),
        )

        self.assertEqual(len(result.facts), 1)
        self.assertEqual(len(result.recommended_actions), 1)

    def test_duplicate_entity_identifiers_are_rejected_across_the_result(self) -> None:
        with self.assertRaises(ValidationError):
            InvestigationResult(
                facts=(changed_file_fact("shared:id"),),
                hypotheses=(supported_hypothesis("shared:id", "shared:id"),),
                missing_information=(),
                recommended_actions=(),
            )

    def test_broken_missing_information_and_action_references_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            InvestigationResult(
                facts=(),
                hypotheses=(),
                missing_information=(
                    MissingInformation(
                        missing_information_id="missing:timeline",
                        kind="incident_timeline_incomplete",
                        related_fact_ids=("fact:not-present",),
                    ),
                ),
                recommended_actions=(),
            )

        with self.assertRaises(ValidationError):
            InvestigationResult(
                facts=(),
                hypotheses=(),
                missing_information=(),
                recommended_actions=(
                    RecommendedAction(
                        action_id="action:collect-timeline",
                        action_code="collect_incident_timeline",
                        message="Collect the incident timeline.",
                        related_missing_information_ids=("missing:not-present",),
                    ),
                ),
            )

        with self.assertRaises(ValidationError):
            InvestigationResult(
                facts=(),
                hypotheses=(),
                missing_information=(),
                recommended_actions=(
                    RecommendedAction(
                        action_id="action:inspect-change",
                        action_code="retrieve_source_data",
                        message="Inspect the relevant code change.",
                        related_fact_ids=("fact:not-present",),
                    ),
                ),
            )

    def test_insufficient_evidence_needs_no_invented_hypothesis(self) -> None:
        result = InvestigationResult(
            facts=(),
            hypotheses=(),
            missing_information=(missing_timeline(),),
            recommended_actions=(
                RecommendedAction(
                    action_id="action:collect-timeline",
                    action_code="collect_incident_timeline",
                    message="Collect the incident timeline.",
                    related_missing_information_ids=("missing:timeline",),
                ),
            ),
        )

        self.assertEqual(result.facts, ())
        self.assertEqual(result.hypotheses, ())
        self.assertEqual(len(result.missing_information), 1)


if __name__ == "__main__":
    unittest.main()

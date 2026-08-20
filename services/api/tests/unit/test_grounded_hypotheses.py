import unittest

from app.explanations import FakeLLMClient, LLMProviderError, LLMProviderFailureCategory
from app.investigations import (
    ChangedFileFact,
    ChangedFileMatchesFailureFileFact,
    DeploymentPrecededIncidentFact,
    InvestigationRequest,
    MissingInformation,
    MissingInformationKind,
)
from app.investigations.replanning import AdaptiveInvestigationState, ContinuationReason
from app.investigations.hypotheses import (
    CandidateHypothesis,
    DeterministicHypothesisValidator,
    HypothesisGenerationError,
    HypothesisGenerationFailureCode,
    HypothesisGenerationInput,
    HypothesisKind,
    GroundedTerminationReason,
    GroundingRenderError,
    HypothesisValidationFailureCode,
    MAX_HYPOTHESES,
    TypedLLMHypothesisGenerator,
    build_hypothesis_generation_input,
    render_grounded_result,
    render_missing_information,
)


def _facts():
    return (
        ChangedFileFact(
            fact_id="F_CHANGED", evidence_reference_ids=("E_CHANGED",),
            path="checkout.py", change_type="modified",
        ),
        ChangedFileMatchesFailureFileFact(
            fact_id="F_FAILURE_FILE", evidence_reference_ids=("E_FAILURE",),
            file_path="checkout.py",
        ),
        DeploymentPrecededIncidentFact(
            fact_id="F_DEPLOYMENT", evidence_reference_ids=("E_DEPLOYMENT",),
            deployment_reference="deploy-42", incident_reference="incident-42",
        ),
    )


def _candidate(*supporting_fact_ids: str, subject: str = "checkout.py"):
    return CandidateHypothesis(
        hypothesis_id="H_CODE_CHANGE",
        kind=HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED,
        subject=subject,
        supporting_fact_ids=supporting_fact_ids,
    )


class HypothesisGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_input_uses_completed_state_facts_not_raw_evidence(self):
        generation_input = build_hypothesis_generation_input(
            InvestigationRequest(
                repository_owner="octo-org", repository_name="analytics",
                question="Investigate checkout failures.",
            ),
            AdaptiveInvestigationState(
                rounds=(), evidence=(), facts=_facts(), missing_information=(),
                action_history=(), remaining_tool_calls=0,
                continuation_reason=ContinuationReason.COMPLETE,
            ),
        )

        self.assertEqual(
            [fact.fact_id for fact in generation_input.facts],
            ["F_CHANGED", "F_DEPLOYMENT", "F_FAILURE_FILE"],
        )

    async def test_typed_candidate_is_bounded_versioned_and_not_trusted(self):
        generator = TypedLLMHypothesisGenerator(
            FakeLLMClient(typed_output={"candidates": [_candidate("F_CHANGED", "F_FAILURE_FILE").model_dump(mode="json")]})
        )

        generated = await generator.generate(
            HypothesisGenerationInput(investigation_goal="Investigate checkout failures.", facts=_facts())
        )

        self.assertEqual(len(generated.candidates), 1)
        self.assertEqual(generated.metadata.prompt_version, "v2.17.1")
        self.assertEqual(generated.metadata.provider, "fake")

    async def test_zero_candidates_and_malformed_or_provider_failures_are_distinct(self):
        prompt_input = HypothesisGenerationInput(investigation_goal="Investigate checkout failures.", facts=_facts())
        self.assertEqual((await TypedLLMHypothesisGenerator(FakeLLMClient(typed_output={"candidates": []})).generate(prompt_input)).candidates, ())

        class ProviderFailure:
            provider = FakeLLMClient.provider
            model = "failure"

            async def generate_typed(self, request):
                raise LLMProviderError(LLMProviderFailureCategory.CONNECTION)

        for client, expected in (
            (ProviderFailure(), HypothesisGenerationFailureCode.PROVIDER_FAILURE),
            (FakeLLMClient(typed_output="raw causal prose"), HypothesisGenerationFailureCode.CANDIDATE_SCHEMA_INVALID),
            (FakeLLMClient(typed_output={"candidates": [{"kind": "redis_definitely_caused_outage"}]}), HypothesisGenerationFailureCode.CANDIDATE_SCHEMA_INVALID),
            (FakeLLMClient(typed_output={"candidates": [_candidate("F_CHANGED").model_dump(mode="json")] * (MAX_HYPOTHESES + 1)}), HypothesisGenerationFailureCode.CANDIDATE_SCHEMA_INVALID),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(HypothesisGenerationError) as raised:
                    await TypedLLMHypothesisGenerator(client).generate(prompt_input)
                self.assertEqual(raised.exception.code, expected)

    async def test_prompt_forbids_authoritative_prose_and_numeric_confidence(self):
        class RecordingClient:
            provider = FakeLLMClient.provider
            model = "recording"
            request = None

            async def generate_typed(self, request):
                self.request = request
                return {"output": {"candidates": []}}

        client = RecordingClient()
        await TypedLLMHypothesisGenerator(client).generate(
            HypothesisGenerationInput(investigation_goal="Investigate checkout failures.", facts=_facts())
        )
        self.assertIn("never authoritative Facts", client.request.system_instructions)
        self.assertIn("confidence", client.request.system_instructions)
        self.assertEqual(client.request.output_model.__name__, "HypothesisGenerationOutput")


class DeterministicHypothesisValidatorTests(unittest.TestCase):
    def test_matching_code_and_failure_fact_relationships_are_accepted(self):
        result = DeterministicHypothesisValidator().validate(
            (_candidate("F_CHANGED", "F_FAILURE_FILE"),), _facts()
        )
        self.assertEqual([item.hypothesis_id for item in result.accepted_hypotheses], ["H_CODE_CHANGE"])
        self.assertEqual(result.rejected_candidates, ())

    def test_existing_but_irrelevant_or_mismatched_facts_are_rejected(self):
        validator = DeterministicHypothesisValidator()
        cases = (
            (_candidate("F_DEPLOYMENT"), HypothesisValidationFailureCode.MISSING_REQUIRED_SUPPORT),
            (_candidate("F_CHANGED"), HypothesisValidationFailureCode.MISSING_REQUIRED_SUPPORT),
            (_candidate("F_CHANGED", "F_FAILURE_FILE", subject="payments.py"), HypothesisValidationFailureCode.ENTITY_MISMATCH),
            (_candidate("F_CHANGED", "F_CHANGED"), HypothesisValidationFailureCode.DUPLICATE_FACT_REFERENCE),
            (_candidate("F_UNKNOWN"), HypothesisValidationFailureCode.UNKNOWN_SUPPORTING_FACT),
        )
        for candidate, expected in cases:
            with self.subTest(expected=expected):
                result = validator.validate((candidate,), _facts())
                self.assertEqual(result.rejected_candidates[0].reason, expected)

    def test_empty_candidate_list_is_a_valid_deterministic_result(self):
        result = DeterministicHypothesisValidator().validate((), _facts())
        self.assertEqual(result.accepted_hypotheses, ())
        self.assertEqual(result.rejected_candidates, ())


class GroundedRenderingTests(unittest.TestCase):
    def test_supported_hypothesis_uses_only_validated_facts(self):
        validated = DeterministicHypothesisValidator().validate(
            (_candidate("F_CHANGED", "F_FAILURE_FILE"),), _facts()
        ).accepted_hypotheses

        result = render_grounded_result(
            _facts(), validated, (), GroundedTerminationReason.COMPLETED
        )

        self.assertEqual(
            result.supported_hypotheses[0].statement,
            "Changes associated with checkout.py may have contributed to the incident.",
        )
        self.assertEqual(result.key_fact_ids, ("F_CHANGED", "F_FAILURE_FILE"))

    def test_same_structured_input_is_deterministic(self):
        validated = DeterministicHypothesisValidator().validate(
            (_candidate("F_CHANGED", "F_FAILURE_FILE"),), _facts()
        ).accepted_hypotheses
        first = render_grounded_result(
            _facts(), validated, (), GroundedTerminationReason.COMPLETED
        )
        second = render_grounded_result(
            _facts(), validated, (), GroundedTerminationReason.COMPLETED
        )
        self.assertEqual(first, second)

    def test_no_validated_hypothesis_is_insufficient_evidence(self):
        result = render_grounded_result(
            _facts(), (), (), GroundedTerminationReason.NO_PROGRESS
        )
        self.assertEqual(result.supported_hypotheses, ())
        self.assertIn("not sufficient", result.summary)

    def test_budget_and_provider_termination_reasons_render_different_safe_summaries(self):
        budget_result = render_grounded_result(
            _facts(), (), (), GroundedTerminationReason.BUDGET_EXHAUSTED
        )
        provider_result = render_grounded_result(
            _facts(), (), (), GroundedTerminationReason.PROVIDER_FAILURE
        )

        self.assertIn("tool-call budget was exhausted", budget_result.summary)
        self.assertIn("hypothesis generation was unavailable", provider_result.summary)
        self.assertNotEqual(budget_result.summary, provider_result.summary)

    def test_missing_information_uses_its_deterministic_detail(self):
        missing = MissingInformation(
            missing_information_id="M_DEPLOYMENT",
            kind=MissingInformationKind.DEPLOYMENT_MAPPING_UNAVAILABLE,
            detail="Deployment evidence was unavailable.",
        )

        self.assertEqual(
            render_missing_information(missing),
            "Deployment evidence was unavailable.",
        )

    def test_candidate_cannot_cross_the_rendering_boundary(self):
        with self.assertRaises(GroundingRenderError):
            render_grounded_result(
                _facts(),
                (_candidate("F_CHANGED", "F_FAILURE_FILE"),),
                (),
                GroundedTerminationReason.COMPLETED,
            )

    def test_unknown_fact_id_cannot_be_rendered(self):
        validated = DeterministicHypothesisValidator().validate(
            (_candidate("F_CHANGED", "F_FAILURE_FILE"),), _facts()
        ).accepted_hypotheses[0].model_copy(
            update={"supporting_fact_ids": ("F_UNKNOWN",)}
        )
        with self.assertRaises(GroundingRenderError):
            render_grounded_result(
                _facts(), (validated,), (), GroundedTerminationReason.COMPLETED
            )


if __name__ == "__main__":
    unittest.main()

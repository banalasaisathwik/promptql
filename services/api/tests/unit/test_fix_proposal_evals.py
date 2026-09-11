import unittest

from app.evals.fix_proposal.cases import build_fix_proposal_eval_dataset
from app.evals.fix_proposal.evaluation import (
    aggregate_fix_proposal_observations,
    build_fixture_candidate,
    build_proposal_input,
    observe_fix_proposal_case,
    unsupported_identifiers,
)
from app.evals.fix_proposal.models import FixProposalEvalCategory
from app.evals.fix_proposal.runner import _FixtureFakeClient
from app.explanations import LLMProviderName


class FixProposalEvalDatasetTests(unittest.TestCase):
    def test_dataset_covers_the_four_required_categories_plus_abstention(self):
        dataset = build_fix_proposal_eval_dataset()

        categories = {case.category for case in dataset.cases}
        self.assertEqual(
            categories,
            {
                FixProposalEvalCategory.KEY_ERROR,
                FixProposalEvalCategory.NONE_DEREFERENCE,
                FixProposalEvalCategory.INPUT_BOUNDARY,
                FixProposalEvalCategory.CONFIGURATION_MISMATCH,
                FixProposalEvalCategory.INSUFFICIENT_CONTEXT,
            },
        )

    def test_every_case_produces_a_real_fix_proposal_input(self):
        dataset = build_fix_proposal_eval_dataset()
        for case in dataset.cases:
            with self.subTest(case_id=case.case_id):
                proposal_input = build_proposal_input(case)
                self.assertIsNotNone(proposal_input)
                assert proposal_input is not None
                self.assertEqual(proposal_input.finding.file_path, case.expected_file_path)


class UnsupportedIdentifierHeuristicTests(unittest.TestCase):
    def test_string_literal_words_are_not_flagged(self):
        original = "def f(x):\n    return x\n"
        corrected = 'def f(x):\n    raise ValueError("quantity is required")\n'

        self.assertEqual(unsupported_identifiers(original, corrected), ())

    def test_stdlib_attribute_calls_are_not_flagged(self):
        original = "def f(payload):\n    return payload['quantity']\n"
        corrected = "def f(payload):\n    return payload.get('quantity')\n"

        self.assertEqual(unsupported_identifiers(original, corrected), ())

    def test_a_genuinely_invented_helper_is_flagged(self):
        original = "def f(x):\n    return x\n"
        corrected = "def f(x):\n    return sanitize_totally_invented_helper(x)\n"

        self.assertIn("sanitize_totally_invented_helper", unsupported_identifiers(original, corrected))


class FixProposalEvalFakeDryRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_candidates_score_well_and_abstention_case_abstains(self):
        dataset = build_fix_proposal_eval_dataset()
        client = _FixtureFakeClient(dataset)

        observations = [
            await observe_fix_proposal_case(
                case,
                sample_number=1,
                provider=LLMProviderName.FAKE,
                requested_model=client.model,
                client=client,
            )
            for case in dataset.cases
        ]

        by_category = {item.category: item for item in observations}
        for category in (
            FixProposalEvalCategory.KEY_ERROR,
            FixProposalEvalCategory.NONE_DEREFERENCE,
            FixProposalEvalCategory.INPUT_BOUNDARY,
            FixProposalEvalCategory.CONFIGURATION_MISMATCH,
        ):
            observation = by_category[category]
            self.assertTrue(observation.accepted, observation)
            self.assertTrue(observation.fix_available_when_expected)
            self.assertTrue(observation.correct_file)
            self.assertTrue(observation.failure_mechanism_grounded)
            self.assertEqual(observation.unsupported_identifier_count, 0)

        abstained = by_category[FixProposalEvalCategory.INSUFFICIENT_CONTEXT]
        self.assertFalse(abstained.candidate_returned)
        self.assertTrue(abstained.abstains_when_fix_not_grounded)

        metrics = aggregate_fix_proposal_observations(observations, planned_samples=len(observations))
        self.assertEqual(metrics.fix_available_when_expected.rate, 1.0)
        self.assertEqual(metrics.abstains_when_fix_not_grounded.rate, 1.0)
        self.assertEqual(metrics.unsupported_identifier_rate, 0.0)

    async def test_a_diff_marker_artifact_candidate_is_rejected_and_scored_accordingly(self):
        dataset = build_fix_proposal_eval_dataset()
        case = next(
            item
            for item in dataset.cases
            if item.category is FixProposalEvalCategory.KEY_ERROR
        )
        proposal_input = build_proposal_input(case)
        assert proposal_input is not None
        good_candidate = build_fixture_candidate(case, proposal_input)
        assert good_candidate is not None
        broken_candidate = good_candidate.model_copy(
            update={"corrected_hunk": "-    remaining = stock[0]"}
        )

        class _BrokenClient:
            provider = LLMProviderName.FAKE
            model = "deterministic-fake-v1"

            async def generate_typed(self, request):
                from app.explanations import LLMStructuredResponse
                from app.investigations.code_diagnosis import FixProposalOutput

                return LLMStructuredResponse(
                    output=FixProposalOutput(candidate=broken_candidate).model_dump(
                        mode="json"
                    )
                )

        observation = await observe_fix_proposal_case(
            case,
            sample_number=1,
            provider=LLMProviderName.FAKE,
            requested_model="deterministic-fake-v1",
            client=_BrokenClient(),
        )

        self.assertTrue(observation.candidate_returned)
        self.assertFalse(observation.accepted)
        self.assertEqual(observation.rejection_reason.value, "diff_marker_artifact")
        self.assertFalse(observation.correct_hunk_or_location)
        self.assertFalse(observation.fix_available_when_expected)


if __name__ == "__main__":
    unittest.main()

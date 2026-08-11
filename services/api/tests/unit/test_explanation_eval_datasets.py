import unittest

from app.evals.cases import (
    DATASET_VERSION,
    DEVELOPMENT_DATASET_ID,
    ExplanationEvalDataset,
    HOLDOUT_DATASET_ID,
    build_development_dataset,
    build_holdout_dataset,
    validate_eval_dataset,
)
from app.evals.models import EvalDatasetSplit
from app.explanations import required_explanation_claims
from app.explanations.instructions import PROMPT_ID, PROMPT_VERSION
from app.policy import evaluate_merge_readiness


DEVELOPMENT_CASE_IDS = (
    "ready",
    "draft",
    "failed-ci",
    "pending-ci",
    "missing-approval",
    "changes-requested",
    "merge-conflict",
    "jira-incomplete",
    "unknown-mergeability",
    "draft-and-merge-conflict",
    "multiple-blockers-and-actions",
)

HOLDOUT_CASE_IDS = (
    "closed-unmerged",
    "missing-jira-link",
    "required-checks-unknown",
    "reviews-unknown",
    "pending-ci-and-jira-blocker",
    "closed-failed-ci-and-jira-incomplete",
)


class ExplanationEvalDatasetTests(unittest.IsolatedAsyncioTestCase):
    async def test_stable_versioned_datasets_are_separate_and_ordered(self) -> None:
        development = await build_development_dataset()
        holdout = await build_holdout_dataset()

        self.assertEqual(development.dataset_id, DEVELOPMENT_DATASET_ID)
        self.assertEqual(holdout.dataset_id, HOLDOUT_DATASET_ID)
        self.assertEqual(development.dataset_version, DATASET_VERSION)
        self.assertEqual(holdout.dataset_version, DATASET_VERSION)
        self.assertIs(development.split, EvalDatasetSplit.DEVELOPMENT)
        self.assertIs(holdout.split, EvalDatasetSplit.HOLDOUT)
        self.assertEqual(
            tuple(case.case_id for case in development.cases),
            DEVELOPMENT_CASE_IDS,
        )
        self.assertEqual(
            tuple(case.case_id for case in holdout.cases),
            HOLDOUT_CASE_IDS,
        )
        self.assertTrue(set(DEVELOPMENT_CASE_IDS).isdisjoint(HOLDOUT_CASE_IDS))
        self.assertEqual(len(set(DEVELOPMENT_CASE_IDS)), len(DEVELOPMENT_CASE_IDS))
        self.assertEqual(len(set(HOLDOUT_CASE_IDS)), len(HOLDOUT_CASE_IDS))

    async def test_ground_truth_is_derived_and_deterministic(self) -> None:
        first_development = await build_development_dataset()
        second_development = await build_development_dataset()
        first_holdout = await build_holdout_dataset()
        second_holdout = await build_holdout_dataset()

        def expected(dataset):
            return tuple(
                required_explanation_claims(
                    evaluate_merge_readiness(case.github, case.jira)
                )
                for case in dataset.cases
            )

        self.assertEqual(expected(first_development), expected(second_development))
        self.assertEqual(expected(first_holdout), expected(second_holdout))

    async def test_dataset_and_prompt_identity_exclude_connector_identity(self) -> None:
        development = await build_development_dataset()
        holdout = await build_holdout_dataset()
        controlled_identity = " ".join(
            (
                PROMPT_ID,
                PROMPT_VERSION,
                development.dataset_id,
                development.dataset_version,
                holdout.dataset_id,
                holdout.dataset_version,
                *(case.case_id for case in development.cases),
                *(case.case_id for case in holdout.cases),
            )
        ).lower()

        for forbidden in ("acme", "analytics", "eng-", "github", "jira-issue"):
            self.assertNotIn(forbidden, controlled_identity)

    async def test_invalid_version_and_duplicate_case_ids_are_rejected(self) -> None:
        development = await build_development_dataset()
        wrong_version = ExplanationEvalDataset(
            dataset_id=development.dataset_id,
            dataset_version="v2",
            split=development.split,
            cases=development.cases,
        )
        duplicate_ids = ExplanationEvalDataset(
            dataset_id=development.dataset_id,
            dataset_version=development.dataset_version,
            split=development.split,
            cases=(development.cases[0], development.cases[0]),
        )

        with self.assertRaises(ValueError):
            validate_eval_dataset(wrong_version)
        with self.assertRaises(ValueError):
            validate_eval_dataset(duplicate_ids)


if __name__ == "__main__":
    unittest.main()

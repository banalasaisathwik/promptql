import unittest

from app.explanations import FakeLLMClient
from app.investigations.grounding_extraction import (
    GroundingExtractionInput,
    TypedGroundingExtractor,
)
from app.investigations.models import has_required_grounding_reference


class GroundingExtractionFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_text_produces_a_complete_groundable_extraction(self) -> None:
        extracted = await TypedGroundingExtractor(FakeLLMClient()).extract(
            GroundingExtractionInput(
                description=(
                    "PR 42 in octo-org/analytics, deployment 52, checkout "
                    "throwing errors"
                )
            )
        )

        self.assertEqual(extracted.repository_owner, "octo-org")
        self.assertEqual(extracted.repository_name, "analytics")
        self.assertEqual(extracted.pull_request_number, 42)
        self.assertEqual(extracted.deployment_reference, "deployment:52")
        self.assertIsNone(extracted.incident_reference)
        self.assertTrue(
            has_required_grounding_reference(
                extracted.incident_reference,
                extracted.pull_request_number,
                extracted.deployment_reference,
            )
        )

    async def test_ambiguous_text_with_no_anchor_needs_clarification(self) -> None:
        extracted = await TypedGroundingExtractor(FakeLLMClient()).extract(
            GroundingExtractionInput(
                description="Checkout is throwing errors after a deploy went out."
            )
        )

        self.assertIsNone(extracted.repository_owner)
        self.assertIsNone(extracted.incident_reference)
        self.assertIsNone(extracted.pull_request_number)
        self.assertIsNone(extracted.deployment_reference)
        self.assertFalse(
            has_required_grounding_reference(
                extracted.incident_reference,
                extracted.pull_request_number,
                extracted.deployment_reference,
            )
        )

    async def test_known_fields_are_echoed_without_re_derivation(self) -> None:
        extracted = await TypedGroundingExtractor(FakeLLMClient()).extract(
            GroundingExtractionInput(
                description="Checkout is throwing errors.",
                known_repository_owner="octo-org",
                known_repository_name="analytics",
                known_incident_reference="incident:checkout-500",
            )
        )

        self.assertEqual(extracted.repository_owner, "octo-org")
        self.assertEqual(extracted.repository_name, "analytics")
        self.assertEqual(extracted.incident_reference, "incident:checkout-500")


if __name__ == "__main__":
    unittest.main()

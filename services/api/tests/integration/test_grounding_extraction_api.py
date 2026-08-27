import unittest

from fastapi.testclient import TestClient

from app.api.v1.connector_router import get_grounding_extractor, get_run_repository
from app.explanations import (
    FakeLLMClient,
    LLMProviderError,
    LLMProviderFailureCategory,
)
from app.investigations.grounding_extraction import (
    GroundingExtractionOutput,
    TypedGroundingExtractor,
)
from app.main import app
from app.runtime import InMemoryRunRepository


class GroundingExtractionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.repository = InMemoryRunRepository()
        app.dependency_overrides[get_run_repository] = lambda: self.repository

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _override_extractor(self, typed_output: object) -> None:
        app.dependency_overrides[get_grounding_extractor] = (
            lambda: TypedGroundingExtractor(FakeLLMClient(typed_output=typed_output))
        )

    def test_complete_extraction_reports_status_complete_and_extracted_fields(
        self,
    ) -> None:
        self._override_extractor(
            GroundingExtractionOutput(
                repository_owner="octo-org",
                repository_name="analytics",
                deployment_reference="deployment:52",
                pull_request_number=42,
            )
        )

        response = self.client.post(
            "/v1/investigations/extract-grounding",
            json={
                "description": (
                    "PR 42 in octo-org/analytics, deployment 52, checkout "
                    "throwing errors"
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "complete")
        self.assertEqual(body["extracted"]["repository_owner"], "octo-org")
        self.assertEqual(body["extracted"]["pull_request_number"], 42)
        self.assertEqual(body["missing"], [])
        self.assertIsNone(body["question"])

    def test_incomplete_extraction_reports_needs_clarification_with_missing_fields(
        self,
    ) -> None:
        self._override_extractor(
            GroundingExtractionOutput(
                repository_owner="octo-org",
                repository_name="analytics",
            )
        )

        response = self.client.post(
            "/v1/investigations/extract-grounding",
            json={"description": "Something is wrong with octo-org/analytics."},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "needs_clarification")
        self.assertEqual(
            sorted(body["missing"]),
            sorted(
                [
                    "incident_reference",
                    "deployment_reference",
                    "pull_request_number",
                ]
            ),
        )
        self.assertIsNotNone(body["question"])

    def test_extraction_never_creates_or_persists_a_run(self) -> None:
        self._override_extractor(
            GroundingExtractionOutput(
                repository_owner="octo-org",
                repository_name="analytics",
                pull_request_number=42,
            )
        )

        self.client.post(
            "/v1/investigations/extract-grounding",
            json={"description": "PR 42 in octo-org/analytics"},
        )

        self.assertEqual(self.repository.history, ())

    def test_provider_failure_returns_502_with_a_typed_error(self) -> None:
        class FailingClient:
            provider = FakeLLMClient.provider
            model = "failure"

            async def generate_typed(self, request):
                raise LLMProviderError(LLMProviderFailureCategory.CONNECTION)

        app.dependency_overrides[get_grounding_extractor] = (
            lambda: TypedGroundingExtractor(FailingClient())
        )

        response = self.client.post(
            "/v1/investigations/extract-grounding",
            json={"description": "PR 42 in octo-org/analytics"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "provider_failure")

    def test_ambiguous_text_through_the_real_fixture_needs_clarification(
        self,
    ) -> None:
        app.dependency_overrides.pop(get_grounding_extractor, None)

        response = self.client.post(
            "/v1/investigations/extract-grounding",
            json={"description": "Checkout is throwing errors after a deploy went out."},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "needs_clarification")
        self.assertIsNotNone(body["question"])

    def test_known_text_through_the_real_fixture_extracts_completely(self) -> None:
        app.dependency_overrides.pop(get_grounding_extractor, None)

        response = self.client.post(
            "/v1/investigations/extract-grounding",
            json={
                "description": (
                    "PR 42 in octo-org/analytics, deployment 52, checkout "
                    "throwing errors"
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "complete")
        self.assertEqual(body["extracted"]["repository_owner"], "octo-org")
        self.assertEqual(body["extracted"]["repository_name"], "analytics")
        self.assertEqual(body["extracted"]["pull_request_number"], 42)
        self.assertEqual(body["extracted"]["deployment_reference"], "deployment:52")


if __name__ == "__main__":
    unittest.main()

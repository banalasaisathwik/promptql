import unittest

from pydantic import ValidationError

from app.investigations.grounding_extraction import (
    GroundingExtractionError,
    GroundingExtractionFailureCode,
    GroundingExtractionInput,
    GroundingExtractionOutput,
)


class GroundingExtractionInputTests(unittest.TestCase):
    def test_description_is_required_and_known_fields_default_to_none(self) -> None:
        extraction_input = GroundingExtractionInput(description="Checkout is failing.")

        self.assertEqual(extraction_input.description, "Checkout is failing.")
        self.assertIsNone(extraction_input.known_repository_owner)
        self.assertIsNone(extraction_input.known_repository_name)
        self.assertIsNone(extraction_input.known_incident_reference)
        self.assertIsNone(extraction_input.known_deployment_reference)
        self.assertIsNone(extraction_input.known_pull_request_number)

    def test_blank_description_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            GroundingExtractionInput(description="   ")

    def test_known_pull_request_number_must_be_a_strict_positive_int(self) -> None:
        with self.assertRaises(ValidationError):
            GroundingExtractionInput(description="text", known_pull_request_number=0)
        with self.assertRaises(ValidationError):
            GroundingExtractionInput(description="text", known_pull_request_number=1.5)


class GroundingExtractionOutputTests(unittest.TestCase):
    def test_all_five_fields_are_optional(self) -> None:
        output = GroundingExtractionOutput()

        self.assertIsNone(output.repository_owner)
        self.assertIsNone(output.repository_name)
        self.assertIsNone(output.incident_reference)
        self.assertIsNone(output.deployment_reference)
        self.assertIsNone(output.pull_request_number)

    def test_partial_extraction_is_valid(self) -> None:
        output = GroundingExtractionOutput(
            repository_owner="octo-org",
            repository_name="analytics",
            pull_request_number=42,
        )

        self.assertEqual(output.repository_owner, "octo-org")
        self.assertEqual(output.pull_request_number, 42)
        self.assertIsNone(output.incident_reference)

    def test_extra_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            GroundingExtractionOutput.model_validate({"root_cause": "forbidden"})


class GroundingExtractionErrorTests(unittest.TestCase):
    def test_error_carries_code_and_message(self) -> None:
        error = GroundingExtractionError(
            GroundingExtractionFailureCode.PROVIDER_FAILURE,
            "The grounding extraction provider failed.",
        )

        self.assertEqual(error.code, GroundingExtractionFailureCode.PROVIDER_FAILURE)
        self.assertEqual(str(error), "The grounding extraction provider failed.")
        self.assertIsNone(error.provider_details)
        self.assertIsNone(error.provider_failure_category)


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from app.config import LLMProvider, LLMSettings, ModelPolicy
from app.diagnostics.openrouter import _failure_result, resolved_configuration


def _settings() -> LLMSettings:
    return LLMSettings(
        provider=LLMProvider.OPENROUTER,
        api_key="private-openrouter-key",
        model="default-model",
        request_timeout_seconds=30,
        max_output_tokens=512,
        model_policy=ModelPolicy(
            default_model="default-model",
            planner_model="planner-model",
            hypothesis_model="hypothesis-model",
            code_diagnosis_model=None,
        ),
    )


class OpenRouterDiagnosticTests(unittest.TestCase):
    def test_resolved_configuration_reports_presence_without_exposing_key(self) -> None:
        configuration = resolved_configuration(_settings())

        self.assertEqual(configuration["provider"], "openrouter")
        self.assertEqual(configuration["planner_model"], "planner-model")
        self.assertEqual(configuration["hypothesis_model"], "hypothesis-model")
        self.assertTrue(configuration["api_key_present"])
        self.assertNotIn("private-openrouter-key", json.dumps(configuration))

    def test_failure_result_extracts_only_sanitized_upstream_fields(self) -> None:
        error = RuntimeError("outer private-openrouter-key")
        error.status_code = 400
        error.message = "Provider returned error"
        error.body = {
            "error": {
                "code": 400,
                "message": "Provider returned error",
                "metadata": {
                    "provider_name": "Azure",
                    "raw": json.dumps({
                        "error": {
                            "code": "invalid_json_schema",
                            "type": "invalid_request_error",
                            "message": (
                                "Invalid oneOf schema for private-openrouter-key"
                            ),
                        }
                    }),
                },
            }
        }

        result = _failure_result(
            stage="planner",
            error=error,
            settings=_settings(),
            requested_model="planner-model",
            api_method="beta.chat.completions.parse",
            provider_category="provider_failure",
        )

        self.assertEqual(result["http_status"], 400)
        self.assertEqual(result["upstream_provider"], "Azure")
        self.assertEqual(result["upstream_error_code"], "invalid_json_schema")
        self.assertIn("Invalid oneOf schema", result["upstream_message"])
        self.assertNotIn("private-openrouter-key", json.dumps(result))

    def test_non_json_upstream_metadata_is_not_echoed(self) -> None:
        error = RuntimeError("safe outer error")
        error.body = {
            "error": {
                "message": "Provider returned error",
                "metadata": {
                    "provider_name": "Example",
                    "raw": "private prompt or provider payload",
                },
            }
        }

        result = _failure_result(
            stage="typed",
            error=error,
            settings=_settings(),
            requested_model="planner-model",
            api_method="beta.chat.completions.parse",
        )

        self.assertEqual(
            result["upstream_message"],
            "Upstream returned non-JSON error metadata.",
        )
        self.assertNotIn("private prompt", json.dumps(result))


if __name__ == "__main__":
    unittest.main()

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.config import LLMProvider, LLMSettings, ModelPolicy
from app.diagnostics.openrouter import (
    COMPONENT_STAGES,
    PAID_STAGES,
    _failure_result,
    resolved_configuration,
    run_code_diagnosis_call,
    run_plain_call,
    run_workflow_call,
)
from app.explanations import FakeLLMClient


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
    def test_workflow_stage_runs_the_complete_fake_connector_trajectory(self) -> None:
        with patch(
            "app.diagnostics.openrouter._typed_client",
            side_effect=lambda _settings, _model: (FakeLLMClient(), object()),
        ) as client_factory:
            result = asyncio.run(run_workflow_call(_settings()))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["maximum_provider_calls"], 5)
        self.assertIn(
            result["termination_reason"],
            {"completed", "no_progress", "planning_limit_reached", "budget_exhausted"},
        )
        self.assertGreaterEqual(result["planning_round_count"], 2)
        self.assertGreater(result["evidence_count"], 0)
        self.assertGreater(result["fact_count"], 0)
        self.assertGreater(result["hypothesis_count"], 0)
        self.assertGreater(result["code_finding_count"], 0)
        self.assertGreater(result["recommendation_count"], 0)
        self.assertIn("workflow", PAID_STAGES)
        self.assertNotIn("workflow", COMPONENT_STAGES)
        self.assertEqual(client_factory.call_count, 3)

    def test_workflow_stage_failure_reports_a_sanitized_exception_message(self) -> None:
        fake_secret = "sk-FAKESECRETVALUE1234567890"

        def _raise_unexpected_error(*_args, **_kwargs):
            raise AttributeError(
                f"'NoneType' object has no attribute 'candidates' near {fake_secret}"
            )

        with patch(
            "app.diagnostics.openrouter._typed_client",
            side_effect=lambda _settings, _model: (FakeLLMClient(), object()),
        ), patch(
            "app.diagnostics.openrouter.InvestigationWorkflowService",
            side_effect=_raise_unexpected_error,
        ):
            result = asyncio.run(run_workflow_call(_settings()))

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["exception_class"], "AttributeError")
        self.assertIn("exception_message", result)
        self.assertNotIn(fake_secret, result["exception_message"])
        self.assertNotIn(fake_secret, json.dumps(result))

    def test_plain_gate_accepts_a_transport_response_with_a_choice(self) -> None:
        class Completions:
            async def create(self, **_request):
                return SimpleNamespace(
                    choices=(
                        SimpleNamespace(
                            message=SimpleNamespace(content="Okay, acknowledged."),
                        ),
                    ),
                    model="resolved-provider-model",
                )

        class Client:
            chat = SimpleNamespace(completions=Completions())

            async def close(self):
                return None

        with patch(
            "app.diagnostics.openrouter._sdk_client",
            return_value=Client(),
        ):
            result = asyncio.run(run_plain_call(_settings()))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["resolved_model"], "resolved-provider-model")

    def test_plain_gate_accepts_reasoning_choice_without_visible_text(self) -> None:
        class Completions:
            async def create(self, **_request):
                return SimpleNamespace(
                    choices=(
                        SimpleNamespace(message=SimpleNamespace(content=None)),
                    ),
                    model="resolved-provider-model",
                )

        class Client:
            chat = SimpleNamespace(completions=Completions())

            async def close(self):
                return None

        with patch(
            "app.diagnostics.openrouter._sdk_client",
            return_value=Client(),
        ):
            result = asyncio.run(run_plain_call(_settings()))

        self.assertEqual(result["status"], "PASS")

    def test_resolved_configuration_reports_presence_without_exposing_key(self) -> None:
        configuration = resolved_configuration(_settings())

        self.assertEqual(configuration["provider"], "openrouter")
        self.assertEqual(configuration["planner_model"], "planner-model")
        self.assertEqual(configuration["hypothesis_model"], "hypothesis-model")
        self.assertTrue(configuration["api_key_present"])
        self.assertNotIn("private-openrouter-key", json.dumps(configuration))

    def test_unconfigured_code_diagnosis_is_reported_without_constructing_client(self) -> None:
        settings = LLMSettings(
            provider=LLMProvider.OPENROUTER,
            api_key="private-openrouter-key",
            model=None,
            request_timeout_seconds=30,
            max_output_tokens=512,
            model_policy=ModelPolicy(
                default_model=None,
                planner_model="planner-model",
                hypothesis_model="hypothesis-model",
                code_diagnosis_model=None,
            ),
        )

        with patch("app.diagnostics.openrouter._typed_client") as client_factory:
            result = asyncio.run(run_code_diagnosis_call(settings))

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["provider_category"], "configuration_error")
        self.assertEqual(result["api_method"], "not_called")
        self.assertIsNone(resolved_configuration(settings)["code_diagnosis_model"])
        client_factory.assert_not_called()

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

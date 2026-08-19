import unittest

from pydantic import ValidationError

from app.connectors.github_code_fakes import (
    CHANGED_FILE_EVIDENCE_FIXTURES,
    FIXTURE_PULL_REQUEST,
)
from app.explanations import FakeLLMClient, LLMProviderError, LLMProviderFailureCategory
from app.investigations import InvestigationRequest, InvestigationResult
from app.investigations.planning import (
    InvestigationPlan,
    InvestigationPlannerError,
    Literal,
    PlanArgument,
    PlanStep,
    PlannerFailureCode,
    StepOutputRef,
    TypedLLMPlanner,
    build_planner_input,
)
from app.tools.models import TOOL_DEFINITIONS


def _result():
    return InvestigationResult(
        evidence=CHANGED_FILE_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST],
        facts=(),
        hypotheses=(),
        missing_information=(),
        recommended_actions=(),
    )


def _request():
    # Keep the prompt test grounded in the same typed request boundary the caller
    # supplies, instead of letting the planner invent its own investigation goal.
    return InvestigationRequest(
        repository_owner="octo-org",
        repository_name="analytics",
        incident_summary="Investigate checkout failures after deployment.",
    )


def _plan():
    return InvestigationPlan(
        steps=(
            PlanStep(
                step_id="s1",
                tool_id="get_deployments",
                arguments=(
                    PlanArgument(name="deployment_reference", value=Literal(value="deploy-42")),
                ),
                reason="Retrieve the deployed revision.",
            ),
            PlanStep(
                step_id="s2",
                tool_id="get_commit",
                arguments=(
                    PlanArgument(
                        name="commit_sha",
                        value=StepOutputRef(step_id="s1", field="commit_sha"),
                    ),
                ),
                depends_on=("s1",),
                reason="Inspect the deployed commit.",
            ),
        )
    )


class PlannerContractTests(unittest.TestCase):
    def test_contract_supports_bounded_steps_literals_references_and_immutability(self) -> None:
        plan = _plan()

        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].arguments[0].value.value_kind, "literal")
        self.assertEqual(plan.steps[1].arguments[0].value.value_kind, "step_output_ref")
        with self.assertRaises(ValidationError):
            plan.steps = ()

    def test_contract_rejects_extra_fields_and_more_than_five_steps(self) -> None:
        with self.assertRaises(ValidationError):
            PlanStep.model_validate({
                "step_id": "s1", "tool_id": "get_incident", "arguments": (),
                "reason": "Retrieve incident.", "root_cause": "forbidden",
            })
        with self.assertRaises(ValidationError):
            InvestigationPlan(steps=(_plan().steps[0],) * 6)


class PlannerPromptTests(unittest.TestCase):
    def test_builder_orders_tools_and_excludes_raw_diff_lines(self) -> None:
        planner_input = build_planner_input(_request(), _result(), reversed(TOOL_DEFINITIONS))

        self.assertEqual(
            [tool.tool_id.value for tool in planner_input.allowed_tools],
            sorted(tool.tool_id.value for tool in TOOL_DEFINITIONS),
        )
        prompt_json = planner_input.model_dump_json()
        self.assertIn("allowed_tools", prompt_json)
        self.assertIn(_request().incident_summary, prompt_json)
        self.assertNotIn("lines", prompt_json)
        self.assertNotIn("root_cause", prompt_json)


class TypedPlannerTests(unittest.IsolatedAsyncioTestCase):
    # These tests use injected fake clients to prove the proposal boundary without
    # credentials, provider SDK calls, or accidentally executing a V2.5 tool.
    async def test_fake_llm_returns_a_typed_multi_step_plan_without_execution(self) -> None:
        proposed = await TypedLLMPlanner(FakeLLMClient(typed_output=_plan())).plan(
            build_planner_input(_request(), _result(), TOOL_DEFINITIONS)
        )

        self.assertEqual(proposed.plan, _plan())
        self.assertEqual(proposed.metadata.prompt_version, "v2.7.1")
        self.assertEqual(proposed.metadata.provider, "fake")

    async def test_provider_invalid_response_and_schema_failures_are_distinguishable(self) -> None:
        planner_input = build_planner_input(_request(), _result(), TOOL_DEFINITIONS)

        class ProviderFailure:
            provider = FakeLLMClient.provider
            model = "failure"

            async def generate_typed(self, request):
                raise LLMProviderError(LLMProviderFailureCategory.CONNECTION)

        class MalformedResponse:
            provider = FakeLLMClient.provider
            model = "malformed"

            async def generate_typed(self, request):
                return object()

        for client, expected in (
            (ProviderFailure(), PlannerFailureCode.PROVIDER_FAILURE),
            (MalformedResponse(), PlannerFailureCode.INVALID_RESPONSE),
            (FakeLLMClient(typed_output={"steps": "not-a-list"}), PlannerFailureCode.PLAN_SCHEMA_INVALID),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(InvestigationPlannerError) as raised:
                    await TypedLLMPlanner(client).plan(planner_input)
                self.assertEqual(raised.exception.code, expected)

    async def test_planner_prompt_explicitly_forbids_truth_claims_and_execution(self) -> None:
        class RecordingClient:
            provider = FakeLLMClient.provider
            model = "recording"
            request = None

            async def generate_typed(self, request):
                self.request = request
                return {"output": _plan().model_dump(mode="json")}

        client = RecordingClient()
        await TypedLLMPlanner(client).plan(build_planner_input(_request(), _result(), TOOL_DEFINITIONS))

        self.assertIn("Do not execute tools", client.request.system_instructions)
        self.assertIn("Do not create authoritative facts", client.request.system_instructions)
        self.assertIn("root-cause claims", client.request.system_instructions)


if __name__ == "__main__":
    unittest.main()

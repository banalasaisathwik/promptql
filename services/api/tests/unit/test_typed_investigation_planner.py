import unittest
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from app.connectors.github_code_fakes import (
    CHANGED_FILE_EVIDENCE_FIXTURES,
    FIXTURE_PULL_REQUEST,
)
from app.explanations import (
    FakeLLMClient,
    LLMProviderError,
    LLMProviderErrorDetails,
    LLMProviderFailureCategory,
)
from app.investigations import InvestigationRequest, InvestigationResult
from app.investigations.planning import (
    ContextBuilder,
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
from app.runtime import FACT_RECURRENCE_PROMOTION_THRESHOLD, InMemoryFactRecurrenceRepository
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
    return InvestigationRequest(
        repository_owner="octo-org",
        repository_name="analytics",
        question="Investigate checkout failures after deployment.",
        incident_reference="incident:checkout-500",
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

    def test_provider_schema_discriminates_argument_values_and_uses_number_literals(self) -> None:
        schema = InvestigationPlan.model_json_schema()
        value_schema = schema["$defs"]["PlanArgument"]["properties"]["value"]
        literal_value_schema = schema["$defs"]["Literal"]["properties"]["value"]

        self.assertIn("oneOf", value_schema)
        self.assertNotIn("anyOf", value_schema)
        self.assertEqual(value_schema["discriminator"]["propertyName"], "value_kind")
        self.assertEqual(
            sorted(value_schema["discriminator"]["mapping"]),
            ["literal", "step_output_ref"],
        )
        self.assertEqual(
            [item["type"] for item in literal_value_schema["anyOf"]],
            ["string", "number", "boolean", "null"],
        )
        self.assertNotIn(
            "integer",
            [item["type"] for item in literal_value_schema["anyOf"]],
        )


class PlannerPromptTests(unittest.TestCase):
    def test_builder_orders_tools_and_excludes_raw_diff_lines(self) -> None:
        planner_input = build_planner_input(_request(), _result(), reversed(TOOL_DEFINITIONS))

        self.assertEqual(
            [tool.tool_id.value for tool in planner_input.allowed_tools],
            sorted(tool.tool_id.value for tool in TOOL_DEFINITIONS),
        )
        self.assertEqual(planner_input.request_context, _request())
        get_commit = next(
            tool for tool in planner_input.allowed_tools if tool.tool_id == "get_commit"
        )
        self.assertIn("repository_owner", get_commit.input_schema["properties"])
        self.assertIn("commit_sha", get_commit.output_schema["properties"])
        prompt_json = planner_input.model_dump_json()
        self.assertIn("allowed_tools", prompt_json)
        self.assertIn(_request().question, prompt_json)
        self.assertNotIn("lines", prompt_json)
        self.assertNotIn("root_cause", prompt_json)


class TypedPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_llm_returns_a_typed_multi_step_plan_without_execution(self) -> None:
        proposed = await TypedLLMPlanner(FakeLLMClient(typed_output=_plan())).plan(
            build_planner_input(_request(), _result(), TOOL_DEFINITIONS)
        )

        self.assertEqual(proposed.plan, _plan())
        self.assertEqual(proposed.metadata.prompt_version, "v2.7.6")
        self.assertEqual(proposed.metadata.provider, "fake")
        self.assertEqual(proposed.metadata.task, "planning")
        self.assertEqual(proposed.metadata.requested_model, "deterministic-fake-v1")

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

    async def test_provider_failure_preserves_safe_diagnostic_details(self) -> None:
        planner_input = build_planner_input(_request(), _result(), TOOL_DEFINITIONS)
        details = LLMProviderErrorDetails(
            http_status=400,
            provider_type="invalid_request_error",
            provider_code="json_validate_failed",
            provider_message="Groq rejected generated structured output.",
            failed_generation_present=True,
            failed_generation_length=123,
        )

        class ProviderFailure:
            provider = FakeLLMClient.provider
            model = "failure"

            async def generate_typed(self, request):
                raise LLMProviderError(
                    LLMProviderFailureCategory.INVALID_REQUEST,
                    details,
                )

        with self.assertRaises(InvestigationPlannerError) as raised:
            await TypedLLMPlanner(ProviderFailure()).plan(planner_input)

        self.assertEqual(raised.exception.code, PlannerFailureCode.PROVIDER_FAILURE)
        self.assertEqual(raised.exception.provider_details, details)
        self.assertEqual(
            raised.exception.provider_failure_category,
            LLMProviderFailureCategory.INVALID_REQUEST.value,
        )

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


class RepositoryMemoryReadPathTests(unittest.TestCase):
    def _build(self, fact_recurrence_repository, request):
        return ContextBuilder().build(
            request.question,
            (),
            (),
            (),
            TOOL_DEFINITIONS,
            request_context=request,
            fact_recurrence_repository=fact_recurrence_repository,
        )

    def test_unpromoted_pattern_is_not_surfaced(self) -> None:
        repository = InMemoryFactRecurrenceRepository()
        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD - 1):
            repository.record_occurrence(
                "octo-org", "analytics", "changed_file", uuid4(), datetime.now(UTC)
            )

        planner_input = self._build(repository, _request())

        self.assertEqual(planner_input.remembered_patterns, ())

    def test_promoted_pattern_is_surfaced_as_fact_type_and_count(self) -> None:
        repository = InMemoryFactRecurrenceRepository()
        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD):
            repository.record_occurrence(
                "octo-org", "analytics", "changed_file", uuid4(), datetime.now(UTC)
            )

        planner_input = self._build(repository, _request())

        self.assertEqual(len(planner_input.remembered_patterns), 1)
        remembered = planner_input.remembered_patterns[0]
        self.assertEqual(remembered.fact_type, "changed_file")
        self.assertEqual(remembered.occurrence_count, FACT_RECURRENCE_PROMOTION_THRESHOLD)

    def test_another_repositorys_promoted_pattern_does_not_leak(self) -> None:
        repository = InMemoryFactRecurrenceRepository()
        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD):
            repository.record_occurrence(
                "other-org", "other-repo", "changed_file", uuid4(), datetime.now(UTC)
            )

        planner_input = self._build(repository, _request())

        self.assertEqual(planner_input.remembered_patterns, ())

    def test_missing_repository_still_returns_empty_tuple(self) -> None:
        planner_input = ContextBuilder().build(
            _request().question, (), (), (), TOOL_DEFINITIONS, request_context=_request()
        )

        self.assertEqual(planner_input.remembered_patterns, ())


class RepositoryMemoryPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_instructions_omit_section_when_no_remembered_patterns(self) -> None:
        class RecordingClient:
            provider = FakeLLMClient.provider
            model = "recording"
            request = None

            async def generate_typed(self, request):
                self.request = request
                return {"output": _plan().model_dump(mode="json")}

        client = RecordingClient()
        await TypedLLMPlanner(client).plan(build_planner_input(_request(), _result(), TOOL_DEFINITIONS))

        self.assertNotIn("Known recurring patterns", client.request.system_instructions)

    async def test_system_instructions_include_labeled_section_when_remembered_patterns_present(
        self,
    ) -> None:
        repository = InMemoryFactRecurrenceRepository()
        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD):
            repository.record_occurrence(
                "octo-org", "analytics", "changed_file", uuid4(), datetime.now(UTC)
            )
        planner_input = ContextBuilder().build(
            _request().question,
            (),
            (),
            CHANGED_FILE_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST],
            TOOL_DEFINITIONS,
            request_context=_request(),
            fact_recurrence_repository=repository,
        )

        class RecordingClient:
            provider = FakeLLMClient.provider
            model = "recording"
            request = None

            async def generate_typed(self, request):
                self.request = request
                return {"output": _plan().model_dump(mode="json")}

        client = RecordingClient()
        await TypedLLMPlanner(client).plan(planner_input)

        self.assertIn("Known recurring patterns for this repository", client.request.system_instructions)
        self.assertIn("not evidence from this run", client.request.system_instructions)


if __name__ == "__main__":
    unittest.main()

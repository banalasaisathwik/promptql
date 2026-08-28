import json
import unittest
from datetime import UTC, datetime

from app.investigations import (
    AdaptiveInvestigationRuntime,
    AgentExecutor,
    ContinuationReason,
    DeploymentEvidenceContent,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    ExecutionBudget,
    IncidentEvidenceContent,
)
from app.explanations import LLMProviderErrorDetails
from app.investigations.evidence_store import EvidenceStore
from app.investigations.planning import InvestigationPlan, InvestigationPlannerError, Literal, PlanArgument, PlanStep, PlannerFailureCode, PlanValidator, PlannedInvestigation, PlannerMetadata
from app.tools import InvestigationToolId, TOOL_DEFINITIONS, ToolOutcome, ToolRegistry, ToolResult


class RecordingInvoker:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    async def invoke(self, tool_id, arguments):
        self.calls.append(tool_id)
        return self.results.pop(0)


class SequentialPlanner:
    def __init__(self, plans):
        self.plans, self.inputs = list(plans), []

    async def plan(self, planner_input):
        self.inputs.append(planner_input)
        return PlannedInvestigation(plan=self.plans.pop(0), metadata=PlannerMetadata(provider="fake", model="fake", prompt_id="test", prompt_version="test"))


class FailingPlanner:
    async def plan(self, _planner_input):
        raise InvestigationPlannerError(
            PlannerFailureCode.PROVIDER_FAILURE,
            "The planning provider failed.",
            provider_details=LLMProviderErrorDetails(
                http_status=400,
                provider_type="invalid_request_error",
                provider_code="json_validate_failed",
                provider_message="Groq rejected generated structured output.",
                failed_generation_present=True,
                failed_generation_length=123,
            ),
            provider_failure_category="invalid_request",
        )


class AdaptiveRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = EvidenceStore()

    def _plan(self, step_id, reference):
        return InvestigationPlan(steps=(PlanStep(step_id=step_id, tool_id="get_incident", reason="collect incident", arguments=(PlanArgument(name="incident_reference", value=Literal(value=reference)),)),))

    def _incident(self, evidence_id):
        now = datetime(2026, 8, 19, tzinfo=UTC)
        return Evidence(evidence_id=evidence_id, source=EvidenceSource.INCIDENT, kind=EvidenceKind.INCIDENT, provenance=EvidenceProvenance(source_reference=evidence_id, retrieved_at=now), content=IncidentEvidenceContent(incident_reference=evidence_id, started_at=now))

    def _observed_result(self, tool_id, *evidence):
        evidence_ids = tuple(self.store.put(item) for item in evidence)
        return ToolResult(tool_id=tool_id, outcome=ToolOutcome.OBSERVED, evidence_ids=evidence_ids)

    async def test_executes_the_short_round_before_replanning_and_passes_accumulated_state(self):
        registry = ToolRegistry(TOOL_DEFINITIONS)
        planner = SequentialPlanner((self._plan("s1", "one"), self._plan("s1", "two")))
        invoker = RecordingInvoker((
            self._observed_result(InvestigationToolId.GET_INCIDENT, self._incident("e1")),
            ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.EMPTY),
        ))
        runtime = AdaptiveInvestigationRuntime(planner, PlanValidator(registry), AgentExecutor(registry, invoker, self.store), self.store)

        state = await runtime.investigate("Why did checkout-api fail?", TOOL_DEFINITIONS, budget=ExecutionBudget(max_tool_calls=3))

        self.assertEqual(invoker.calls, [InvestigationToolId.GET_INCIDENT, InvestigationToolId.GET_INCIDENT])
        self.assertEqual(len(state.rounds), 2)
        self.assertEqual(state.rounds[0].evidence_delta_ids, ("e1",))
        self.assertEqual(planner.inputs[1].evidence[0].evidence_id, "e1")
        self.assertEqual(planner.inputs[1].action_history[0].tool_id, InvestigationToolId.GET_INCIDENT)
        self.assertEqual(state.continuation_reason, ContinuationReason.NO_PROGRESS)

    async def test_a_follow_up_round_numbers_continue_from_initial_rounds(self):
        registry = ToolRegistry(TOOL_DEFINITIONS)
        planner = SequentialPlanner((self._plan("s1", "two"),))
        invoker = RecordingInvoker((
            ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.EMPTY),
        ))
        runtime = AdaptiveInvestigationRuntime(planner, PlanValidator(registry), AgentExecutor(registry, invoker, self.store), self.store)

        state = await runtime.investigate(
            "Why did checkout-api fail?",
            TOOL_DEFINITIONS,
            budget=ExecutionBudget(max_tool_calls=5),
            initial_rounds=2,
        )

        self.assertEqual(len(state.rounds), 1)
        self.assertEqual(state.rounds[0].round_number, 3)
        self.assertEqual(planner.inputs[0].planning_round, 3)

    async def test_a_follow_up_on_an_exhausted_budget_short_circuits_before_planning(self):
        registry = ToolRegistry(TOOL_DEFINITIONS)
        planner = SequentialPlanner(())
        invoker = RecordingInvoker(())
        runtime = AdaptiveInvestigationRuntime(planner, PlanValidator(registry), AgentExecutor(registry, invoker, self.store), self.store)

        state = await runtime.investigate(
            "Why did checkout-api fail?",
            TOOL_DEFINITIONS,
            budget=ExecutionBudget(max_tool_calls=0),
            initial_rounds=1,
        )

        self.assertEqual(state.continuation_reason, ContinuationReason.TOOL_CALL_BUDGET_EXHAUSTED)
        self.assertEqual(state.rounds, ())
        self.assertEqual(planner.inputs, [])
        self.assertEqual(invoker.calls, [])

    async def test_a_follow_up_that_already_used_every_planning_round_still_terminates(self):
        registry = ToolRegistry(TOOL_DEFINITIONS)
        planner = SequentialPlanner(())
        invoker = RecordingInvoker(())
        runtime = AdaptiveInvestigationRuntime(planner, PlanValidator(registry), AgentExecutor(registry, invoker, self.store), self.store)

        state = await runtime.investigate(
            "Why did checkout-api fail?",
            TOOL_DEFINITIONS,
            budget=ExecutionBudget(max_tool_calls=5),
            initial_rounds=3,
        )

        self.assertEqual(state.continuation_reason, ContinuationReason.MAX_PLANNING_ROUNDS)
        self.assertEqual(state.rounds, ())
        self.assertEqual(planner.inputs, [])

    async def test_prior_result_summary_is_carried_only_on_a_follow_up_round(self):
        registry = ToolRegistry(TOOL_DEFINITIONS)
        planner = SequentialPlanner((self._plan("s1", "two"),))
        invoker = RecordingInvoker((
            ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.EMPTY),
        ))
        runtime = AdaptiveInvestigationRuntime(planner, PlanValidator(registry), AgentExecutor(registry, invoker, self.store), self.store)

        await runtime.investigate(
            "What about the deployment?",
            TOOL_DEFINITIONS,
            budget=ExecutionBudget(max_tool_calls=5),
            initial_rounds=1,
            prior_result_summary="No supported hypotheses were found in the prior turn.",
        )

        self.assertEqual(planner.inputs[0].investigation_goal, "What about the deployment?")
        self.assertEqual(
            planner.inputs[0].prior_result_summary,
            "No supported hypotheses were found in the prior turn.",
        )

    async def test_global_budget_stops_before_another_planner_call(self):
        registry = ToolRegistry(TOOL_DEFINITIONS)
        planner = SequentialPlanner((self._plan("s1", "one"),))
        invoker = RecordingInvoker((
            self._observed_result(InvestigationToolId.GET_INCIDENT, self._incident("e1")),
        ))
        runtime = AdaptiveInvestigationRuntime(planner, PlanValidator(registry), AgentExecutor(registry, invoker, self.store), self.store)

        state = await runtime.investigate("Why did checkout-api fail?", TOOL_DEFINITIONS, budget=ExecutionBudget(max_tool_calls=1))

        self.assertEqual(state.continuation_reason, ContinuationReason.TOOL_CALL_BUDGET_EXHAUSTED)
        self.assertEqual(len(planner.inputs), 1)
        self.assertEqual(state.remaining_tool_calls, 0)

    async def test_invalid_replanned_plan_terminates_without_execution(self):
        registry = ToolRegistry(TOOL_DEFINITIONS)
        invalid_plan = InvestigationPlan(steps=(PlanStep(step_id="s1", tool_id="unknown_tool", reason="invalid", arguments=()),))
        planner = SequentialPlanner((invalid_plan,))
        invoker = RecordingInvoker(())
        runtime = AdaptiveInvestigationRuntime(planner, PlanValidator(registry), AgentExecutor(registry, invoker, self.store), self.store)

        state = await runtime.investigate("Why did checkout-api fail?", TOOL_DEFINITIONS, budget=ExecutionBudget(max_tool_calls=1))

        self.assertEqual(state.continuation_reason, ContinuationReason.PLAN_VALIDATION_FAILURE)
        self.assertEqual(invoker.calls, [])

    async def test_planner_failure_logs_safe_context_without_the_goal(self):
        registry = ToolRegistry(TOOL_DEFINITIONS)
        runtime = AdaptiveInvestigationRuntime(
            FailingPlanner(), PlanValidator(registry), AgentExecutor(registry, RecordingInvoker(()), self.store), self.store
        )
        private_evidence_id = self.store.put(self._incident("private-evidence-payload"))

        with self.assertLogs("promptql.runtime", level="ERROR") as logs:
            state = await runtime.investigate(
                "Private checkout incident question",
                TOOL_DEFINITIONS,
                budget=ExecutionBudget(max_tool_calls=10),
                initial_evidence=(private_evidence_id,),
            )

        record = json.loads(logs.output[0].split(":", 2)[-1])
        self.assertEqual(state.continuation_reason, ContinuationReason.PLANNER_FAILURE)
        self.assertEqual(record["round"], 1)
        self.assertEqual(record["facts_count"], 0)
        self.assertEqual(record["evidence_count"], 1)
        self.assertEqual(record["remaining_tool_calls"], 10)
        self.assertEqual(record["exception_class"], "InvestigationPlannerError")
        self.assertEqual(record["planner_failure_code"], "provider_failure")
        self.assertEqual(record["http_status"], 400)
        self.assertEqual(record["provider_type"], "invalid_request_error")
        self.assertEqual(record["provider_code"], "json_validate_failed")
        self.assertEqual(record["provider_failure_category"], "invalid_request")
        self.assertEqual(record["failed_generation_length"], 123)
        self.assertNotIn("Private checkout incident question", logs.output[0])
        self.assertNotIn("private-evidence-payload", logs.output[0])


if __name__ == "__main__":
    unittest.main()

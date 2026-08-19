import unittest
from datetime import UTC, datetime, timedelta

from app.investigations import (
    AgentExecutor,
    ExecutionBudget,
    DeploymentEvidenceContent,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    ExecutionBlockReason,
    ExecutionStepStatus,
    ExecutionTerminationReason,
    IncidentEvidenceContent,
)
from app.investigations.planning import (
    InvestigationPlan,
    Literal,
    PlanArgument,
    PlanStep,
    PlanValidator,
    StepOutputRef,
)
from app.tools import (
    InvestigationToolId,
    TOOL_DEFINITIONS,
    ToolFailure,
    ToolFailureCode,
    ToolOutcome,
    ToolRegistry,
    ToolResult,
)


class RecordingInvoker:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def invoke(self, tool_id, arguments):
        self.calls.append((tool_id, arguments))
        results = self.results[tool_id]
        return results.pop(0) if isinstance(results, list) else results


# This injected async test double records requested delays so backoff tests do
# not wait one or two real seconds. It plays the same role as a mocked timer in
# a JavaScript test while leaving production execution on `asyncio.sleep`.
class RecordingSleeper:
    def __init__(self):
        self.delays = []

    async def __call__(self, seconds):
        self.delays.append(seconds)


class AgentExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.definitions = {item.tool_id: item for item in TOOL_DEFINITIONS}
        self.registry = ToolRegistry(self.definitions.values())
        self.timestamp = datetime(2026, 8, 19, tzinfo=UTC)

    def _validated(self, *steps):
        result = PlanValidator(self.registry).validate(
            InvestigationPlan(steps=steps), self.definitions.values()
        )
        self.assertTrue(result.valid, result.errors)
        return result.validated_plan

    def _incident(self, evidence_id, reference="incident-1"):
        return Evidence(
            evidence_id=evidence_id,
            source=EvidenceSource.INCIDENT,
            kind=EvidenceKind.INCIDENT,
            provenance=EvidenceProvenance(source_reference=evidence_id, retrieved_at=self.timestamp),
            content=IncidentEvidenceContent(
                incident_reference=reference, started_at=self.timestamp
            ),
        )

    def _deployment(self, evidence_id="deployment-1"):
        return Evidence(
            evidence_id=evidence_id,
            source=EvidenceSource.DEPLOYMENT,
            kind=EvidenceKind.DEPLOYMENT,
            provenance=EvidenceProvenance(source_reference=evidence_id, retrieved_at=self.timestamp),
            content=DeploymentEvidenceContent(
                deployment_reference="deployment-1",
                service="checkout",
                environment="production",
                commit_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                deployed_at=self.timestamp - timedelta(minutes=5),
            ),
        )

    @staticmethod
    def _observed(tool_id, *evidence):
        return ToolResult(tool_id=tool_id, outcome=ToolOutcome.OBSERVED, evidence=evidence)

    async def test_chain_resolves_runtime_reference_and_constructs_typed_input(self):
        plan = self._validated(
            PlanStep(
                step_id="s1", tool_id="get_deployments", reason="find deployment",
                arguments=(PlanArgument(name="deployment_reference", value=Literal(value="deployment-1")),),
            ),
            PlanStep(
                step_id="s2", tool_id="get_commit", reason="inspect deployed commit", depends_on=("s1",),
                arguments=(
                    PlanArgument(name="repository_owner", value=Literal(value="acme")),
                    PlanArgument(name="repository_name", value=Literal(value="checkout")),
                    PlanArgument(name="commit_sha", value=StepOutputRef(step_id="s1", field="commit_sha")),
                ),
            ),
        )
        invoker = RecordingInvoker({
            InvestigationToolId.GET_DEPLOYMENTS: self._observed(InvestigationToolId.GET_DEPLOYMENTS, self._deployment()),
            InvestigationToolId.GET_COMMIT: ToolResult(tool_id=InvestigationToolId.GET_COMMIT, outcome=ToolOutcome.EMPTY),
        })

        state = await AgentExecutor(self.registry, invoker).execute(plan, budget=ExecutionBudget(max_tool_calls=5))

        self.assertEqual([call[0] for call in invoker.calls], [InvestigationToolId.GET_DEPLOYMENTS, InvestigationToolId.GET_COMMIT])
        self.assertEqual(invoker.calls[1][1]["commit_sha"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual([item.status for item in state.step_states], [ExecutionStepStatus.SUCCEEDED, ExecutionStepStatus.SUCCEEDED])

    async def test_branching_plan_continues_after_unrelated_failure_and_blocks_descendants(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_incident", reason="first", arguments=(PlanArgument(name="incident_reference", value=Literal(value="one")),)),
            PlanStep(step_id="s2", tool_id="get_incident", reason="dependent", depends_on=("s1",), arguments=(PlanArgument(name="incident_reference", value=StepOutputRef(step_id="s1", field="incident_reference")),)),
            PlanStep(step_id="s3", tool_id="get_incident", reason="transitive", depends_on=("s2",), arguments=(PlanArgument(name="incident_reference", value=StepOutputRef(step_id="s2", field="incident_reference")),)),
            PlanStep(step_id="s4", tool_id="get_incident", reason="independent", arguments=(PlanArgument(name="incident_reference", value=Literal(value="four")),)),
        )
        invoker = RecordingInvoker({
            InvestigationToolId.GET_INCIDENT: ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.FAILED, failure=ToolFailure(code=ToolFailureCode.SOURCE_FAILURE, message="source failed")),
        })

        state = await AgentExecutor(self.registry, invoker).execute(plan, budget=ExecutionBudget(max_tool_calls=5))

        self.assertEqual([item.status for item in state.step_states], [ExecutionStepStatus.FAILED, ExecutionStepStatus.BLOCKED, ExecutionStepStatus.BLOCKED, ExecutionStepStatus.FAILED])
        self.assertEqual([item.block_reason for item in state.step_states[1:3]], [ExecutionBlockReason.DEPENDENCY_FAILED, ExecutionBlockReason.DEPENDENCY_FAILED])
        self.assertEqual(len(invoker.calls), 2)
        self.assertEqual(len(state.missing_information), 2)

    async def test_full_evidence_set_is_rederived_deduplicated_and_repeatable(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_deployments", reason="deployment", arguments=(PlanArgument(name="deployment_reference", value=Literal(value="deployment-1")),)),
            PlanStep(step_id="s2", tool_id="get_incident", reason="incident", arguments=(PlanArgument(name="incident_reference", value=Literal(value="incident-1")),)),
        )
        results = {
            InvestigationToolId.GET_DEPLOYMENTS: self._observed(InvestigationToolId.GET_DEPLOYMENTS, self._deployment(), self._deployment()),
            InvestigationToolId.GET_INCIDENT: self._observed(InvestigationToolId.GET_INCIDENT, self._incident("incident-1")),
        }

        first = await AgentExecutor(self.registry, RecordingInvoker(results)).execute(plan, budget=ExecutionBudget(max_tool_calls=5))
        second = await AgentExecutor(self.registry, RecordingInvoker(results)).execute(plan, budget=ExecutionBudget(max_tool_calls=5))

        self.assertEqual(len(first.evidence), 2)
        self.assertEqual(len(first.facts), 1)
        self.assertEqual(first.facts, second.facts)
        self.assertEqual(first.model_dump(), second.model_dump())

    async def test_empty_source_output_blocks_reference_consumer_without_a_call(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_incident", reason="source", arguments=(PlanArgument(name="incident_reference", value=Literal(value="one")),)),
            PlanStep(step_id="s2", tool_id="get_incident", reason="consumer", depends_on=("s1",), arguments=(PlanArgument(name="incident_reference", value=StepOutputRef(step_id="s1", field="incident_reference")),)),
        )
        invoker = RecordingInvoker({InvestigationToolId.GET_INCIDENT: ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.EMPTY)})

        state = await AgentExecutor(self.registry, invoker).execute(plan, budget=ExecutionBudget(max_tool_calls=5))

        self.assertEqual(len(invoker.calls), 1)
        self.assertEqual(state.step_states[1].status, ExecutionStepStatus.BLOCKED)
        self.assertEqual(state.step_states[1].block_reason, ExecutionBlockReason.RUNTIME_OUTPUT_UNAVAILABLE)

    async def test_budget_blocks_remaining_steps_and_preserves_partial_evidence(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_incident", reason="first", arguments=(PlanArgument(name="incident_reference", value=Literal(value="one")),)),
            PlanStep(step_id="s2", tool_id="get_incident", reason="second", arguments=(PlanArgument(name="incident_reference", value=Literal(value="two")),)),
            PlanStep(step_id="s3", tool_id="get_incident", reason="third", arguments=(PlanArgument(name="incident_reference", value=Literal(value="three")),)),
        )
        invoker = RecordingInvoker({InvestigationToolId.GET_INCIDENT: self._observed(InvestigationToolId.GET_INCIDENT, self._incident("incident-1"))})

        state = await AgentExecutor(self.registry, invoker).execute(plan, budget=ExecutionBudget(max_tool_calls=2))

        self.assertEqual(len(invoker.calls), 2)
        self.assertEqual(state.budget.used_tool_calls, 2)
        self.assertEqual(state.budget.remaining_tool_calls, 0)
        self.assertEqual(state.termination_reason, ExecutionTerminationReason.BUDGET_EXHAUSTED)
        self.assertEqual(state.step_states[2].block_reason, ExecutionBlockReason.BUDGET_EXHAUSTED)
        self.assertEqual(len(state.evidence), 1)

    async def test_failed_attempt_consumes_budget_but_blocked_dependency_does_not(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_incident", reason="fails", arguments=(PlanArgument(name="incident_reference", value=Literal(value="one")),)),
            PlanStep(step_id="s2", tool_id="get_incident", reason="blocked", depends_on=("s1",), arguments=(PlanArgument(name="incident_reference", value=StepOutputRef(step_id="s1", field="incident_reference")),)),
        )
        invoker = RecordingInvoker({InvestigationToolId.GET_INCIDENT: ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.FAILED, failure=ToolFailure(code=ToolFailureCode.SOURCE_FAILURE, message="source failed"))})

        state = await AgentExecutor(self.registry, invoker).execute(plan, budget=ExecutionBudget(max_tool_calls=2))

        self.assertEqual(len(invoker.calls), 1)
        self.assertEqual(state.budget.used_tool_calls, 1)
        self.assertEqual(state.step_states[1].status, ExecutionStepStatus.BLOCKED)
        self.assertEqual(state.termination_reason, ExecutionTerminationReason.COMPLETED)

    async def test_retryable_failure_retries_with_exponential_backoff_and_consumes_budget(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_incident", reason="retrieve", arguments=(PlanArgument(name="incident_reference", value=Literal(value="one")),)),
        )
        invoker = RecordingInvoker({
            InvestigationToolId.GET_INCIDENT: [
                ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.FAILED, failure=ToolFailure(code=ToolFailureCode.RATE_LIMITED, message="rate limited")),
                self._observed(InvestigationToolId.GET_INCIDENT, self._incident("incident-1")),
            ],
        })
        sleeper = RecordingSleeper()

        state = await AgentExecutor(self.registry, invoker, sleep=sleeper).execute(
            plan, budget=ExecutionBudget(max_tool_calls=3)
        )

        self.assertEqual(len(invoker.calls), 2)
        self.assertEqual(sleeper.delays, [1.0])
        self.assertEqual(state.budget.used_tool_calls, 2)
        self.assertEqual(state.step_states[0].attempts, 2)
        self.assertEqual(state.step_states[0].status, ExecutionStepStatus.SUCCEEDED)

    async def test_non_retryable_failure_stops_after_one_attempt(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_incident", reason="retrieve", arguments=(PlanArgument(name="incident_reference", value=Literal(value="one")),)),
        )
        invoker = RecordingInvoker({
            InvestigationToolId.GET_INCIDENT: ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.FAILED, failure=ToolFailure(code=ToolFailureCode.NOT_FOUND, message="not found")),
        })
        sleeper = RecordingSleeper()

        state = await AgentExecutor(self.registry, invoker, sleep=sleeper).execute(
            plan, budget=ExecutionBudget(max_tool_calls=3)
        )

        self.assertEqual(len(invoker.calls), 1)
        self.assertEqual(sleeper.delays, [])
        self.assertEqual(state.budget.used_tool_calls, 1)
        self.assertEqual(state.step_states[0].attempts, 1)
        self.assertEqual(state.step_states[0].status, ExecutionStepStatus.FAILED)

    async def test_retry_attempts_stop_after_three_total_calls(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_incident", reason="retrieve", arguments=(PlanArgument(name="incident_reference", value=Literal(value="one")),)),
        )
        retryable_failure = ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.FAILED, failure=ToolFailure(code=ToolFailureCode.TIMEOUT, message="timed out"))
        invoker = RecordingInvoker({InvestigationToolId.GET_INCIDENT: [retryable_failure] * 3})
        sleeper = RecordingSleeper()

        state = await AgentExecutor(self.registry, invoker, sleep=sleeper).execute(
            plan, budget=ExecutionBudget(max_tool_calls=5)
        )

        self.assertEqual(len(invoker.calls), 3)
        self.assertEqual(sleeper.delays, [1.0, 2.0])
        self.assertEqual(state.budget.used_tool_calls, 3)
        self.assertEqual(state.step_states[0].attempts, 3)
        self.assertEqual(state.step_states[0].status, ExecutionStepStatus.FAILED)

    async def test_budget_exhaustion_stops_a_pending_retry_and_blocks_later_work(self):
        plan = self._validated(
            PlanStep(step_id="s1", tool_id="get_incident", reason="first", arguments=(PlanArgument(name="incident_reference", value=Literal(value="one")),)),
            PlanStep(step_id="s2", tool_id="get_incident", reason="second", arguments=(PlanArgument(name="incident_reference", value=Literal(value="two")),)),
        )
        invoker = RecordingInvoker({
            InvestigationToolId.GET_INCIDENT: ToolResult(tool_id=InvestigationToolId.GET_INCIDENT, outcome=ToolOutcome.FAILED, failure=ToolFailure(code=ToolFailureCode.UPSTREAM_UNAVAILABLE, message="unavailable")),
        })
        sleeper = RecordingSleeper()

        state = await AgentExecutor(self.registry, invoker, sleep=sleeper).execute(
            plan, budget=ExecutionBudget(max_tool_calls=1)
        )

        self.assertEqual(len(invoker.calls), 1)
        self.assertEqual(sleeper.delays, [])
        self.assertEqual(state.budget.used_tool_calls, 1)
        self.assertEqual(state.step_states[0].attempts, 1)
        self.assertEqual(state.step_states[1].block_reason, ExecutionBlockReason.BUDGET_EXHAUSTED)
        self.assertEqual(state.termination_reason, ExecutionTerminationReason.BUDGET_EXHAUSTED)


if __name__ == "__main__":
    unittest.main()

import asyncio
import unittest
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.explanations import (
    FakeLLMClient,
    LLMProviderErrorDetails,
    LLMProviderName,
    LLMStructuredResponse,
)
from app.investigations.hypotheses import (
    CandidateHypothesis,
    GroundedInvestigationResult,
    GroundedTerminationReason,
    HypothesisGenerationError,
    HypothesisGenerationFailureCode,
    HypothesisGenerationInput,
    HypothesisKind,
    TypedLLMHypothesisGenerator,
)
from app.investigations.models import InvestigationRequest
from app.investigations.planning import InvestigationPlan, Literal, PlanArgument, PlanStep
from app.investigations.replanning import (
    AdaptiveInvestigationRuntime,
    AdaptiveInvestigationState,
    ContinuationReason,
)
from app.tools import InvestigationToolId
from app.runtime import (
    InMemoryFactRecurrenceRepository,
    InMemoryRunRepository,
    RunStateConflictError,
    RunStatus,
)
from app.runtime.investigation_models import (
    ExecutionState,
    InvestigationPlanningRoundSnapshot,
    InvestigationRun,
    InvestigationRuntimeSnapshot,
    WorkingMemory,
)
from app.workflows.investigation import (
    INVESTIGATION_WORKFLOW_NAME,
    INVESTIGATION_WORKFLOW_VERSION,
    InvestigationWorkflowService,
    _code_diagnosis_failure_diagnostics,
    _hypothesis_failure_diagnostics,
)
from app.investigations.code_diagnosis import (
    CodeContextBuilder,
    CodeDiagnosisError,
    CodeDiagnosisFailureCode,
    TypedLLMCodeDiagnoser,
)


class SequentialPlannerClient:
    provider = LLMProviderName.FAKE
    model = "sequential-planner-test-double"

    def __init__(self, plans):
        self.plans = list(plans)
        self.inputs = []

    async def generate_typed(self, request):
        self.inputs.append(request.input)
        return LLMStructuredResponse(output=self.plans.pop(0).model_dump(mode="json"))


def incident_plan(reference: str) -> InvestigationPlan:
    return InvestigationPlan(
        steps=(PlanStep(
            step_id="s1",
            tool_id=InvestigationToolId.GET_INCIDENT,
            reason="Collect incident evidence.",
            arguments=(PlanArgument(name="incident_reference", value=Literal(value=reference)),),
        ),)
    )


def hypothesis_plan() -> InvestigationPlan:
    return InvestigationPlan(steps=(
        PlanStep(step_id="s1", tool_id=InvestigationToolId.GET_INCIDENT, reason="Collect incident evidence.", arguments=(PlanArgument(name="incident_reference", value=Literal(value="incident:checkout-500")),)),
        PlanStep(step_id="s2", tool_id=InvestigationToolId.GET_FAILURE_LOCATION, reason="Collect failure location evidence.", arguments=(PlanArgument(name="incident_reference", value=Literal(value="incident:checkout-500")),)),
        PlanStep(step_id="s3", tool_id=InvestigationToolId.GET_DIFF, reason="Collect changed file evidence.", arguments=(PlanArgument(name="repository_owner", value=Literal(value="octo-org")), PlanArgument(name="repository_name", value=Literal(value="analytics")), PlanArgument(name="pr_number", value=Literal(value=42)))),
    ))


class InvestigationWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_code_diagnosis_failure_diagnostics_are_allowlisted(self):
        completed = await self._completed_fake_context()
        diagnosis_input = CodeContextBuilder().build(
            completed.request,
            completed.state.working_memory.validated_hypotheses,
            completed.state.working_memory.facts,
            completed.state.working_memory.evidence_content,
        )
        diagnostics = _code_diagnosis_failure_diagnostics(
            TypedLLMCodeDiagnoser(FakeLLMClient()),
            diagnosis_input,
            CodeDiagnosisError(CodeDiagnosisFailureCode.PROVIDER_FAILURE),
        )

        self.assertEqual(
            diagnostics["event"],
            "investigation.code_diagnosis.failed",
        )
        self.assertEqual(diagnostics["hypothesis_count"], 1)
        self.assertNotIn(completed.request.question, str(diagnostics))
        self.assertNotIn("services/checkout.py", str(diagnostics))

    def test_hypothesis_failure_diagnostics_are_allowlisted(self):
        diagnostics = _hypothesis_failure_diagnostics(
            TypedLLMHypothesisGenerator(FakeLLMClient()),
            HypothesisGenerationInput(
                investigation_goal="private investigation goal",
                facts=(),
            ),
            HypothesisGenerationError(
                HypothesisGenerationFailureCode.PROVIDER_FAILURE,
                provider_details=LLMProviderErrorDetails(
                    http_status=400,
                    provider_code="json_validate_failed",
                    provider_message="Sanitized provider message.",
                    failed_generation_present=True,
                    failed_generation_length=123,
                ),
                provider_failure_category="invalid_structured_response",
            ),
        )

        self.assertEqual(diagnostics["event"], "investigation.hypothesis.failed")
        self.assertEqual(diagnostics["http_status"], 400)
        self.assertEqual(diagnostics["provider_code"], "json_validate_failed")
        self.assertEqual(diagnostics["failed_generation_length"], 123)
        self.assertNotIn("private investigation goal", str(diagnostics))

    async def test_validated_hypothesis_reaches_only_deterministic_grounded_result(self):
        class HypothesisClient(FakeLLMClient):
            async def generate_typed(self, request):
                facts = request.input.facts
                changed = next(fact for fact in facts if fact.fact_type == "changed_file")
                failure = next(
                    fact
                    for fact in facts
                    if fact.fact_type == "changed_file_matches_failure_file"
                )
                candidate = CandidateHypothesis(
                    hypothesis_id="H_CODE_CHANGE",
                    kind=HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED,
                    subject=changed.path,
                    supporting_fact_ids=(changed.fact_id, failure.fact_id),
                    rationale="This provider rationale must not reach the result.",
                )
                return LLMStructuredResponse(
                    output={"candidates": [candidate.model_dump(mode="json")]}
                )

        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(
            repository,
            HypothesisClient(),
            planner_client=SequentialPlannerClient((hypothesis_plan(), hypothesis_plan())),
        )
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why did checkout failures increase?",
                incident_reference="incident:checkout-500",
                pull_request_number=42,
            )
        )

        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(len(completed.state.working_memory.validated_hypotheses), 1)
        self.assertIsNotNone(completed.state.execution_state.hypothesis_generation_metadata)
        self.assertTrue(completed.state.working_memory.action_history)
        self.assertTrue(
            all(
                round.planner_metadata is not None
                for round in completed.state.execution_state.rounds
            )
        )
        self.assertEqual(len(completed.results[-1].supported_hypotheses), 1)
        rendered_hypothesis = completed.results[-1].supported_hypotheses[0]
        self.assertIn("may have contributed", rendered_hypothesis.statement)
        self.assertNotIn("provider rationale", completed.results[-1].model_dump_json())


        self.assertEqual(
            rendered_hypothesis.connected_fact_chain,
            (rendered_hypothesis.supporting_fact_ids[1],),
        )

    async def test_code_diagnosis_failure_preserves_grounded_hypothesis(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(
            repository,
            FakeLLMClient(),
            planner_client=SequentialPlannerClient(
                (hypothesis_plan(), hypothesis_plan())
            ),
            code_diagnosis_client=FakeLLMClient(
                typed_output={"candidates": [{"invented": True}]}
            ),
        )
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why did checkout fail?",
                incident_reference="incident:checkout-500",
                pull_request_number=42,
            )
        )

        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertEqual(len(completed.results[-1].supported_hypotheses), 1)
        self.assertEqual(completed.results[-1].code_findings, ())
        self.assertEqual(completed.results[-1].recommendations, ())
        self.assertEqual(
            completed.results[-1].termination_reason,
            "code_diagnosis_failure",
        )

    async def test_unexpected_post_processing_error_terminally_fails_run(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(
            repository,
            FakeLLMClient(),
            planner_client=SequentialPlannerClient(
                (hypothesis_plan(), hypothesis_plan())
            ),
        )
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why did checkout fail?",
                incident_reference="incident:checkout-500",
                pull_request_number=42,
            )
        )

        with patch(
            "app.workflows.investigation.render_grounded_result",
            side_effect=RuntimeError("private internal detail"),
        ):
            failed = await workflow.continue_persisted_run(pending)

        self.assertEqual(failed.status, RunStatus.FAILED)
        self.assertEqual(failed.error.code, "investigation_runtime_failure")
        self.assertNotIn("private internal detail", failed.error.message)
        self.assertIs(repository.get(failed.run_id), failed)

    async def test_cancellation_mid_run_marks_the_run_cancelled_not_stuck_running(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(
            repository,
            FakeLLMClient(),
            planner_client=SequentialPlannerClient((incident_plan("incident:checkout-500"),)),
        )
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why did checkout failures increase?",
                incident_reference="incident:checkout-500",
            )
        )


        async def cancelled_after_round_two(
            self,
            investigation_goal,
            allowed_tools,
            *,
            budget,
            initial_evidence=(),
            initial_missing_information=(),
            initial_rounds=0,
            prior_result_summary=None,
            request_context=None,
            on_round_planned=None,
            on_round_completed=None,
        ):
            two_rounds_in = AdaptiveInvestigationState(
                rounds=(),
                evidence=(),
                facts=(),
                missing_information=(),
                action_history=(),
                remaining_tool_calls=budget.max_tool_calls,
                continuation_reason=ContinuationReason.IN_PROGRESS,
            )
            await on_round_completed(two_rounds_in)
            raise asyncio.CancelledError()

        with patch.object(
            AdaptiveInvestigationRuntime, "investigate", cancelled_after_round_two
        ):
            with self.assertRaises(asyncio.CancelledError):
                await workflow.continue_persisted_run(pending)

        stored = repository.get(pending.run_id)
        self.assertEqual(stored.status, RunStatus.CANCELLED)
        self.assertIsNotNone(stored.started_at)
        self.assertIsNotNone(stored.completed_at)
        self.assertEqual(stored.results, ())

    async def test_persisted_investigation_reuses_snapshot_repository_and_renders_result(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(
            repository,
            FakeLLMClient(),
            planner_client=SequentialPlannerClient((incident_plan("incident:checkout-500"), incident_plan("incident:checkout-500"))),
        )
        request = InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout failures increase?",
            incident_reference="incident:checkout-500",
            deployment_reference="deployment:1042",
            pull_request_number=42,
        )

        pending = await workflow.create_persisted_run(request)
        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(pending.status, RunStatus.PENDING)
        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertIsNotNone(completed.state)
        self.assertEqual(len(completed.state.execution_state.rounds), 2)
        self.assertGreater(len(completed.state.working_memory.evidence), 0)
        self.assertTrue(completed.results)
        self.assertEqual(completed.results[-1].supported_hypotheses, ())
        self.assertIn("not sufficient", completed.results[-1].summary)
        self.assertIs(repository.get(completed.run_id), completed)

    async def test_second_adaptive_round_receives_first_round_state(self):
        repository = InMemoryRunRepository()
        planner = SequentialPlannerClient(
            (hypothesis_plan(), hypothesis_plan())
        )
        workflow = InvestigationWorkflowService(
            repository,
            FakeLLMClient(),
            planner_client=planner,
        )
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why did checkout failures increase?",
                incident_reference="incident:checkout-500",
            )
        )

        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual([item.planning_round for item in planner.inputs], [1, 2])
        self.assertEqual(
            planner.inputs[0].investigation_goal,
            "Why did checkout failures increase?",
        )
        self.assertEqual(planner.inputs[0].facts, ())
        self.assertEqual(planner.inputs[0].evidence, ())
        self.assertGreater(len(planner.inputs[1].facts), 0)
        self.assertGreater(len(planner.inputs[1].evidence), 0)
        self.assertGreater(len(planner.inputs[1].action_history), 0)
        self.assertLess(
            planner.inputs[1].remaining_tool_calls,
            planner.inputs[0].remaining_tool_calls,
        )
        self.assertEqual(planner.inputs[0].allowed_tools, planner.inputs[1].allowed_tools)
        self.assertEqual(completed.state.execution_state.termination_reason, "no_progress")
        self.assertFalse(completed.state.working_memory.action_history[0].produced_new_facts)

    async def test_round_boundaries_are_persisted_before_the_final_result(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(
            repository,
            FakeLLMClient(),
            planner_client=SequentialPlannerClient(
                (incident_plan("incident:checkout-500"), incident_plan("incident:checkout-500"))
            ),
        )
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why did checkout failures increase?",
                incident_reference="incident:checkout-500",
            )
        )

        completed = await workflow.continue_persisted_run(pending)

        snapshots = [run.state for run in repository.history if run.state is not None]
        self.assertEqual(snapshots[0].execution_state.rounds, ())
        self.assertFalse(snapshots[1].execution_state.rounds[0].completed)
        self.assertTrue(snapshots[2].execution_state.rounds[0].completed)
        self.assertFalse(snapshots[3].execution_state.rounds[1].completed)
        self.assertTrue(snapshots[4].execution_state.rounds[0].completed)
        self.assertTrue(snapshots[4].execution_state.rounds[1].completed)
        self.assertEqual(completed, repository.history[-1])

    async def test_planner_failure_keeps_the_last_completed_round(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(
            repository,
            FakeLLMClient(),
            planner_client=SequentialPlannerClient((incident_plan("incident:checkout-500"),)),
        )
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why did checkout failures increase?",
                incident_reference="incident:checkout-500",
            )
        )

        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertEqual(completed.state.execution_state.termination_reason, "planner_failure")
        self.assertEqual(len(completed.state.execution_state.rounds), 1)
        self.assertTrue(completed.state.execution_state.rounds[0].completed)
        self.assertGreater(len(completed.state.working_memory.evidence), 0)

    def test_missing_structured_sources_is_rejected_before_construction(self):
        with self.assertRaises(ValidationError):
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why is the service unhealthy?",
            )

    async def _completed_fake_context(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(repository, FakeLLMClient())
        request = InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout fail?",
            incident_reference="incident:checkout-500",
            pull_request_number=42,
        )
        pending = await workflow.create_persisted_run(request)
        return await workflow.continue_persisted_run(pending)


class InvestigationFollowUpTests(unittest.IsolatedAsyncioTestCase):
    def _request(self) -> InvestigationRequest:
        return InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout failures increase?",
            incident_reference="incident:checkout-500",
        )

    async def test_follow_up_reuses_remaining_budget_and_continues_round_numbers(self):
        repository = InMemoryRunRepository()
        planner = SequentialPlannerClient((incident_plan("incident:checkout-500"),) * 3)
        workflow = InvestigationWorkflowService(
            repository, FakeLLMClient(), planner_client=planner
        )
        pending = await workflow.create_persisted_run(self._request())
        completed = await workflow.continue_persisted_run(pending)


        self.assertEqual(len(completed.state.execution_state.rounds), 2)
        self.assertEqual(completed.state.execution_state.remaining_tool_calls, 8)
        self.assertEqual(len(completed.results), 1)

        reopened = await workflow.reopen_for_follow_up(completed)
        self.assertEqual(reopened.status, RunStatus.RUNNING)
        self.assertEqual(reopened.follow_up_count, 1)

        follow_up_completed = await workflow.continue_persisted_run(
            reopened, follow_up_question="What about the deployment?"
        )

        self.assertEqual(follow_up_completed.status, RunStatus.COMPLETED)
        rounds = follow_up_completed.state.execution_state.rounds
        self.assertEqual([round.round_number for round in rounds], [1, 2, 3])


        self.assertEqual(follow_up_completed.state.execution_state.remaining_tool_calls, 7)
        self.assertEqual(planner.inputs[2].remaining_tool_calls, 8)
        self.assertEqual(planner.inputs[2].planning_round, 3)
        self.assertEqual(planner.inputs[2].investigation_goal, "What about the deployment?")


        self.assertEqual(len(follow_up_completed.results), 2)
        self.assertEqual(follow_up_completed.results[0], completed.results[0])
        self.assertEqual(repository.get(completed.run_id), follow_up_completed)

    async def test_follow_up_on_an_exhausted_budget_case_completes_with_zero_new_tool_calls(
        self,
    ) -> None:
        repository = InMemoryRunRepository()


        planner = SequentialPlannerClient(())
        workflow = InvestigationWorkflowService(
            repository, FakeLLMClient(), planner_client=planner
        )
        now = datetime.now(UTC)
        exhausted_round = InvestigationPlanningRoundSnapshot(
            round_number=1,
            plan_id="round-1",
            plan_validation_status="accepted",
            completed=True,
        )
        exhausted = InvestigationRun(
            run_id=uuid4(),
            workflow_name=INVESTIGATION_WORKFLOW_NAME,
            workflow_version=INVESTIGATION_WORKFLOW_VERSION,
            status=RunStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            error=None,
            request=self._request(),
            state=InvestigationRuntimeSnapshot(
                working_memory=WorkingMemory(),
                execution_state=ExecutionState(
                    rounds=(exhausted_round,),
                    max_tool_calls=10,
                    used_tool_calls=10,
                    remaining_tool_calls=0,
                    termination_reason="tool_call_budget_exhausted",
                ),
            ),
            results=(
                GroundedInvestigationResult(
                    termination_reason=GroundedTerminationReason.BUDGET_EXHAUSTED,
                    summary="Investigation stopped: tool-call budget exhausted.",
                ),
            ),
        )
        repository.save(exhausted)

        reopened = await workflow.reopen_for_follow_up(exhausted)
        follow_up_completed = await workflow.continue_persisted_run(
            reopened, follow_up_question="Anything else in the logs?"
        )

        self.assertEqual(follow_up_completed.status, RunStatus.COMPLETED)
        self.assertEqual(len(follow_up_completed.results), 2)
        self.assertEqual(
            follow_up_completed.state.execution_state.rounds, (exhausted_round,)
        )
        self.assertEqual(follow_up_completed.state.execution_state.remaining_tool_calls, 0)
        self.assertEqual(follow_up_completed.state.execution_state.used_tool_calls, 10)

    async def test_follow_up_does_not_double_record_an_already_recorded_fact_type(self):
        repository = InMemoryRunRepository()
        fact_recurrence_repository = InMemoryFactRecurrenceRepository()
        planner = SequentialPlannerClient((hypothesis_plan(), hypothesis_plan(), hypothesis_plan()))
        workflow = InvestigationWorkflowService(
            repository,
            FakeLLMClient(),
            planner_client=planner,
            fact_recurrence_repository=fact_recurrence_repository,
        )
        request = InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout fail?",
            incident_reference="incident:checkout-500",
            pull_request_number=42,
        )
        pending = await workflow.create_persisted_run(request)
        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(
            set(completed.recorded_fact_types),
            {"changed_file", "changed_file_matches_failure_file"},
        )
        recorded_before = fact_recurrence_repository.get(
            "octo-org", "analytics", "changed_file"
        )
        self.assertEqual(recorded_before.occurrence_count, 1)

        reopened = await workflow.reopen_for_follow_up(completed)
        follow_up_completed = await workflow.continue_persisted_run(
            reopened, follow_up_question="What else changed in that PR?"
        )


        recorded_after = fact_recurrence_repository.get(
            "octo-org", "analytics", "changed_file"
        )
        self.assertEqual(recorded_after.occurrence_count, 1)
        self.assertEqual(
            set(follow_up_completed.recorded_fact_types),
            set(completed.recorded_fact_types),
        )

    async def test_reopen_for_follow_up_rejects_a_run_that_is_not_completed(self) -> None:
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(repository, FakeLLMClient())
        pending = await workflow.create_persisted_run(self._request())

        with self.assertRaises(RunStateConflictError):
            await workflow.reopen_for_follow_up(pending)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from app.explanations import (
    FakeLLMClient,
    LLMProviderErrorDetails,
    LLMProviderName,
    LLMStructuredResponse,
)
from app.investigations.hypotheses import (
    CandidateHypothesis,
    HypothesisGenerationError,
    HypothesisGenerationFailureCode,
    HypothesisGenerationInput,
    HypothesisKind,
    TypedLLMHypothesisGenerator,
)
from app.investigations.models import InvestigationRequest
from app.investigations.planning import InvestigationPlan, Literal, PlanArgument, PlanStep
from app.tools import InvestigationToolId
from app.runtime import InMemoryRunRepository, RunStatus
from app.workflows.investigation import (
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
            completed.state.validated_hypotheses,
            completed.state.facts,
            completed.state.evidence_content,
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

        self.assertEqual(len(completed.state.validated_hypotheses), 1)
        self.assertIsNotNone(completed.state.hypothesis_generation_metadata)
        self.assertTrue(completed.state.action_history)
        self.assertTrue(
            all(round.planner_metadata is not None for round in completed.state.rounds)
        )
        self.assertEqual(len(completed.result.supported_hypotheses), 1)
        self.assertIn("may have contributed", completed.result.supported_hypotheses[0].statement)
        self.assertNotIn("provider rationale", completed.result.model_dump_json())

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
        self.assertEqual(len(completed.result.supported_hypotheses), 1)
        self.assertEqual(completed.result.code_findings, ())
        self.assertEqual(completed.result.recommendations, ())
        self.assertEqual(
            completed.result.termination_reason,
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
        self.assertEqual(len(completed.state.rounds), 2)
        self.assertGreater(len(completed.state.evidence), 0)
        self.assertIsNotNone(completed.result)
        self.assertEqual(completed.result.supported_hypotheses, ())
        self.assertIn("not sufficient", completed.result.summary)
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
        self.assertEqual(completed.state.termination_reason, "no_progress")
        self.assertFalse(completed.state.action_history[0].produced_new_facts)

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
        self.assertEqual(snapshots[0].rounds, ())
        self.assertFalse(snapshots[1].rounds[0].completed)
        self.assertTrue(snapshots[2].rounds[0].completed)
        self.assertFalse(snapshots[3].rounds[1].completed)
        self.assertTrue(snapshots[4].rounds[0].completed)
        self.assertTrue(snapshots[4].rounds[1].completed)
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
        self.assertEqual(completed.state.termination_reason, "planner_failure")
        self.assertEqual(len(completed.state.rounds), 1)
        self.assertTrue(completed.state.rounds[0].completed)
        self.assertGreater(len(completed.state.evidence), 0)

    async def test_missing_structured_sources_still_returns_insufficient_evidence(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(repository, FakeLLMClient())
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                question="Why is the service unhealthy?",
            )
        )

        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertEqual(completed.state.rounds, ())
        self.assertEqual(completed.state.evidence, ())
        self.assertEqual(completed.result.supported_hypotheses, ())

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


if __name__ == "__main__":
    unittest.main()

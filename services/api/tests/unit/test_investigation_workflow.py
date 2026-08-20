import unittest

from app.explanations import FakeLLMClient, LLMStructuredResponse
from app.investigations.hypotheses import CandidateHypothesis, HypothesisKind
from app.investigations.models import InvestigationRequest
from app.runtime import InMemoryRunRepository, RunStatus
from app.workflows.investigation import InvestigationWorkflowService


class InvestigationWorkflowTests(unittest.IsolatedAsyncioTestCase):
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
        workflow = InvestigationWorkflowService(repository, HypothesisClient())
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                incident_summary="Checkout failures increased.",
                incident_reference="incident:checkout-500",
                pull_request_number=42,
            )
        )

        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(len(completed.state.validated_hypotheses), 1)
        self.assertEqual(len(completed.result.supported_hypotheses), 1)
        self.assertIn("may have contributed", completed.result.supported_hypotheses[0].statement)
        self.assertNotIn("provider rationale", completed.result.model_dump_json())

    async def test_persisted_investigation_reuses_snapshot_repository_and_renders_result(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(repository, FakeLLMClient())
        request = InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            incident_summary="Checkout failures increased.",
            incident_reference="incident:checkout-500",
            deployment_reference="deployment:1042",
            pull_request_number=42,
        )

        pending = await workflow.create_persisted_run(request)
        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(pending.status, RunStatus.PENDING)
        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertIsNotNone(completed.state)
        self.assertEqual(len(completed.state.rounds), 1)
        self.assertGreater(len(completed.state.evidence), 0)
        self.assertIsNotNone(completed.result)
        self.assertEqual(completed.result.supported_hypotheses, ())
        self.assertIn("not sufficient", completed.result.summary)
        self.assertIs(repository.get(completed.run_id), completed)

    async def test_missing_structured_sources_still_returns_insufficient_evidence(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(repository, FakeLLMClient())
        pending = await workflow.create_persisted_run(
            InvestigationRequest(
                repository_owner="octo-org",
                repository_name="analytics",
                incident_summary="The service is unhealthy.",
            )
        )

        completed = await workflow.continue_persisted_run(pending)

        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertEqual(completed.state.rounds, ())
        self.assertEqual(completed.state.evidence, ())
        self.assertEqual(completed.result.supported_hypotheses, ())


if __name__ == "__main__":
    unittest.main()

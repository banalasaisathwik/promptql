import unittest

from pydantic import ValidationError

from app.connectors.github_code_fakes import (
    CHANGED_FILE_EVIDENCE_FIXTURES,
    FIXTURE_PULL_REQUEST,
)
from app.connectors.incident_fakes import (
    FAILURE_LOCATION_EVIDENCE_FIXTURES,
    FAILURE_LOCATION_REQUEST,
)
from app.explanations import FakeLLMClient
from app.investigations import (
    ChangedFileFact,
    ChangedFileMatchesFailureFileFact,
    InvestigationRequest,
)
from app.investigations.code_diagnosis import (
    CodeContextBuilder,
    CodeContextKind,
    CodeDiagnosisError,
    CodeDiagnosisFailureCode,
    CodeFindingCategory,
    CodeFindingValidationFailureCode,
    DeterministicCodeFindingValidator,
    DeveloperRecommendationCode,
    MAX_CODE_CONTEXT_LOCATIONS,
    MAX_CODE_LINES_PER_HUNK,
    SuspectedCodeFinding,
    TypedLLMCodeDiagnoser,
    build_developer_recommendations,
)
from app.investigations.fact_derivation import derive_facts
from app.investigations.hypotheses import (
    CandidateHypothesis,
    DeterministicHypothesisValidator,
    HypothesisKind,
)


EVIDENCE = (
    *CHANGED_FILE_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST],
    FAILURE_LOCATION_EVIDENCE_FIXTURES[FAILURE_LOCATION_REQUEST],
)
FACTS = derive_facts(EVIDENCE)
CHANGED_FACT = next(item for item in FACTS if isinstance(item, ChangedFileFact))
RELATIONSHIP_FACT = next(
    item for item in FACTS if isinstance(item, ChangedFileMatchesFailureFileFact)
)
HYPOTHESIS = DeterministicHypothesisValidator().validate(
    (
        CandidateHypothesis(
            hypothesis_id="hypothesis:checkout-change",
            kind=HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED,
            subject="services/checkout.py",
            supporting_fact_ids=(
                CHANGED_FACT.fact_id,
                RELATIONSHIP_FACT.fact_id,
            ),
        ),
    ),
    FACTS,
).accepted_hypotheses[0]
SUPPORTING_EVIDENCE_IDS = tuple(
    dict.fromkeys(
        evidence_id
        for fact in (CHANGED_FACT, RELATIONSHIP_FACT)
        for evidence_id in fact.evidence_reference_ids
    )
)
STACK_EVIDENCE_ID = EVIDENCE[-1].evidence_id
REQUEST = InvestigationRequest(
    repository_owner="octo-org",
    repository_name="analytics",
    question="Why did checkout requests fail?",
    incident_reference="incident:checkout-500",
    pull_request_number=42,
)


def _candidate(**updates) -> SuspectedCodeFinding:
    values = {
        "finding_id": "finding:checkout-null-path",
        "hypothesis_id": HYPOTHESIS.hypothesis_id,
        "file_path": "services/checkout.py",
        "location_evidence_id": STACK_EVIDENCE_ID,
        "category": CodeFindingCategory.ERROR_HANDLING_OR_NULL_PATH,
        "supporting_fact_ids": HYPOTHESIS.supporting_fact_ids,
        "supporting_evidence_ids": SUPPORTING_EVIDENCE_IDS,
        "explanation": "The observed null failure is in the changed file.",
    }
    values.update(updates)
    return SuspectedCodeFinding(**values)


class CodeContextBuilderTests(unittest.TestCase):
    def test_context_is_relevant_bounded_and_deterministic(self):
        builder = CodeContextBuilder()

        first = builder.build(REQUEST, (HYPOTHESIS,), FACTS, EVIDENCE)
        second = builder.build(REQUEST, (HYPOTHESIS,), FACTS, EVIDENCE)

        self.assertEqual(first, second)
        self.assertEqual(first.investigation_goal, REQUEST.question)
        self.assertEqual(
            {fact.fact_id for fact in first.facts},
            set(HYPOTHESIS.supporting_fact_ids),
        )
        self.assertEqual(
            first.support_bundles[0].supporting_evidence_ids,
            SUPPORTING_EVIDENCE_IDS,
        )
        self.assertEqual(
            {location.kind for location in first.locations},
            {
                CodeContextKind.CHANGED_FILE,
                CodeContextKind.DIFF_HUNK,
                CodeContextKind.STACK_FRAME,
            },
        )
        self.assertTrue(
            all(location.file_path == HYPOTHESIS.subject for location in first.locations)
        )

    def test_context_caps_locations_lines_and_line_width(self):
        changed_file = EVIDENCE[0]
        hunk = EVIDENCE[1]
        long_line = hunk.content.lines[1].model_copy(update={"text": "x" * 500})
        long_hunk = hunk.model_copy(
            update={
                "content": hunk.content.model_copy(
                    update={"lines": (long_line,) * 25, "new_count": 25}
                )
            }
        )
        repeated_files = tuple(
            changed_file.model_copy(update={"evidence_id": f"github:file:{index}"})
            for index in range(5)
        )
        repeated_frames = tuple(
            EVIDENCE[-1].model_copy(
                update={"evidence_id": f"incident:frame:{index}"}
            )
            for index in range(20)
        )

        result = CodeContextBuilder().build(
            REQUEST,
            (HYPOTHESIS,),
            FACTS,
            (*repeated_files, long_hunk, *repeated_frames),
        )

        self.assertEqual(len(result.locations), MAX_CODE_CONTEXT_LOCATIONS)
        hunk_location = next(
            location
            for location in result.locations
            if location.kind is CodeContextKind.DIFF_HUNK
        )
        self.assertEqual(len(hunk_location.lines), MAX_CODE_LINES_PER_HUNK)
        self.assertTrue(all(len(line.text) == 300 for line in hunk_location.lines))


class CodeFindingValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = DeterministicCodeFindingValidator()

    def _reason(self, candidate):
        result = self.validator.validate(
            (candidate,),
            (HYPOTHESIS,),
            FACTS,
            EVIDENCE,
        )
        self.assertEqual(result.accepted_findings, ())
        return result.rejected_candidates[0].reason

    def test_accepts_location_supported_by_hypothesis_facts_and_evidence(self):
        result = self.validator.validate(
            (_candidate(),),
            (HYPOTHESIS,),
            FACTS,
            EVIDENCE,
        )

        self.assertEqual(len(result.accepted_findings), 1)
        self.assertEqual(result.rejected_candidates, ())
        self.assertEqual(result.accepted_findings[0].line_number, 87)

    def test_rejects_fabricated_file(self):
        self.assertEqual(
            self._reason(_candidate(file_path="services/invented.py")),
            CodeFindingValidationFailureCode.FILE_MISMATCH,
        )

    def test_candidate_schema_cannot_represent_fabricated_coordinates(self):
        with self.assertRaises(ValidationError):
            _candidate(line_number=999, function_name="invented_function")

    def test_rejects_unknown_fact(self):
        self.assertEqual(
            self._reason(
                _candidate(
                    supporting_fact_ids=(
                        *HYPOTHESIS.supporting_fact_ids,
                        "fact:invented",
                    )
                )
            ),
            CodeFindingValidationFailureCode.UNKNOWN_SUPPORTING_FACT,
        )

    def test_rejects_incomplete_hypothesis_support(self):
        self.assertEqual(
            self._reason(
                _candidate(supporting_fact_ids=(CHANGED_FACT.fact_id,))
            ),
            CodeFindingValidationFailureCode.HYPOTHESIS_SUPPORT_MISMATCH,
        )

    def test_rejects_extra_evidence_outside_exact_fact_support(self):
        hunk_id = EVIDENCE[1].evidence_id
        self.assertEqual(
            self._reason(
                _candidate(
                    supporting_evidence_ids=(*SUPPORTING_EVIDENCE_IDS, hunk_id)
                )
            ),
            CodeFindingValidationFailureCode.EVIDENCE_RELATIONSHIP_MISMATCH,
        )

    def test_rejects_evidence_that_does_not_cover_selected_facts(self):
        self.assertEqual(
            self._reason(
                _candidate(
                    supporting_evidence_ids=(CHANGED_FACT.evidence_reference_ids[0],)
                )
            ),
            CodeFindingValidationFailureCode.EVIDENCE_RELATIONSHIP_MISMATCH,
        )

    def test_rejects_location_outside_support_bundle(self):
        self.assertEqual(
            self._reason(
                _candidate(
                    location_evidence_id=EVIDENCE[1].evidence_id,
                )
            ),
            CodeFindingValidationFailureCode.LOCATION_NOT_OBSERVED,
        )

    def test_rejects_duplicate_finding_identifier(self):
        result = self.validator.validate(
            (_candidate(), _candidate()),
            (HYPOTHESIS,),
            FACTS,
            EVIDENCE,
        )

        self.assertEqual(len(result.accepted_findings), 1)
        self.assertEqual(
            result.rejected_candidates[0].reason,
            CodeFindingValidationFailureCode.DUPLICATE_FINDING_ID,
        )


class CodeDiagnosisServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_client_proposes_candidate_then_validator_accepts_it(self):
        diagnosis_input = CodeContextBuilder().build(
            REQUEST,
            (HYPOTHESIS,),
            FACTS,
            EVIDENCE,
        )

        generated = await TypedLLMCodeDiagnoser(FakeLLMClient()).generate(
            diagnosis_input
        )
        validation = DeterministicCodeFindingValidator().validate(
            generated.candidates,
            (HYPOTHESIS,),
            FACTS,
            EVIDENCE,
        )

        self.assertEqual(generated.metadata.task, "code_diagnosis")
        self.assertEqual(len(validation.accepted_findings), 1)

    async def test_malformed_candidate_is_a_schema_failure(self):
        diagnosis_input = CodeContextBuilder().build(
            REQUEST,
            (HYPOTHESIS,),
            FACTS,
            EVIDENCE,
        )

        with self.assertRaises(CodeDiagnosisError) as raised:
            await TypedLLMCodeDiagnoser(
                FakeLLMClient(typed_output={"candidates": [{"invented": True}]})
            ).generate(diagnosis_input)

        self.assertEqual(
            raised.exception.code,
            CodeDiagnosisFailureCode.CANDIDATE_SCHEMA_INVALID,
        )


class DeveloperRecommendationTests(unittest.TestCase):
    def test_recommendations_are_deterministic_and_grounded(self):
        finding = DeterministicCodeFindingValidator().validate(
            (_candidate(),),
            (HYPOTHESIS,),
            FACTS,
            EVIDENCE,
        ).accepted_findings[0]

        first = build_developer_recommendations((finding,))
        second = build_developer_recommendations((finding,))

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(item.code for item in first),
            (
                DeveloperRecommendationCode.INSPECT_FAILURE_PATH,
                DeveloperRecommendationCode.VALIDATE_ERROR_HANDLING,
                DeveloperRecommendationCode.ADD_REGRESSION_TEST,
            ),
        )
        self.assertTrue(all(item.finding_id == finding.finding_id for item in first))
        self.assertTrue(
            all(item.supporting_fact_ids == finding.supporting_fact_ids for item in first)
        )
        self.assertNotIn(_candidate().explanation, " ".join(item.message for item in first))


if __name__ == "__main__":
    unittest.main()

import unittest

from app.connectors.github_code_fakes import FIXTURE_PULL_REQUEST
from app.investigations.planning import (
    InvestigationPlan,
    Literal,
    PlanArgument,
    PlanStep,
    PlanValidationFailureCode,
    PlanValidator,
    StepOutputRef,
)
from app.tools.models import TOOL_DEFINITIONS
from app.tools.registry import ToolRegistry


def _step(
    step_id: str,
    tool_id: str,
    arguments: tuple[PlanArgument, ...],
    depends_on: tuple[str, ...] = (),
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        tool_id=tool_id,
        arguments=arguments,
        depends_on=depends_on,
        reason="Collect bounded investigation evidence.",
    )


def _literal(name: str, value: object) -> PlanArgument:
    return PlanArgument(name=name, value=Literal(value=value))


def _valid_plan() -> InvestigationPlan:
    return InvestigationPlan(
        steps=(
            _step("s1", "get_deployments", (_literal("deployment_reference", "deploy-42"),)),
            _step(
                "s2",
                "get_commit",
                (
                    _literal("repository_owner", FIXTURE_PULL_REQUEST.repository_owner),
                    _literal("repository_name", "analytics"),
                    PlanArgument(
                        name="commit_sha",
                        value=StepOutputRef(step_id="s1", field="commit_sha"),
                    ),
                ),
                depends_on=("s1",),
            ),
        )
    )


class PlanValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = PlanValidator(ToolRegistry(TOOL_DEFINITIONS))

    def _codes(self, plan: InvestigationPlan, allowed_tools=TOOL_DEFINITIONS):
        return tuple(
            failure.code for failure in self.validator.validate(plan, allowed_tools).errors
        )

    def test_accepts_a_dependency_consistent_typed_reference(self) -> None:
        result = self.validator.validate(_valid_plan(), TOOL_DEFINITIONS)

        self.assertTrue(result.valid)
        self.assertEqual(result.validated_plan.topological_step_ids, ("s1", "s2"))
        self.assertEqual(result.errors, ())

    def test_rejects_duplicate_step_ids_after_schema_parsing(self) -> None:
        plan = InvestigationPlan(steps=(_valid_plan().steps[0], _valid_plan().steps[0]))

        self.assertIn(PlanValidationFailureCode.DUPLICATE_STEP_ID, self._codes(plan))

    def test_rejects_unknown_and_disallowed_tools(self) -> None:
        unknown = InvestigationPlan(
            steps=(_step("s1", "search_everything", (),),)
        )
        disallowed = InvestigationPlan(
            steps=(_valid_plan().steps[0],)
        )

        self.assertIn(PlanValidationFailureCode.UNKNOWN_TOOL, self._codes(unknown))
        self.assertIn(
            PlanValidationFailureCode.TOOL_NOT_ALLOWED,
            self._codes(disallowed, ()),
        )

    def test_rejects_missing_self_and_cyclic_dependencies(self) -> None:
        unknown_dependency = InvestigationPlan(
            steps=(_step("s1", "get_deployments", (_literal("deployment_reference", "d"),), ("s9",)),)
        )
        self_dependency = InvestigationPlan(
            steps=(_step("s1", "get_deployments", (_literal("deployment_reference", "d"),), ("s1",)),)
        )
        cycle = InvestigationPlan(
            steps=(
                _step("s1", "get_deployments", (_literal("deployment_reference", "d"),), ("s2",)),
                _step("s2", "get_incident", (_literal("incident_reference", "i"),), ("s1",)),
            )
        )

        self.assertIn(PlanValidationFailureCode.UNKNOWN_DEPENDENCY, self._codes(unknown_dependency))
        self.assertIn(PlanValidationFailureCode.SELF_DEPENDENCY, self._codes(self_dependency))
        self.assertIn(PlanValidationFailureCode.CYCLE_DETECTED, self._codes(cycle))

    def test_rejects_bad_references_without_emitting_a_partial_plan(self) -> None:
        missing_step = _valid_plan().model_copy(
            update={
                "steps": (
                    _valid_plan().steps[0],
                    _step(
                        "s2",
                        "get_commit",
                        (
                            _literal("repository_owner", "octo-org"),
                            _literal("repository_name", "analytics"),
                            PlanArgument(
                                name="commit_sha",
                                value=StepOutputRef(step_id="s9", field="commit_sha"),
                            ),
                        ),
                    ),
                )
            }
        )
        missing_dependency = _valid_plan().model_copy(
            update={"steps": (_valid_plan().steps[0], _valid_plan().steps[1].model_copy(update={"depends_on": ()}))}
        )

        result = self.validator.validate(missing_step, TOOL_DEFINITIONS)
        self.assertFalse(result.valid)
        self.assertIsNone(result.validated_plan)
        self.assertIn(PlanValidationFailureCode.UNKNOWN_OUTPUT_REFERENCE_STEP, self._codes(missing_step))
        self.assertIn(PlanValidationFailureCode.MISSING_REFERENCE_DEPENDENCY, self._codes(missing_dependency))

    def test_rejects_unknown_output_fields_and_incompatible_types(self) -> None:
        unknown_field = _valid_plan().model_copy(
            update={
                "steps": (
                    _valid_plan().steps[0],
                    _valid_plan().steps[1].model_copy(
                        update={
                            "arguments": (
                                _literal("repository_owner", "octo-org"),
                                _literal("repository_name", "analytics"),
                                PlanArgument(
                                    name="commit_sha",
                                    value=StepOutputRef(step_id="s1", field="database_password"),
                                ),
                            )
                        }
                    ),
                )
            }
        )
        incompatible = InvestigationPlan(
            steps=(
                _step(
                    "s1",
                    "get_diff",
                    (
                        _literal("repository_owner", "octo-org"),
                        _literal("repository_name", "analytics"),
                        _literal("pr_number", 42),
                    ),
                ),
                _step(
                    "s2",
                    "get_commit",
                    (
                        _literal("repository_owner", "octo-org"),
                        _literal("repository_name", "analytics"),
                        PlanArgument(name="commit_sha", value=StepOutputRef(step_id="s1", field="pr_number")),
                    ),
                    ("s1",),
                ),
            )
        )

        self.assertIn(PlanValidationFailureCode.UNKNOWN_OUTPUT_FIELD, self._codes(unknown_field))
        self.assertIn(PlanValidationFailureCode.REFERENCE_TYPE_MISMATCH, self._codes(incompatible))

    def test_reuses_tool_input_validation_for_invalid_literals_and_is_deterministic(self) -> None:
        invalid_literal = InvestigationPlan(
            steps=(_step("s1", "get_deployments", (_literal("deployment_reference", 42),)),)
        )

        first = self.validator.validate(invalid_literal, TOOL_DEFINITIONS)
        second = self.validator.validate(invalid_literal, TOOL_DEFINITIONS)
        self.assertEqual(first, second)
        self.assertIn(PlanValidationFailureCode.INVALID_LITERAL_ARGUMENT, self._codes(invalid_literal))


if __name__ == "__main__":
    unittest.main()

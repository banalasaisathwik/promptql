"""Deterministic static validation for typed investigation-plan proposals."""

from collections.abc import Iterable
from enum import StrEnum
from heapq import heappop, heappush
from typing import Any, Union, get_args, get_origin

from pydantic import ValidationError

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.planning.models import (
    MAX_PLAN_STEPS,
    InvestigationPlan,
    Literal,
    PlanFieldName,
    PlanStepIdentifier,
    StepOutputRef,
)
from app.tools.errors import UnknownToolError
from app.tools.models import ToolDefinition
from app.tools.registry import ToolRegistry


class PlanValidationFailureCode(StrEnum):
    PLAN_TOO_LARGE = "plan_too_large"
    DUPLICATE_STEP_ID = "duplicate_step_id"
    UNKNOWN_TOOL = "unknown_tool"
    TOOL_NOT_ALLOWED = "tool_not_allowed"
    UNKNOWN_DEPENDENCY = "unknown_dependency"
    SELF_DEPENDENCY = "self_dependency"
    CYCLE_DETECTED = "cycle_detected"
    UNKNOWN_ARGUMENT = "unknown_argument"
    MISSING_REQUIRED_ARGUMENT = "missing_required_argument"
    INVALID_LITERAL_ARGUMENT = "invalid_literal_argument"
    UNKNOWN_OUTPUT_REFERENCE_STEP = "unknown_output_reference_step"
    MISSING_REFERENCE_DEPENDENCY = "missing_reference_dependency"
    UNKNOWN_OUTPUT_FIELD = "unknown_output_field"
    REFERENCE_TYPE_MISMATCH = "reference_type_mismatch"


class PlanValidationFailure(ContractModel):
    code: PlanValidationFailureCode
    message: NonEmptyString
    step_id: PlanStepIdentifier | None = None
    tool_id: str | None = None
    dependency_step_id: PlanStepIdentifier | None = None
    source_step_id: PlanStepIdentifier | None = None
    field_name: PlanFieldName | None = None
    argument_name: PlanFieldName | None = None


class ValidatedPlan(ContractModel):
    # PURPOSE: Preserve the proposal unchanged while recording the deterministic
    # order that a future V2.9 executor may consume; this class never executes it.
    plan: InvestigationPlan
    topological_step_ids: tuple[PlanStepIdentifier, ...]


class PlanValidationResult(ContractModel):
    valid: bool
    validated_plan: ValidatedPlan | None = None
    errors: tuple[PlanValidationFailure, ...] = ()

    @classmethod
    def accepted(cls, plan: ValidatedPlan) -> "PlanValidationResult":
        return cls(valid=True, validated_plan=plan)

    @classmethod
    def rejected(
        cls, errors: list[PlanValidationFailure]
    ) -> "PlanValidationResult":
        return cls(valid=False, errors=tuple(errors))


def _annotation_is_compatible(source: Any, destination: Any) -> bool:
    """Accept exact annotations and a non-optional source for an optional input."""
    if source == destination:
        return True
    destination_origin = get_origin(destination)
    if destination_origin in (Union,):
        return any(_annotation_is_compatible(source, member) for member in get_args(destination))
    return False


class PlanValidator:
    """Validate an untrusted plan against registry metadata and caller policy."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def validate(
        self,
        plan: InvestigationPlan,
        allowed_tools: Iterable[ToolDefinition],
    ) -> PlanValidationResult:
        # FLOW: Check bounded identity and permission rules first, then build the
        # dependency graph, then inspect references against static contracts. Each
        # stage appends sanitized failures instead of throwing, so callers receive
        # one deterministic all-or-nothing result for the untrusted proposal.
        allowed_tool_ids = {definition.tool_id for definition in allowed_tools}
        failures: list[PlanValidationFailure] = []
        steps_by_id: dict[str, object] = {}

        if len(plan.steps) > MAX_PLAN_STEPS:
            failures.append(
                PlanValidationFailure(
                    code=PlanValidationFailureCode.PLAN_TOO_LARGE,
                    message="The plan exceeds the configured step limit.",
                )
            )

        for step in plan.steps:
            if step.step_id in steps_by_id:
                failures.append(
                    PlanValidationFailure(
                        code=PlanValidationFailureCode.DUPLICATE_STEP_ID,
                        message="Plan step identifiers must be unique.",
                        step_id=step.step_id,
                    )
                )
                continue
            steps_by_id[step.step_id] = step

        definitions_by_step_id: dict[str, ToolDefinition] = {}
        for step in plan.steps:
            try:
                definition = self._registry.get(step.tool_id)
            except UnknownToolError:
                failures.append(
                    PlanValidationFailure(
                        code=PlanValidationFailureCode.UNKNOWN_TOOL,
                        message="The plan names a tool that is not registered.",
                        step_id=step.step_id,
                        tool_id=step.tool_id,
                    )
                )
                continue
            definitions_by_step_id.setdefault(step.step_id, definition)
            if definition.tool_id not in allowed_tool_ids:
                failures.append(
                    PlanValidationFailure(
                        code=PlanValidationFailureCode.TOOL_NOT_ALLOWED,
                        message="The plan names a tool outside the allowed set.",
                        step_id=step.step_id,
                        tool_id=step.tool_id,
                    )
                )

        graph = {step_id: [] for step_id in steps_by_id}
        in_degree = {step_id: 0 for step_id in steps_by_id}
        for step in plan.steps:
            for dependency_step_id in step.depends_on:
                if dependency_step_id not in steps_by_id:
                    failures.append(
                        PlanValidationFailure(
                            code=PlanValidationFailureCode.UNKNOWN_DEPENDENCY,
                            message="A declared dependency does not name a plan step.",
                            step_id=step.step_id,
                            dependency_step_id=dependency_step_id,
                        )
                    )
                    continue
                if dependency_step_id == step.step_id:
                    failures.append(
                        PlanValidationFailure(
                            code=PlanValidationFailureCode.SELF_DEPENDENCY,
                            message="A plan step cannot depend on itself.",
                            step_id=step.step_id,
                            dependency_step_id=dependency_step_id,
                        )
                    )
                    continue
                graph[dependency_step_id].append(step.step_id)
                in_degree[step.step_id] += 1

        topological_step_ids = self._topological_order(graph, in_degree, plan)
        if topological_step_ids is None:
            failures.append(
                PlanValidationFailure(
                    code=PlanValidationFailureCode.CYCLE_DETECTED,
                    message="Plan dependencies must form an acyclic graph.",
                )
            )

        for step in plan.steps:
            definition = definitions_by_step_id.get(step.step_id)
            if definition is None:
                continue
            argument_names = {argument.name for argument in step.arguments}
            for field_name, field_info in definition.input_model.model_fields.items():
                if field_info.is_required() and field_name not in argument_names:
                    failures.append(
                        PlanValidationFailure(
                            code=PlanValidationFailureCode.MISSING_REQUIRED_ARGUMENT,
                            message="The step omits a required tool argument.",
                            step_id=step.step_id,
                            tool_id=step.tool_id,
                            argument_name=field_name,
                        )
                    )

            for argument in step.arguments:
                destination_field = definition.input_model.model_fields.get(argument.name)
                if destination_field is None:
                    failures.append(
                        PlanValidationFailure(
                            code=PlanValidationFailureCode.UNKNOWN_ARGUMENT,
                            message="The step names an argument outside the tool input contract.",
                            step_id=step.step_id,
                            tool_id=step.tool_id,
                            argument_name=argument.name,
                        )
                    )
                    continue
                if isinstance(argument.value, Literal):
                    self._validate_literal(step.step_id, step.tool_id, argument.name, argument.value, destination_field.rebuild_annotation(), failures)
                elif isinstance(argument.value, StepOutputRef):
                    self._validate_reference(
                        step,
                        argument.name,
                        argument.value,
                        destination_field.rebuild_annotation(),
                        steps_by_id,
                        definitions_by_step_id,
                        failures,
                    )

            if all(isinstance(argument.value, Literal) for argument in step.arguments):
                self._validate_literal_model(step, definition, failures)

        if failures:
            return PlanValidationResult.rejected(failures)
        assert topological_step_ids is not None
        return PlanValidationResult.accepted(
            ValidatedPlan(plan=plan, topological_step_ids=topological_step_ids)
        )

    @staticmethod
    def _topological_order(graph, in_degree, plan: InvestigationPlan):
        # Kahn's algorithm repeatedly removes nodes with no unmet dependencies.
        # Keeping original step positions in the heap makes equally-ready steps
        # deterministic without adding scheduling or parallel-execution semantics.
        step_position = {step.step_id: index for index, step in enumerate(plan.steps)}
        ready: list[tuple[int, str]] = []
        for step_id, degree in in_degree.items():
            if degree == 0:
                heappush(ready, (step_position[step_id], step_id))
        ordered: list[str] = []
        while ready:
            _, step_id = heappop(ready)
            ordered.append(step_id)
            for dependent_step_id in sorted(graph[step_id], key=step_position.__getitem__):
                in_degree[dependent_step_id] -= 1
                if in_degree[dependent_step_id] == 0:
                    heappush(ready, (step_position[dependent_step_id], dependent_step_id))
        return tuple(ordered) if len(ordered) == len(graph) else None

    @staticmethod
    def _validate_literal(step_id, tool_id, argument_name, literal, annotation, failures):
        from pydantic import TypeAdapter

        try:
            TypeAdapter(annotation).validate_python(literal.value)
        except ValidationError:
            failures.append(
                PlanValidationFailure(
                    code=PlanValidationFailureCode.INVALID_LITERAL_ARGUMENT,
                    message="A literal argument does not match the tool input contract.",
                    step_id=step_id,
                    tool_id=tool_id,
                    argument_name=argument_name,
                )
            )

    @staticmethod
    def _validate_literal_model(step, definition, failures):
        try:
            definition.validate_arguments(
                {argument.name: argument.value.value for argument in step.arguments}
            )
        except ValueError:
            failures.append(
                PlanValidationFailure(
                    code=PlanValidationFailureCode.INVALID_LITERAL_ARGUMENT,
                    message="Literal arguments do not satisfy the complete tool input contract.",
                    step_id=step.step_id,
                    tool_id=step.tool_id,
                )
            )

    @staticmethod
    def _validate_reference(step, argument_name, reference, destination_annotation, steps_by_id, definitions_by_step_id, failures):
        # A declared control dependency is separate from data flow: the reference
        # states what value is consumed, while `depends_on` states when it is safe
        # to consume it. V2.8 rejects disagreement rather than rewriting the plan.
        source_step = steps_by_id.get(reference.step_id)
        if source_step is None:
            failures.append(
                PlanValidationFailure(
                    code=PlanValidationFailureCode.UNKNOWN_OUTPUT_REFERENCE_STEP,
                    message="A referenced output step does not exist.",
                    step_id=step.step_id,
                    source_step_id=reference.step_id,
                    argument_name=argument_name,
                )
            )
            return
        if reference.step_id not in step.depends_on:
            failures.append(
                PlanValidationFailure(
                    code=PlanValidationFailureCode.MISSING_REFERENCE_DEPENDENCY,
                    message="An output reference must also be declared as a dependency.",
                    step_id=step.step_id,
                    source_step_id=reference.step_id,
                    argument_name=argument_name,
                )
            )
        source_definition = definitions_by_step_id.get(reference.step_id)
        if source_definition is None:
            return
        source_field = source_definition.plan_output_model.model_fields.get(reference.field)
        if source_field is None:
            failures.append(
                PlanValidationFailure(
                    code=PlanValidationFailureCode.UNKNOWN_OUTPUT_FIELD,
                    message="The referenced field is outside the source tool output contract.",
                    step_id=step.step_id,
                    source_step_id=reference.step_id,
                    field_name=reference.field,
                    argument_name=argument_name,
                )
            )
            return
        if not _annotation_is_compatible(source_field.rebuild_annotation(), destination_annotation):
            failures.append(
                PlanValidationFailure(
                    code=PlanValidationFailureCode.REFERENCE_TYPE_MISMATCH,
                    message="The referenced output type is incompatible with the destination argument.",
                    step_id=step.step_id,
                    source_step_id=reference.step_id,
                    field_name=reference.field,
                    argument_name=argument_name,
                )
            )

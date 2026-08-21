from app.explanations.models import (
    GeneratedExplanation,
    LLMProviderName,
    LLMStructuredResponse,
    LLMTokenUsage,
    MergeReadinessExplanationInput,
    TypedLLMRequest,
)


class FakeLLMClient:
    provider = LLMProviderName.FAKE
    model = "deterministic-fake-v1"

    def __init__(self, typed_output: object | None = None) -> None:
        self._typed_output = typed_output

    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse:
        reason_codes = tuple(
            dict.fromkeys(
                (
                    *explanation_input.blocker_reason_codes,
                    *explanation_input.missing_information_reason_codes,
                )
            )
        )
        if not reason_codes:
            reason_codes = (explanation_input.primary_reason_code,)
        generated = GeneratedExplanation(
            decision=explanation_input.decision,
            summary="This deterministic fake prose is intentionally discarded.",
            reason_codes=reason_codes,
            action_codes=tuple(
                dict.fromkeys(explanation_input.pending_action_codes)
            ),
        )
        input_token_count = (
            2
            + len(explanation_input.blocker_reason_codes)
            + len(explanation_input.missing_information_reason_codes)
            + len(explanation_input.pending_action_codes)
        )
        output_token_count = (
            1 + len(generated.reason_codes) + len(generated.action_codes)
        )

        return LLMStructuredResponse(
            output=generated.model_dump(mode="json"),
            token_usage=LLMTokenUsage(
                input_tokens=input_token_count,
                output_tokens=output_token_count,
                total_tokens=input_token_count + output_token_count,
            ),
        )

    async def generate_typed(
        self,
        request: TypedLLMRequest,
    ) -> LLMStructuredResponse:
        output = self._typed_output
        if output is None:
            output = _default_investigation_output(request)
        if output is None:
            from app.explanations.errors import (
                LLMProviderError,
                LLMProviderFailureCategory,
            )

            raise LLMProviderError(
                LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE
            )
        if hasattr(output, "model_dump"):
            output = output.model_dump(mode="json")
        return LLMStructuredResponse(output=output)


def _default_investigation_output(request: TypedLLMRequest) -> object | None:
    """Return deterministic fixture proposals for the local investigation demo."""

    # PURPOSE: Give the default local stack realistic typed planner and
    # hypothesis proposals without making a network call.
    #
    # FLOW: Inspect the requested output contract -> read only explicit typed
    # request fields -> construct that contract. The normal validator and
    # executor still decide whether a proposal is accepted and executable.
    #
    # WATCH OUT: This is fixture behavior, not natural-language intent parsing.
    # Adding keyword rules here would create a second semantic planner that
    # production providers and tests could disagree with.

    if request.output_model.__name__ == "InvestigationPlan":
        from app.investigations.planning import (
            InvestigationPlan,
            Literal,
            PlanArgument,
            PlanStep,
        )
        from app.tools import InvestigationToolId

        context = getattr(request.input, "request_context", None)
        if context is None:
            return None
        steps: list[PlanStep] = []
        if context.pull_request_number is not None:
            steps.append(
                PlanStep(
                    step_id=f"s{len(steps) + 1}",
                    tool_id=InvestigationToolId.GET_DIFF,
                    arguments=(
                        PlanArgument(
                            name="repository_owner",
                            value=Literal(value=context.repository_owner),
                        ),
                        PlanArgument(
                            name="repository_name",
                            value=Literal(value=context.repository_name),
                        ),
                        PlanArgument(
                            name="pr_number",
                            value=Literal(value=context.pull_request_number),
                        ),
                    ),
                    reason="Collect the bounded changed-file and diff evidence.",
                )
            )
        if context.incident_reference is not None:
            for tool_id, reason in (
                (
                    InvestigationToolId.GET_FAILURE_LOCATION,
                    "Collect the observed incident failure location.",
                ),
                (
                    InvestigationToolId.GET_INCIDENT,
                    "Collect the normalized incident record.",
                ),
            ):
                if len(steps) == 3:
                    break
                steps.append(
                    PlanStep(
                        step_id=f"s{len(steps) + 1}",
                        tool_id=tool_id,
                        arguments=(
                            PlanArgument(
                                name="incident_reference",
                                value=Literal(value=context.incident_reference),
                            ),
                        ),
                        reason=reason,
                    )
                )
        return InvestigationPlan(steps=tuple(steps)) if steps else None

    if request.output_model.__name__ == "HypothesisGenerationOutput":
        from app.investigations.hypotheses import (
            CandidateHypothesis,
            HypothesisGenerationOutput,
            HypothesisKind,
        )
        from app.investigations.models import (
            ChangedFileFact,
            ChangedFileMatchesFailureFileFact,
            ChangedHunkOverlapsFailureLineFact,
        )

        # The fake may propose causality only from the same typed Fact
        # relationship required by the deterministic production validator.
        facts = getattr(request.input, "facts", ())
        for changed_file in (
            fact for fact in facts if isinstance(fact, ChangedFileFact)
        ):
            relationship = next(
                (
                    fact
                    for fact in facts
                    if isinstance(
                        fact,
                        (
                            ChangedFileMatchesFailureFileFact,
                            ChangedHunkOverlapsFailureLineFact,
                        ),
                    )
                    and fact.file_path == changed_file.path
                ),
                None,
            )
            if relationship is not None:
                return HypothesisGenerationOutput(
                    candidates=(
                        CandidateHypothesis(
                            hypothesis_id="hypothesis:fake-code-change",
                            kind=HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED,
                            subject=changed_file.path,
                            supporting_fact_ids=(
                                changed_file.fact_id,
                                relationship.fact_id,
                            ),
                        ),
                    )
                )
        return HypothesisGenerationOutput()

    return None

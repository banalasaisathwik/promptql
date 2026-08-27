import argparse
import asyncio
import json
import re
from types import SimpleNamespace
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import LLMConfigurationError, LLMProvider, LLMSettings, LLMTask
from app.connectors.github_code_fakes import (
    CHANGED_FILE_EVIDENCE_FIXTURES,
    FIXTURE_PULL_REQUEST,
)
from app.connectors.incident_fakes import (
    FAILURE_LOCATION_EVIDENCE_FIXTURES,
    FAILURE_LOCATION_REQUEST,
)
from app.explanations import LLMProviderError, LLMStructuredResponse, TypedLLMRequest
from app.explanations.factory import OPENROUTER_OPENAI_BASE_URL
from app.explanations.openrouter_client import OpenRouterLLMClient
from app.investigations import InvestigationRequest, InvestigationResult
from app.investigations.code_diagnosis import (
    CodeContextBuilder,
    CodeDiagnosisError,
    DeterministicCodeFindingValidator,
    TypedLLMCodeDiagnoser,
)
from app.investigations.fact_derivation import derive_facts
from app.investigations.hypotheses import (
    CandidateHypothesis,
    DeterministicHypothesisValidator,
    GroundedTerminationReason,
    HypothesisGenerationError,
    HypothesisGenerationInput,
    HypothesisKind,
    TypedLLMHypothesisGenerator,
)
from app.investigations.planning import (
    InvestigationPlan,
    InvestigationPlannerError,
    PlannerInput,
    TypedLLMPlanner,
    build_planner_input,
)
from app.investigations.planning.instructions import PLANNER_SYSTEM_INSTRUCTIONS
from app.runtime import InMemoryRunRepository, RunStatus
from app.tools.models import TOOL_DEFINITIONS
from app.workflows import InvestigationWorkflowService


OPENROUTER_CHAT_COMPLETIONS_ENDPOINT = (
    f"{OPENROUTER_OPENAI_BASE_URL}/chat/completions"
)


COMPONENT_STAGES = (
    "plain",
    "typed",
    "planner",
    "planner-routing",
    "hypothesis",
    "code-diagnosis",
)
PAID_STAGES = (
    *COMPONENT_STAGES,
    "workflow",
    "all",
)
ALL_STAGES = ("config", *PAID_STAGES)


class SmokeInput(BaseModel):
    request: str


class SmokeOutput(BaseModel):
    message: str


class RecordingParseCompletions:
    def __init__(self, completions: object) -> None:
        self._completions = completions
        self.last_exception: Exception | None = None

    async def parse(self, **request: object) -> object:
        try:
            return await self._completions.parse(**request)
        except Exception as error:
            self.last_exception = error
            raise


class RecordingSDKClient:
    def __init__(self, sdk_client: AsyncOpenAI) -> None:
        self._sdk_client = sdk_client
        self.completions = RecordingParseCompletions(
            sdk_client.beta.chat.completions
        )
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(completions=self.completions)
        )

    async def close(self) -> None:
        await self._sdk_client.close()


def resolved_configuration(settings: LLMSettings) -> dict[str, object]:
    is_openrouter = settings.provider is LLMProvider.OPENROUTER
    return {
        "provider": settings.provider.value,
        "base_url": OPENROUTER_OPENAI_BASE_URL if is_openrouter else None,
        "planner_model": (
            settings.model_for(LLMTask.PLANNING) if is_openrouter else None
        ),
        "hypothesis_model": (
            settings.model_for(LLMTask.HYPOTHESIS_GENERATION)
            if is_openrouter
            else None
        ),
        "code_diagnosis_model": (
            (
                settings.model_policy.code_diagnosis_model
                or settings.model_policy.default_model
            )
            if is_openrouter and settings.model_policy is not None
            else None
        ),
        "default_model": settings.model,
        "api_key_present": settings.api_key is not None,
    }


def _sanitize_message(message: str, api_key: str | None) -> str:
    sanitized = message
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    sanitized = re.sub(
        r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [REDACTED]",
        sanitized,
    )
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", sanitized)
    return sanitized[:500]


def _provider_error_payload(error: Exception) -> dict[str, object]:
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return {}
    nested_error = body.get("error")
    if isinstance(nested_error, dict):
        return nested_error
    return body


def _upstream_error_fields(payload: dict[str, object]) -> dict[str, object]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    fields: dict[str, object] = {
        "upstream_provider": metadata.get("provider_name"),
    }
    raw_error = metadata.get("raw")
    if not isinstance(raw_error, str):
        return fields
    try:
        decoded_error = json.loads(raw_error)
    except json.JSONDecodeError:
        fields["upstream_message"] = "Upstream returned non-JSON error metadata."
        return fields
    if not isinstance(decoded_error, dict):
        return fields
    nested_error = decoded_error.get("error", decoded_error)
    if not isinstance(nested_error, dict):
        return fields
    fields.update(
        upstream_error_code=nested_error.get("code"),
        upstream_error_type=nested_error.get("type"),
        upstream_message=nested_error.get("message"),
    )
    return fields


def _failure_result(
    *,
    stage: str,
    error: Exception,
    settings: LLMSettings,
    requested_model: str,
    api_method: str,
    provider_category: str | None = None,
) -> dict[str, object]:
    payload = _provider_error_payload(error)
    upstream_fields = _upstream_error_fields(payload)
    provider_message = payload.get("message")
    if not isinstance(provider_message, str):
        provider_message = getattr(error, "message", None)
    if not isinstance(provider_message, str):
        provider_message = str(error)
    result = {
        "stage": stage,
        "status": "FAIL",
        "exception_class": type(error).__name__,
        "http_status": getattr(error, "status_code", None),
        "provider_error_code": payload.get("code"),
        "provider_error_type": payload.get("type"),
        "provider_message": _sanitize_message(
            provider_message,
            settings.api_key,
        ),
        "provider_category": provider_category,
        "requested_model": requested_model,
        "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
        "api_method": api_method,
    }
    upstream_message = upstream_fields.get("upstream_message")
    if isinstance(upstream_message, str):
        upstream_fields["upstream_message"] = _sanitize_message(
            upstream_message,
            settings.api_key,
        )
    result.update(upstream_fields)
    return result


def _sdk_client(settings: LLMSettings) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.api_key,
        base_url=OPENROUTER_OPENAI_BASE_URL,
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )


def _typed_client(
    settings: LLMSettings,
    model: str,
) -> tuple[OpenRouterLLMClient, RecordingSDKClient]:
    recording_client = RecordingSDKClient(_sdk_client(settings))
    return (
        OpenRouterLLMClient(
            client=recording_client,
            model=model,
            request_timeout_seconds=settings.request_timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
        ),
        recording_client,
    )


async def run_plain_call(settings: LLMSettings) -> dict[str, object]:
    model = settings.model_for(LLMTask.PLANNING)
    client = _sdk_client(settings)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=({"role": "user", "content": "Reply with the word ok."},),
            max_tokens=16,
            timeout=settings.request_timeout_seconds,
        )


        if not response.choices:
            return {
                "stage": "plain",
                "status": "FAIL",
                "exception_class": None,
                "http_status": None,
                "provider_error_code": "unexpected_response",
                "provider_error_type": "response_content",
                "provider_message": "The provider response did not contain a completion choice.",
                "provider_category": "invalid_structured_response",
                "requested_model": model,
                "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
                "api_method": "chat.completions.create",
            }
        return {
            "stage": "plain",
            "status": "PASS",
            "requested_model": model,
            "resolved_model": getattr(response, "model", None),
            "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
            "api_method": "chat.completions.create",
        }
    except Exception as error:
        return _failure_result(
            stage="plain",
            error=error,
            settings=settings,
            requested_model=model,
            api_method="chat.completions.create",
        )
    finally:
        await client.close()


async def run_typed_call(settings: LLMSettings) -> dict[str, object]:
    model = settings.model_for(LLMTask.PLANNING)
    client, recording_client = _typed_client(settings, model)
    try:
        response = await client.generate_typed(
            TypedLLMRequest(
                system_instructions=(
                    'Return JSON matching the schema with message exactly "ok".'
                ),
                input=SmokeInput(request="Reply with the word ok."),
                output_model=SmokeOutput,
            )
        )
        structured = LLMStructuredResponse.model_validate(response)
        output = SmokeOutput.model_validate(structured.output)
        if output.message.strip().lower() != "ok":
            raise ValueError("The typed provider response did not contain message=ok.")
        return {
            "stage": "typed",
            "status": "PASS",
            "requested_model": model,
            "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
            "api_method": "beta.chat.completions.parse",
            "output_schema": SmokeOutput.__name__,
        }
    except LLMProviderError as error:
        provider_error = recording_client.completions.last_exception or error
        return _failure_result(
            stage="typed",
            error=provider_error,
            settings=settings,
            requested_model=model,
            api_method="beta.chat.completions.parse",
            provider_category=error.category.value,
        )
    except (TypeError, ValueError, ValidationError) as error:
        return _failure_result(
            stage="typed",
            error=error,
            settings=settings,
            requested_model=model,
            api_method="beta.chat.completions.parse",
            provider_category="schema_validation",
        )
    finally:
        await client.aclose()


def _planner_input() -> PlannerInput:
    request = InvestigationRequest(
        repository_owner="octo-org",
        repository_name="analytics",
        question="Identify the next read-only evidence call for a checkout incident.",
        incident_reference="incident:checkout-500",
    )
    empty_result = InvestigationResult(
        evidence=(),
        facts=(),
        hypotheses=(),
        missing_information=(),
        recommended_actions=(),
    )
    return build_planner_input(
        request,
        empty_result,
        TOOL_DEFINITIONS,
        remaining_tool_calls=3,
        planning_round=1,
        max_planning_rounds=1,
    )


async def run_planner_call(settings: LLMSettings) -> dict[str, object]:
    model = settings.model_for(LLMTask.PLANNING)
    client, recording_client = _typed_client(settings, model)
    try:
        planned = await TypedLLMPlanner(client).plan(_planner_input())
        return {
            "stage": "planner",
            "status": "PASS",
            "requested_model": model,
            "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
            "api_method": "beta.chat.completions.parse",
            "plan_step_count": len(planned.plan.steps),
            "prompt_id": planned.metadata.prompt_id,
            "prompt_version": planned.metadata.prompt_version,
        }
    except InvestigationPlannerError as error:
        provider_error = recording_client.completions.last_exception or error
        return _failure_result(
            stage="planner",
            error=provider_error,
            settings=settings,
            requested_model=model,
            api_method="beta.chat.completions.parse",
            provider_category=error.code.value,
        )
    finally:
        await client.aclose()


async def run_planner_routing_call(settings: LLMSettings) -> dict[str, object]:
    model = settings.model_for(LLMTask.PLANNING)
    client = _sdk_client(settings)
    try:
        response = await client.beta.chat.completions.parse(
            model=model,
            messages=(
                {"role": "system", "content": PLANNER_SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": _planner_input().model_dump_json()},
            ),
            response_format=InvestigationPlan,
            max_tokens=settings.max_output_tokens,
            timeout=settings.request_timeout_seconds,
            extra_body={"provider": {"require_parameters": True}},
        )
        message = response.choices[0].message if response.choices else None
        parsed_output = getattr(message, "parsed", None)
        plan = InvestigationPlan.model_validate(parsed_output)
        return {
            "stage": "planner-routing",
            "status": "PASS",
            "requested_model": model,
            "resolved_model": getattr(response, "model", None),
            "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
            "api_method": "beta.chat.completions.parse",
            "provider_require_parameters": True,
            "plan_step_count": len(plan.steps),
        }
    except Exception as error:
        return _failure_result(
            stage="planner-routing",
            error=error,
            settings=settings,
            requested_model=model,
            api_method="beta.chat.completions.parse",
            provider_category="routing_parameter_probe",
        ) | {"provider_require_parameters": True}
    finally:
        await client.close()


async def run_hypothesis_call(settings: LLMSettings) -> dict[str, object]:
    model = settings.model_for(LLMTask.HYPOTHESIS_GENERATION)
    client, recording_client = _typed_client(settings, model)
    try:
        generated = await TypedLLMHypothesisGenerator(client).generate(
            HypothesisGenerationInput(
                investigation_goal="Assess whether current Facts support a cause.",
                facts=(),
            )
        )
        return {
            "stage": "hypothesis",
            "status": "PASS",
            "requested_model": model,
            "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
            "api_method": "beta.chat.completions.parse",
            "candidate_count": len(generated.candidates),
            "prompt_id": generated.metadata.prompt_id,
            "prompt_version": generated.metadata.prompt_version,
        }
    except HypothesisGenerationError as error:
        provider_error = recording_client.completions.last_exception or error
        return _failure_result(
            stage="hypothesis",
            error=provider_error,
            settings=settings,
            requested_model=model,
            api_method="beta.chat.completions.parse",
            provider_category=error.code.value,
        )
    finally:
        await client.aclose()


def _code_diagnosis_fixture():
    evidence = (
        *CHANGED_FILE_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST],
        FAILURE_LOCATION_EVIDENCE_FIXTURES[FAILURE_LOCATION_REQUEST],
    )
    facts = derive_facts(evidence)
    changed_file_fact = next(
        fact for fact in facts if fact.fact_type == "changed_file"
    )
    relationship_fact = next(
        fact
        for fact in facts
        if fact.fact_type == "changed_file_matches_failure_file"
    )
    hypothesis = DeterministicHypothesisValidator().validate(
        (
            CandidateHypothesis(
                hypothesis_id="hypothesis:diagnostic-code-change",
                kind=HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED,
                subject="services/checkout.py",
                supporting_fact_ids=(
                    changed_file_fact.fact_id,
                    relationship_fact.fact_id,
                ),
            ),
        ),
        facts,
    ).accepted_hypotheses[0]
    request = InvestigationRequest(
        repository_owner="octo-org",
        repository_name="analytics",
        question="Identify a bounded suspected code location for the checkout incident.",
        incident_reference="incident:checkout-500",
        pull_request_number=42,
    )
    return (
        CodeContextBuilder().build(request, (hypothesis,), facts, evidence),
        (hypothesis,),
        facts,
        evidence,
    )


async def run_code_diagnosis_call(
    settings: LLMSettings,
) -> dict[str, object]:
    try:
        model = settings.model_for(LLMTask.CODE_DIAGNOSIS)
    except LLMConfigurationError as error:
        return {
            "stage": "code-diagnosis",
            "status": "FAIL",
            "exception_class": type(error).__name__,
            "provider_category": "configuration_error",
            "provider_message": str(error),
            "requested_model": None,
            "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
            "api_method": "not_called",
        }
    client, recording_client = _typed_client(settings, model)
    diagnosis_input, hypotheses, facts, evidence = _code_diagnosis_fixture()
    try:
        generated = await TypedLLMCodeDiagnoser(client).generate(diagnosis_input)
        validation = DeterministicCodeFindingValidator().validate(
            generated.candidates,
            hypotheses,
            facts,
            evidence,
        )
        if not validation.accepted_findings:
            rejection_reasons = sorted(
                {item.reason.value for item in validation.rejected_candidates}
            )
            return {
                "stage": "code-diagnosis",
                "status": "FAIL",
                "provider_status": "PASS",
                "schema_status": "PASS",
                "grounding_status": "FAIL",
                "requested_model": model,
                "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
                "api_method": "beta.chat.completions.parse",
                "candidate_count": len(generated.candidates),
                "accepted_finding_count": 0,
                "rejected_finding_count": len(validation.rejected_candidates),
                "rejection_reasons": rejection_reasons,
                "prompt_id": generated.metadata.prompt_id,
                "prompt_version": generated.metadata.prompt_version,
            }
        return {
            "stage": "code-diagnosis",
            "status": "PASS",
            "provider_status": "PASS",
            "schema_status": "PASS",
            "grounding_status": "PASS",
            "requested_model": model,
            "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
            "api_method": "beta.chat.completions.parse",
            "candidate_count": len(generated.candidates),
            "accepted_finding_count": len(validation.accepted_findings),
            "rejected_finding_count": len(validation.rejected_candidates),
            "prompt_id": generated.metadata.prompt_id,
            "prompt_version": generated.metadata.prompt_version,
        }
    except CodeDiagnosisError as error:
        provider_error = recording_client.completions.last_exception or error
        return _failure_result(
            stage="code-diagnosis",
            error=provider_error,
            settings=settings,
            requested_model=model,
            api_method="beta.chat.completions.parse",
            provider_category=error.code.value,
        )
    finally:
        await client.aclose()


async def run_workflow_call(settings: LLMSettings) -> dict[str, object]:
    models = {
        "planning": settings.model_for(LLMTask.PLANNING),
        "hypothesis_generation": settings.model_for(LLMTask.HYPOTHESIS_GENERATION),
        "code_diagnosis": settings.model_for(LLMTask.CODE_DIAGNOSIS),
    }
    clients = tuple(_typed_client(settings, model)[0] for model in models.values())
    try:
        workflow = InvestigationWorkflowService(
            InMemoryRunRepository(),
            clients[1],
            planner_client=clients[0],
            code_diagnosis_client=clients[2],
        )
        request = InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout start returning 500 errors?",
            incident_reference="incident:checkout-500",
            deployment_reference="deployment:1042",
            pull_request_number=42,
            service="checkout-api",
            environment="production",
        )
        pending = await workflow.create_persisted_run(request)
        terminal = await workflow.continue_persisted_run(pending)
        state = terminal.state
        result = terminal.result


        successful_termination_reasons = {
            GroundedTerminationReason.COMPLETED,
            GroundedTerminationReason.NO_PROGRESS,
            GroundedTerminationReason.PLANNING_LIMIT_REACHED,
            GroundedTerminationReason.BUDGET_EXHAUSTED,
        }
        passed = (
            terminal.status is RunStatus.COMPLETED
            and result is not None
            and result.termination_reason in successful_termination_reasons
            and bool(result.supported_hypotheses)
            and bool(result.code_findings)
            and bool(result.recommendations)
        )
        return {
            "stage": "workflow",
            "status": "PASS" if passed else "FAIL",
            "requested_models": models,
            "maximum_provider_calls": 5,
            "run_status": terminal.status.value,
            "termination_reason": (
                result.termination_reason.value if result is not None else None
            ),
            "planning_round_count": (
                len(state.execution_state.rounds) if state is not None else 0
            ),
            "evidence_count": (
                len(state.working_memory.evidence) if state is not None else 0
            ),
            "fact_count": len(state.working_memory.facts) if state is not None else 0,
            "hypothesis_count": (
                len(result.supported_hypotheses) if result is not None else 0
            ),
            "code_finding_count": len(result.code_findings) if result is not None else 0,
            "recommendation_count": (
                len(result.recommendations) if result is not None else 0
            ),
        }
    except Exception as error:
        return {
            "stage": "workflow",
            "status": "FAIL",
            "requested_models": models,
            "maximum_provider_calls": 5,
            "exception_class": error.__class__.__name__,
            "exception_message": _sanitize_message(str(error), settings.api_key),
        }
    finally:
        for client in clients:
            close = getattr(client, "aclose", None)
            if callable(close):
                await close()


async def run_stage(stage: str, settings: LLMSettings) -> list[dict[str, object]]:
    if stage == "config":
        return [{"stage": "config", "status": "PASS", **resolved_configuration(settings)}]

    stage_calls = {
        "plain": run_plain_call,
        "typed": run_typed_call,
        "planner": run_planner_call,
        "planner-routing": run_planner_routing_call,
        "hypothesis": run_hypothesis_call,
        "code-diagnosis": run_code_diagnosis_call,
        "workflow": run_workflow_call,
    }
    requested_stages = (
        tuple(stage for stage in COMPONENT_STAGES if stage != "planner-routing")
        if stage == "all"
        else (stage,)
    )
    results: list[dict[str, object]] = []
    for requested_stage in requested_stages:
        result = await stage_calls[requested_stage](settings)
        results.append(result)
        if result["status"] != "PASS":
            break
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run secret-safe OpenRouter boundary diagnostics."
    )
    parser.add_argument("--stage", choices=ALL_STAGES, default="config")
    parser.add_argument(
        "--acknowledge-paid-call",
        action="store_true",
        help="Required for stages that can call OpenRouter and incur charges.",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    settings = LLMSettings.from_environment()
    configuration = resolved_configuration(settings)
    if settings.provider is not LLMProvider.OPENROUTER:
        print(json.dumps({
            "stage": "config",
            "status": "FAIL",
            **configuration,
            "message": "PROMPTQL_LLM_PROVIDER must resolve to openrouter.",
        }, indent=2))
        return 2
    if arguments.stage in PAID_STAGES and not arguments.acknowledge_paid_call:
        print(json.dumps({
            "stage": arguments.stage,
            "status": "NOT_RUN",
            **configuration,
            "message": "Add --acknowledge-paid-call to permit an external request.",
        }, indent=2))
        return 2

    results = asyncio.run(run_stage(arguments.stage, settings))
    print(json.dumps({"configuration": configuration, "results": results}, indent=2))
    return 0 if all(result["status"] == "PASS" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

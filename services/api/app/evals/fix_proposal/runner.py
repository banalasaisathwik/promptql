import argparse
import asyncio
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.config import LLMConfigurationError, LLMProvider, LLMSettings, LLMTask
from app.evals.fix_proposal.cases import build_fix_proposal_eval_dataset
from app.evals.fix_proposal.evaluation import build_fixture_candidate, execute_fix_proposal_eval
from app.evals.fix_proposal.models import FixProposalEvalDataset, FixProposalEvalRunIdentity
from app.evals.runner import EvalConfigurationError, PaidCallAcknowledgementError, validate_execution_mode
from app.explanations import (
    LLMClient,
    LLMProviderName,
    LLMStructuredResponse,
    TypedLLMClient,
    TypedLLMRequest,
    create_llm_client,
)
from app.investigations.code_diagnosis import FixProposalOutput


DEFAULT_SAMPLES_PER_CASE = 3
DEFAULT_INTER_REQUEST_DELAY_SECONDS = 1.0
DEFAULT_ARTIFACT_DIRECTORY = Path("local-artifacts") / "fix-proposal-evals"

ClientFactory = Callable[[LLMSettings, str | None], LLMClient]


class _FixtureFakeClient:
    provider = LLMProviderName.FAKE
    model = "deterministic-fake-v1"

    def __init__(self, dataset: FixProposalEvalDataset) -> None:
        self._cases_by_finding_id = {
            f"finding:{case.case_id}": case for case in dataset.cases
        }

    async def generate_typed(self, request: TypedLLMRequest) -> LLMStructuredResponse:
        proposal_input = request.input
        case = self._cases_by_finding_id.get(proposal_input.finding.finding_id)
        candidate = (
            build_fixture_candidate(case, proposal_input) if case is not None else None
        )
        return LLMStructuredResponse(
            output=FixProposalOutput(candidate=candidate).model_dump(mode="json")
        )


def _requested_model(settings: LLMSettings) -> str:
    if settings.provider is LLMProvider.FAKE:
        return "deterministic-fake-v1"
    return settings.model_for(LLMTask.CODE_DIAGNOSIS)


def build_fix_proposal_eval_identity(
    settings: LLMSettings,
    dataset: FixProposalEvalDataset,
    *,
    samples_per_case: int,
    inter_request_delay_seconds: float,
) -> FixProposalEvalRunIdentity:
    if samples_per_case < 1:
        raise EvalConfigurationError("Samples per case must be at least one.")
    if inter_request_delay_seconds < 0:
        raise EvalConfigurationError("Inter-request delay must not be negative.")
    return FixProposalEvalRunIdentity(
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.dataset_version,
        provider=LLMProviderName(settings.provider.value),
        requested_model=_requested_model(settings),
        samples_per_case=samples_per_case,
        inter_request_delay_seconds=inter_request_delay_seconds,
    )


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", commit):
        return commit
    return None


def _default_report_path(dataset: FixProposalEvalDataset, provider: LLMProvider) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_ARTIFACT_DIRECTORY / (
        f"{dataset.dataset_id}-{provider.value}-{timestamp}.report.json"
    )


def _write_report(path: Path, report) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def format_fix_proposal_eval_summary(report) -> str:
    metrics = report.metrics

    def rate(name, value) -> str:
        rendered = "n/a" if value.rate is None else f"{value.rate:.1%}"
        return f"{name}: {value.numerator}/{value.denominator} ({rendered})"

    return "\n".join(
        (
            f"eval execution completed: {report.execution_completed}",
            f"dataset: {report.run_identity.dataset_id}",
            f"planned/completed: {metrics.planned_samples}/{metrics.completed_samples}",
            rate("provider success", metrics.provider_success),
            rate("schema valid after provider success", metrics.schema_valid),
            rate("correct file", metrics.correct_file),
            rate("correct hunk/location", metrics.correct_hunk_or_location),
            rate("failure mechanism grounded", metrics.failure_mechanism_grounded),
            rate("minimal edit", metrics.minimal_edit),
            f"unsupported identifier rate: {metrics.unsupported_identifier_rate:.1%}",
            rate("syntax valid (applicable cases)", metrics.syntax_valid),
            rate("fix available when expected", metrics.fix_available_when_expected),
            rate("correct abstention", metrics.abstains_when_fix_not_grounded),
            f"provider failures: {metrics.provider_failures_by_category}",
            f"release passed: {report.release_passed}",
            f"failed checks: {list(report.failed_checks)}",
        )
    )


async def run_fix_proposal_eval(
    settings: LLMSettings,
    dataset: FixProposalEvalDataset,
    *,
    samples_per_case: int,
    inter_request_delay_seconds: float,
    acknowledge_paid_calls: bool,
    fake_dry_run: bool,
    report_path: Path,
    client_factory: ClientFactory = create_llm_client,
):
    validate_execution_mode(
        settings, acknowledge_paid_calls=acknowledge_paid_calls, fake_dry_run=fake_dry_run
    )
    identity = build_fix_proposal_eval_identity(
        settings,
        dataset,
        samples_per_case=samples_per_case,
        inter_request_delay_seconds=inter_request_delay_seconds,
    )
    client: TypedLLMClient
    if settings.provider is LLMProvider.FAKE:
        client = _FixtureFakeClient(dataset)
    else:
        client = client_factory(settings, identity.requested_model)
    try:
        observations, report = await execute_fix_proposal_eval(
            dataset,
            run_identity=identity,
            client=client,
            git_commit=_git_commit(),
        )
    finally:
        close = getattr(client, "aclose", None)
        if callable(close):
            await close()
    _write_report(report_path, report)
    return observations, report


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the focused fix-proposal eval matrix."
    )
    parser.add_argument("--samples-per-case", type=int, default=DEFAULT_SAMPLES_PER_CASE)
    parser.add_argument(
        "--inter-request-delay-seconds",
        type=float,
        default=DEFAULT_INTER_REQUEST_DELAY_SECONDS,
    )
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--acknowledge-paid-calls", action="store_true")
    parser.add_argument("--fake-dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser


async def _run_cli(arguments: argparse.Namespace) -> int:
    settings = LLMSettings.from_environment()
    dataset = build_fix_proposal_eval_dataset()
    identity = build_fix_proposal_eval_identity(
        settings,
        dataset,
        samples_per_case=arguments.samples_per_case,
        inter_request_delay_seconds=arguments.inter_request_delay_seconds,
    )
    report_path = arguments.report or _default_report_path(dataset, settings.provider)
    planned_samples = len(dataset.cases) * identity.samples_per_case

    if arguments.preflight:
        print(f"dataset={dataset.dataset_id}")
        print(f"case_count={len(dataset.cases)}")
        print(f"samples_per_case={identity.samples_per_case}")
        print(f"planned_samples={planned_samples}")
        print(f"maximum_provider_calls_if_run={planned_samples}")
        print(f"provider={identity.provider.value}")
        print(f"requested_model={identity.requested_model}")
        print(f"report_path={report_path}")
        print("external_calls=0")
        return 0

    _, report = await run_fix_proposal_eval(
        settings,
        dataset,
        samples_per_case=identity.samples_per_case,
        inter_request_delay_seconds=identity.inter_request_delay_seconds,
        acknowledge_paid_calls=arguments.acknowledge_paid_calls,
        fake_dry_run=arguments.fake_dry_run,
        report_path=report_path,
    )
    print(format_fix_proposal_eval_summary(report))
    print(f"report_path={report_path}")
    return 0 if report.release_passed else 1


def main() -> int:
    arguments = _build_argument_parser().parse_args()
    try:
        return asyncio.run(_run_cli(arguments))
    except (
        EvalConfigurationError,
        LLMConfigurationError,
        OSError,
        PaidCallAcknowledgementError,
        ValueError,
    ) as error:
        print(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

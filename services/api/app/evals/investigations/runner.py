import argparse
import asyncio
import re
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from app.config import LLMConfigurationError, LLMProvider, LLMSettings, LLMTask
from app.evals.investigations.cases import build_investigation_eval_dataset
from app.evals.investigations.evaluation import execute_investigation_eval
from app.evals.investigations.models import InvestigationEvalRunIdentity
from app.evals.models import EvalDatasetSplit
from app.evals.runner import (
    EvalConfigurationError,
    PaidCallAcknowledgementError,
    validate_execution_mode,
)
from app.explanations import LLMClient, LLMProviderName, create_llm_client
from app.investigations.replanning import MAX_PLANNING_ROUNDS


DEFAULT_SAMPLES_PER_CASE = 3
DEFAULT_INTER_REQUEST_DELAY_SECONDS = 1.0
DEFAULT_ARTIFACT_DIRECTORY = Path("local-artifacts") / "investigation-evals"
MAX_PROVIDER_CALLS_PER_SAMPLE = 3 + MAX_PLANNING_ROUNDS + 2

ClientFactory = Callable[[LLMSettings, str | None], LLMClient]
SleepFunction = Callable[[float], Awaitable[None]]


def _requested_models(settings: LLMSettings) -> dict[str, str]:
    # Purpose: Resolve the same task-specific model policy used by production
    # before any client exists, which lets preflight remain network-free.
    if settings.provider is LLMProvider.FAKE:
        return {
            "planning": "deterministic-fake-v1",
            "hypothesis_generation": "deterministic-fake-v1",
            "code_diagnosis": "deterministic-fake-v1",
        }
    return {
        "planning": settings.model_for(LLMTask.PLANNING),
        "hypothesis_generation": settings.model_for(
            LLMTask.HYPOTHESIS_GENERATION
        ),
        "code_diagnosis": settings.model_for(LLMTask.CODE_DIAGNOSIS),
    }


def build_investigation_eval_identity(
    settings: LLMSettings,
    dataset,
    *,
    samples_per_case: int,
    inter_request_delay_seconds: float,
) -> InvestigationEvalRunIdentity:
    if samples_per_case < 1:
        raise EvalConfigurationError("Samples per case must be at least one.")
    if inter_request_delay_seconds < 0:
        raise EvalConfigurationError("Inter-request delay must not be negative.")
    return InvestigationEvalRunIdentity(
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.dataset_version,
        dataset_split=dataset.split,
        provider=LLMProviderName(settings.provider.value),
        requested_models=_requested_models(settings),
        samples_per_case=samples_per_case,
        inter_request_delay_seconds=inter_request_delay_seconds,
    )


def _create_clients(
    settings: LLMSettings,
    requested_models: dict[str, str],
    client_factory: ClientFactory,
) -> tuple[LLMClient, LLMClient, LLMClient]:
    if settings.provider is LLMProvider.FAKE:
        shared = client_factory(settings, None)
        return shared, shared, shared
    return (
        client_factory(settings, requested_models["planning"]),
        client_factory(settings, requested_models["hypothesis_generation"]),
        client_factory(settings, requested_models["code_diagnosis"]),
    )


async def _close_clients(clients: tuple[LLMClient, ...]) -> None:
    # Key syntax: The temporary dict deduplicates a shared fake client by object
    # identity, so one resource is never closed three times.
    for client in {id(item): item for item in clients}.values():
        close = getattr(client, "aclose", None)
        if callable(close):
            await close()


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


def _default_report_path(dataset, provider: LLMProvider) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_ARTIFACT_DIRECTORY / (
        f"{dataset.dataset_id}-{provider.value}-{timestamp}.report.json"
    )


def _write_report(path: Path, report) -> None:
    # Why here: Replace-after-write avoids leaving a partially serialized report
    # if the process stops during the write.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def format_investigation_eval_summary(report) -> str:
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
            rate("component quality", metrics.component_quality),
            rate("trajectory quality", metrics.trajectory_quality),
            (
                "baseline/adaptive relevant Evidence recall: "
                f"{metrics.mean_deterministic_baseline_evidence_recall:.1%}/"
                f"{metrics.mean_adaptive_evidence_recall:.1%}"
            ),
            (
                "baseline/adaptive expected Fact recall: "
                f"{metrics.mean_deterministic_baseline_fact_recall:.1%}/"
                f"{metrics.mean_adaptive_fact_recall:.1%}"
            ),
            f"provider failures: {metrics.provider_failures_by_stage_and_category}",
            f"release passed: {report.release_passed}",
            f"failed checks: {list(report.failed_checks)}",
        )
    )


async def run_investigation_eval(
    settings: LLMSettings,
    dataset,
    *,
    samples_per_case: int,
    inter_request_delay_seconds: float,
    acknowledge_paid_calls: bool,
    fake_dry_run: bool,
    report_path: Path,
    client_factory: ClientFactory = create_llm_client,
    sleep: SleepFunction = asyncio.sleep,
):
    # Watch out: This gate runs before client construction. A configured real
    # provider cannot make a paid request without explicit acknowledgement.
    validate_execution_mode(
        settings,
        acknowledge_paid_calls=acknowledge_paid_calls,
        fake_dry_run=fake_dry_run,
    )
    identity = build_investigation_eval_identity(
        settings,
        dataset,
        samples_per_case=samples_per_case,
        inter_request_delay_seconds=inter_request_delay_seconds,
    )
    clients = _create_clients(settings, identity.requested_models, client_factory)
    try:
        observations, report = await execute_investigation_eval(
            dataset,
            run_identity=identity,
            planner_client=clients[0],
            hypothesis_client=clients[1],
            code_diagnosis_client=clients[2],
            git_commit=_git_commit(),
            sleep=sleep,
        )
    finally:
        await _close_clients(clients)
    _write_report(report_path, report)
    return observations, report


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run versioned V2 investigation component and trajectory evals."
    )
    parser.add_argument(
        "--dataset",
        choices=tuple(split.value for split in EvalDatasetSplit),
        default=EvalDatasetSplit.DEVELOPMENT.value,
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
    dataset = build_investigation_eval_dataset(EvalDatasetSplit(arguments.dataset))
    identity = build_investigation_eval_identity(
        settings,
        dataset,
        samples_per_case=arguments.samples_per_case,
        inter_request_delay_seconds=arguments.inter_request_delay_seconds,
    )
    report_path = arguments.report or _default_report_path(dataset, settings.provider)
    planned_samples = len(dataset.cases) * identity.samples_per_case
    if arguments.preflight:
        # Purpose: Make cost exposure reviewable without constructing a provider
        # client or sending any repository context over the network.
        print(f"dataset={dataset.dataset_id}")
        print(f"case_count={len(dataset.cases)}")
        print(f"samples_per_case={identity.samples_per_case}")
        print(f"planned_samples={planned_samples}")
        print(
            "maximum_provider_calls_if_run="
            f"{planned_samples * MAX_PROVIDER_CALLS_PER_SAMPLE}"
        )
        print(f"provider={identity.provider.value}")
        for task, model in identity.requested_models.items():
            print(f"requested_model.{task}={model}")
        print(f"report_path={report_path}")
        print("external_calls=0")
        return 0

    _, report = await run_investigation_eval(
        settings,
        dataset,
        samples_per_case=identity.samples_per_case,
        inter_request_delay_seconds=identity.inter_request_delay_seconds,
        acknowledge_paid_calls=arguments.acknowledge_paid_calls,
        fake_dry_run=arguments.fake_dry_run,
        report_path=report_path,
    )
    print(format_investigation_eval_summary(report))
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

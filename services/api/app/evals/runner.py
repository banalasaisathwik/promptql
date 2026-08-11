import argparse
import asyncio
import re
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import LLMConfigurationError, LLMProvider, LLMSettings
from app.evals.cases import (
    ExplanationEvalDataset,
    ExplanationObservationCase,
    build_eval_dataset,
)
from app.evals.graders import (
    aggregate_records,
    development_case_reliability,
    evaluate_thresholds,
)
from app.evals.models import (
    EvalBaselineComparison,
    EvalDatasetSplit,
    EvalModelSettings,
    EvalRunIdentity,
    EvalRunReport,
    ExplanationObservationRecord,
)
from app.evals.observation import observe_case
from app.evals.reporting import (
    baseline_from_report,
    compare_with_baseline,
    format_human_summary,
    load_baseline,
    write_baseline,
    write_completed_report,
    write_observation_line,
)
from app.explanations import LLMClient, LLMProviderName, create_llm_client
from app.explanations.instructions import PROMPT_ID, PROMPT_VERSION


DEFAULT_SAMPLES_PER_CASE = 3
DEFAULT_INTER_REQUEST_DELAY_SECONDS = 1.0
DEFAULT_ARTIFACT_DIRECTORY = Path("local-artifacts") / "explanation-evals"


class PaidCallAcknowledgementError(RuntimeError):
    pass


class EvalConfigurationError(ValueError):
    pass


ClientFactory = Callable[[LLMSettings], LLMClient]
SleepFunction = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class EvalArtifactPaths:
    observations: Path
    report: Path


@dataclass(frozen=True)
class EvalExecutionResult:
    records: tuple[ExplanationObservationRecord, ...]
    report: EvalRunReport
    paths: EvalArtifactPaths
    baseline_comparison: EvalBaselineComparison | None


def validate_execution_mode(
    settings: LLMSettings,
    *,
    acknowledge_paid_calls: bool,
    fake_dry_run: bool,
) -> None:
    if acknowledge_paid_calls and fake_dry_run:
        raise PaidCallAcknowledgementError(
            "Choose either paid-call acknowledgement or fake dry-run mode."
        )
    if settings.provider is LLMProvider.FAKE:
        if not fake_dry_run:
            raise PaidCallAcknowledgementError(
                "The fake provider requires --fake-dry-run."
            )
        return
    if fake_dry_run:
        raise PaidCallAcknowledgementError(
            "Fake dry-run mode cannot use a real provider."
        )
    if not acknowledge_paid_calls:
        raise PaidCallAcknowledgementError(
            "Real provider execution requires --acknowledge-paid-calls."
        )


def build_run_identity(
    settings: LLMSettings,
    dataset: ExplanationEvalDataset,
    *,
    samples_per_case: int,
    inter_request_delay_seconds: float,
) -> EvalRunIdentity:
    if samples_per_case < 1:
        raise EvalConfigurationError("Samples per case must be at least one.")
    if inter_request_delay_seconds < 0:
        raise EvalConfigurationError("Inter-request delay must not be negative.")
    return EvalRunIdentity(
        prompt_id=PROMPT_ID,
        prompt_version=PROMPT_VERSION,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.dataset_version,
        dataset_split=dataset.split,
        provider=LLMProviderName(settings.provider.value),
        configured_model=settings.model,
        model_settings=EvalModelSettings(
            request_timeout_seconds=settings.request_timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
        ),
        samples_per_case=samples_per_case,
        inter_request_delay_seconds=inter_request_delay_seconds,
    )


async def run_repeated_samples(
    cases: Sequence[ExplanationObservationCase],
    client: LLMClient,
    *,
    run_identity: EvalRunIdentity,
    observations_path: Path,
    include_details: bool,
    sleep: SleepFunction = asyncio.sleep,
) -> tuple[ExplanationObservationRecord, ...]:
    planned_samples = len(cases) * run_identity.samples_per_case
    observations_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[ExplanationObservationRecord] = []
    attempt_index = 0
    with observations_path.open("w", encoding="utf-8", newline="\n") as report_file:
        for case in cases:
            for sample_number in range(1, run_identity.samples_per_case + 1):
                record = await observe_case(
                    case,
                    client,
                    run_identity=run_identity,
                    sample_number=sample_number,
                )
                records.append(record)
                write_observation_line(
                    report_file,
                    record,
                    include_details=include_details,
                )
                attempt_index += 1
                if attempt_index < planned_samples:
                    await sleep(run_identity.inter_request_delay_seconds)
    return tuple(records)


async def _close_client(client: LLMClient) -> None:
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
    return commit if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", commit) else None


async def execute_eval(
    settings: LLMSettings,
    dataset: ExplanationEvalDataset,
    *,
    samples_per_case: int,
    inter_request_delay_seconds: float,
    acknowledge_paid_calls: bool,
    fake_dry_run: bool,
    debug_holdout_details: bool,
    paths: EvalArtifactPaths,
    baseline_path: Path | None = None,
    save_baseline_path: Path | None = None,
    client_factory: ClientFactory = create_llm_client,
    sleep: SleepFunction = asyncio.sleep,
) -> EvalExecutionResult:
    validate_execution_mode(
        settings,
        acknowledge_paid_calls=acknowledge_paid_calls,
        fake_dry_run=fake_dry_run,
    )
    run_identity = build_run_identity(
        settings,
        dataset,
        samples_per_case=samples_per_case,
        inter_request_delay_seconds=inter_request_delay_seconds,
    )
    started_at = datetime.now(UTC)
    client = client_factory(settings)
    try:
        include_details = (
            dataset.split is EvalDatasetSplit.DEVELOPMENT
            or debug_holdout_details
        )
        records = await run_repeated_samples(
            dataset.cases,
            client,
            run_identity=run_identity,
            observations_path=paths.observations,
            include_details=include_details,
            sleep=sleep,
        )
    finally:
        await _close_client(client)

    metrics = aggregate_records(
        records,
        planned_samples=len(dataset.cases) * samples_per_case,
    )
    thresholds = evaluate_thresholds(
        metrics,
        records,
        dataset_split=dataset.split,
    )
    report = EvalRunReport(
        execution_completed=True,
        run_identity=run_identity,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        git_commit=_git_commit(),
        metrics=metrics,
        thresholds=thresholds,
        development_case_reliability=(
            development_case_reliability(records)
            if dataset.split is EvalDatasetSplit.DEVELOPMENT
            else ()
        ),
    )

    comparison = None
    if baseline_path is not None:
        comparison = compare_with_baseline(report, load_baseline(baseline_path))
        report = report.model_copy(update={"baseline_comparison": comparison})


    write_completed_report(paths.report, report)
    if save_baseline_path is not None:
        write_baseline(save_baseline_path, baseline_from_report(report))

    return EvalExecutionResult(
        records=records,
        report=report,
        paths=paths,
        baseline_comparison=comparison,
    )


def default_artifact_paths(
    dataset: ExplanationEvalDataset,
    provider: LLMProvider,
) -> EvalArtifactPaths:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{dataset.dataset_id}-{provider.value}-{timestamp}"
    return EvalArtifactPaths(
        observations=DEFAULT_ARTIFACT_DIRECTORY / f"{stem}.observations.jsonl",
        report=DEFAULT_ARTIFACT_DIRECTORY / f"{stem}.report.json",
    )


def eval_exit_code(result: EvalExecutionResult) -> int:
    if (
        result.baseline_comparison is not None
        and not result.baseline_comparison.compatible
    ):
        return 3
    return 0 if result.report.thresholds.release_passed else 1


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run versioned merge-readiness explanation evaluations.",
    )
    parser.add_argument(
        "--dataset",
        choices=tuple(split.value for split in EvalDatasetSplit),
        default=EvalDatasetSplit.DEVELOPMENT.value,
    )
    parser.add_argument(
        "--samples-per-case",
        type=int,
        default=DEFAULT_SAMPLES_PER_CASE,
    )
    parser.add_argument(
        "--inter-request-delay-seconds",
        type=float,
        default=DEFAULT_INTER_REQUEST_DELAY_SECONDS,
    )
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--acknowledge-paid-calls", action="store_true")
    parser.add_argument("--fake-dry-run", action="store_true")
    parser.add_argument("--debug-holdout-details", action="store_true")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--save-baseline", type=Path)
    return parser


async def _run_cli(arguments: argparse.Namespace) -> int:
    settings = LLMSettings.from_environment()
    split = EvalDatasetSplit(arguments.dataset)
    dataset = await build_eval_dataset(split)
    identity = build_run_identity(
        settings,
        dataset,
        samples_per_case=arguments.samples_per_case,
        inter_request_delay_seconds=arguments.inter_request_delay_seconds,
    )
    paths = default_artifact_paths(dataset, settings.provider)
    planned_request_count = len(dataset.cases) * identity.samples_per_case

    if arguments.preflight:
        print(f"dataset={dataset.dataset_id}")
        print(f"case_count={len(dataset.cases)}")
        print(f"samples_per_case={identity.samples_per_case}")
        print(f"planned_request_count={planned_request_count}")
        print(f"provider={identity.provider.value}")
        print(f"configured_model={identity.configured_model or 'none'}")
        print(f"inter_request_delay_seconds={identity.inter_request_delay_seconds}")
        print(
            "maximum_output_tokens_if_run="
            f"{planned_request_count * identity.model_settings.max_output_tokens}"
        )
        print(f"observations_path={paths.observations}")
        print(f"report_path={paths.report}")
        print("external_calls=0")
        return 0

    result = await execute_eval(
        settings,
        dataset,
        samples_per_case=identity.samples_per_case,
        inter_request_delay_seconds=identity.inter_request_delay_seconds,
        acknowledge_paid_calls=arguments.acknowledge_paid_calls,
        fake_dry_run=arguments.fake_dry_run,
        debug_holdout_details=arguments.debug_holdout_details,
        paths=paths,
        baseline_path=arguments.baseline,
        save_baseline_path=arguments.save_baseline,
    )
    print(
        format_human_summary(
            result.report,
            result.records,
            include_holdout_details=arguments.debug_holdout_details,
        )
    )
    print(f"observations_path={result.paths.observations}")
    print(f"report_path={result.paths.report}")
    if result.baseline_comparison is not None and not result.baseline_comparison.compatible:
        print(
            "baseline_incompatible="
            + ",".join(result.baseline_comparison.incompatibilities)
        )
    return eval_exit_code(result)


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

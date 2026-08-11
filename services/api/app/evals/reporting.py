import json
from collections.abc import Sequence
from pathlib import Path

from app.evals.graders import record_quality_succeeds
from app.evals.models import (
    EvalBaseline,
    EvalBaselineComparison,
    EvalDatasetSplit,
    EvalRunReport,
    ExplanationObservationRecord,
)


DETAIL_FIELDS = {
    "case_id",
    "expected_decision",
    "expected_reason_codes",
    "expected_action_codes",
    "observed_decision",
    "observed_reason_codes",
    "observed_action_codes",
}


def observation_artifact(
    record: ExplanationObservationRecord,
    *,
    include_details: bool,
) -> dict[str, object]:
    artifact = record.model_dump(mode="json")
    if not include_details:
        for field_name in DETAIL_FIELDS:
            artifact.pop(field_name, None)
    return artifact


def write_observation_line(
    report_file: object,
    record: ExplanationObservationRecord,
    *,
    include_details: bool,
) -> None:
    serialized = json.dumps(
        observation_artifact(record, include_details=include_details),
        separators=(",", ":"),
        sort_keys=True,
    )
    report_file.write(serialized + "\n")
    report_file.flush()


def _write_model(path: Path, model: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        model.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def write_completed_report(path: Path, report: EvalRunReport) -> None:
    _write_model(path, report)


def baseline_from_report(report: EvalRunReport) -> EvalBaseline:
    return EvalBaseline(
        created_at=report.completed_at,
        git_commit=report.git_commit,
        run_identity=report.run_identity,
        metrics=report.metrics,
    )


def write_baseline(path: Path, baseline: EvalBaseline) -> None:
    _write_model(path, baseline)


def load_baseline(path: Path) -> EvalBaseline:
    return EvalBaseline.model_validate_json(path.read_text(encoding="utf-8"))


def _compatibility_fields() -> tuple[str, ...]:
    return (
        "prompt_id",
        "prompt_version",
        "dataset_id",
        "dataset_version",
        "dataset_split",
        "provider",
        "configured_model",
        "model_settings",
        "samples_per_case",
    )


def _rate(value: float | None) -> float:
    return 0.0 if value is None else value


def compare_with_baseline(
    report: EvalRunReport,
    baseline: EvalBaseline,
) -> EvalBaselineComparison:
    current_identity = report.run_identity
    baseline_identity = baseline.run_identity
    incompatibilities = tuple(
        field_name
        for field_name in _compatibility_fields()
        if getattr(current_identity, field_name) != getattr(
            baseline_identity,
            field_name,
        )
    )
    if incompatibilities:
        return EvalBaselineComparison(
            compatible=False,
            incompatibilities=incompatibilities,
            metric_deltas={},
        )

    current = report.metrics
    previous = baseline.metrics
    deltas = {
        "provider_success_rate": _rate(current.provider_success.rate)
        - _rate(previous.provider_success.rate),
        "candidate_schema_valid_rate": _rate(current.candidate_schema_valid.rate)
        - _rate(previous.candidate_schema_valid.rate),
        "candidate_decision_match_rate": _rate(current.candidate_decision_match.rate)
        - _rate(previous.candidate_decision_match.rate),
        "candidate_exact_reason_set_match_rate": _rate(
            current.candidate_exact_reason_set_match.rate
        )
        - _rate(previous.candidate_exact_reason_set_match.rate),
        "candidate_exact_action_set_match_rate": _rate(
            current.candidate_exact_action_set_match.rate
        )
        - _rate(previous.candidate_exact_action_set_match.rate),
        "validator_pass_rate": _rate(current.validator_pass.rate)
        - _rate(previous.validator_pass.rate),
        "candidate_end_to_end_quality_rate": _rate(
            current.candidate_end_to_end_quality.rate
        )
        - _rate(previous.candidate_end_to_end_quality.rate),
        "attempt_end_to_end_success_rate": _rate(
            current.attempt_end_to_end_success.rate
        )
        - _rate(previous.attempt_end_to_end_success.rate),
        "reason_code_micro_precision": current.reason_code_micro_precision
        - previous.reason_code_micro_precision,
        "reason_code_micro_recall": current.reason_code_micro_recall
        - previous.reason_code_micro_recall,
        "action_code_micro_precision": current.action_code_micro_precision
        - previous.action_code_micro_precision,
        "action_code_micro_recall": current.action_code_micro_recall
        - previous.action_code_micro_recall,
        "provider_failure_count": float(
            sum(current.provider_failures_by_category.values())
            - sum(previous.provider_failures_by_category.values())
        ),
        "mean_latency_ms": (current.latency.mean_ms or 0.0)
        - (previous.latency.mean_ms or 0.0),
        "input_tokens": float(
            current.tokens.input_tokens - previous.tokens.input_tokens
        ),
        "output_tokens": float(
            current.tokens.output_tokens - previous.tokens.output_tokens
        ),
        "provider_total_tokens": float(
            current.tokens.provider_total_tokens
            - previous.tokens.provider_total_tokens
        ),
    }
    return EvalBaselineComparison(
        compatible=True,
        incompatibilities=(),
        metric_deltas=deltas,
    )


def _format_rate(label: str, numerator: int, denominator: int, rate: float | None) -> str:
    rendered_rate = "n/a" if rate is None else f"{rate:.1%}"
    return f"{label}: {numerator}/{denominator} ({rendered_rate})"


def format_human_summary(
    report: EvalRunReport,
    records: Sequence[ExplanationObservationRecord],
    *,
    include_holdout_details: bool,
) -> str:
    metrics = report.metrics
    lines = [
        f"eval execution completed: {report.execution_completed}",
        f"dataset: {report.run_identity.dataset_id}",
        f"planned/attempted/completed: {metrics.planned_samples}/{metrics.attempted_samples}/{metrics.completed_samples}",
        _format_rate("provider success", **metrics.provider_success.model_dump()),
        _format_rate("candidate schema valid", **metrics.candidate_schema_valid.model_dump()),
        _format_rate("candidate decision match", **metrics.candidate_decision_match.model_dump()),
        _format_rate(
            "candidate exact reason set",
            **metrics.candidate_exact_reason_set_match.model_dump(),
        ),
        _format_rate(
            "candidate exact action set",
            **metrics.candidate_exact_action_set_match.model_dump(),
        ),
        f"reason micro precision/recall: {metrics.reason_code_micro_precision:.1%}/{metrics.reason_code_micro_recall:.1%}",
        f"action micro precision/recall: {metrics.action_code_micro_precision:.1%}/{metrics.action_code_micro_recall:.1%}",
        _format_rate("validator pass", **metrics.validator_pass.model_dump()),
        _format_rate(
            "candidate end-to-end quality",
            **metrics.candidate_end_to_end_quality.model_dump(),
        ),
        _format_rate(
            "attempt end-to-end success",
            **metrics.attempt_end_to_end_success.model_dump(),
        ),
        f"provider failures: {metrics.provider_failures_by_category}",
        f"quality thresholds passed: {report.thresholds.quality_passed}",
        f"operational thresholds passed: {report.thresholds.operational_passed}",
        f"release thresholds passed: {report.thresholds.release_passed}",
    ]
    if report.run_identity.dataset_split is EvalDatasetSplit.DEVELOPMENT:
        lines.append("development per-case reliability:")
        lines.extend(
            f"  {case.case_id}: attempts={case.attempts}, attempt_success_rate={case.attempt_success_rate}"
            for case in report.development_case_reliability
        )
    elif include_holdout_details:
        lines.append("holdout details (this holdout is now spent):")
        for record in records:
            lines.append(
                "  "
                + json.dumps(
                    {
                        "case_id": record.case_id,
                        "sample_number": record.sample_number,
                        "expected_decision": record.expected_decision.value,
                        "observed_decision": (
                            record.observed_decision.value
                            if record.observed_decision is not None
                            else None
                        ),
                        "expected_reason_codes": [
                            code.value for code in record.expected_reason_codes
                        ],
                        "observed_reason_codes": [
                            code.value for code in record.observed_reason_codes
                        ],
                        "expected_action_codes": [
                            code.value for code in record.expected_action_codes
                        ],
                        "observed_action_codes": [
                            code.value for code in record.observed_action_codes
                        ],
                        "quality_success": record_quality_succeeds(record),
                    },
                    sort_keys=True,
                )
            )
    if report.baseline_comparison is not None:
        if report.baseline_comparison.compatible:
            lines.append("compatible baseline metric deltas:")
            lines.extend(
                f"  {name}: {delta:+.6f}"
                for name, delta in report.baseline_comparison.metric_deltas.items()
            )
        else:
            lines.append(
                "incompatible baseline fields: "
                + ", ".join(report.baseline_comparison.incompatibilities)
            )
    return "\n".join(lines)

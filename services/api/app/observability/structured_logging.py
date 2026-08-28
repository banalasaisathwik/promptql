import json
import logging
import sys
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from opentelemetry import trace

from app.observability.live_event_broker import LiveEventBroker


LOGGER_NAME = "promptql.runtime"
ALLOWED_EVENT_FIELDS = frozenset(
    {
        "run_id",
        "workflow_name",
        "workflow_version",
        "run_status",
        "policy_decision",
        "step_name",
        "persistence_operation",
        "persistence_checkpoint",
        "failure_category",
        "github_source",
        "jira_source",
        "sentry_source",
        "llm_provider",
        "telemetry_signal",
        "tool_id",
        "tool_outcome",
        "evidence_id",
        "round_number",
        "round_completed",
        "requested_model",
        "prompt_version",
        "facts_count",
        "missing_information_count",
        "hypothesis_count",
        "location_count",
        "role",
        "char_count",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "exception_class",
        "failure_code",
        "http_status",
        "provider_type",
        "provider_code",
        "provider_message",
        "failed_generation_present",
        "failed_generation_length",
        "local_schema_error",
    }
)


def _json_value(value: Any) -> str | int | float | bool | None:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("structured log value has an unsupported type")


def configure_structured_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    has_promptql_handler = any(
        getattr(handler, "_promptql_handler", False)
        for handler in logger.handlers
    )
    if not has_promptql_handler:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._promptql_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


class StructuredEventLogger:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or configure_structured_logger()
        self._broker: LiveEventBroker | None = None

    def set_broker(self, broker: LiveEventBroker | None) -> None:
        self._broker = broker

    def emit(self, event: str, level: int = logging.INFO, **fields: Any) -> None:
        try:
            if not fields.keys() <= ALLOWED_EVENT_FIELDS:
                raise ValueError("structured log field is not allowed")

            span_context = trace.get_current_span().get_span_context()
            record: dict[str, Any] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": logging.getLevelName(level).lower(),
                "event": event,
            }
            if span_context.is_valid:
                record["trace_id"] = format(span_context.trace_id, "032x")
                record["span_id"] = format(span_context.span_id, "016x")

            for key, value in fields.items():
                if value is not None:
                    record[key] = _json_value(value)

            self._logger.log(
                level,
                json.dumps(record, separators=(",", ":"), sort_keys=True),
            )

            run_id = record.get("run_id")
            if self._broker is not None and run_id is not None:
                self._broker.publish(run_id, record)
        except Exception:
            return


class NoOpStructuredEventLogger:
    def emit(self, _event: str, _level: int = logging.INFO, **_fields: Any) -> None:
        return

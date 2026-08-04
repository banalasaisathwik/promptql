pass

import json
import logging
import sys
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from opentelemetry import trace


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
        "telemetry_signal",
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
    pass

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
    pass

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or configure_structured_logger()

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
        except Exception:


            return


class NoOpStructuredEventLogger:
    pass

    def emit(self, _event: str, _level: int = logging.INFO, **_fields: Any) -> None:
        return

pass

import logging
from dataclasses import dataclass, field
from threading import Lock
from weakref import WeakSet

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricExportResult,
    MetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExportResult,
    SpanExporter,
)

from app.config import TelemetrySettings
from app.observability.contracts import FailureCategory
from app.observability.runtime_telemetry import RuntimeTelemetry
from app.observability.structured_logging import (
    StructuredEventLogger,
    configure_structured_logger,
)


EXPORT_TIMEOUT_MILLIS = 5_000
METRIC_EXPORT_INTERVAL_MILLIS = 60_000
MAX_SPAN_QUEUE_SIZE = 2_048
MAX_SPAN_EXPORT_BATCH_SIZE = 512


class _ExportWarning:
    pass

    def __init__(self, event_logger: StructuredEventLogger, signal: str) -> None:
        self._event_logger = event_logger
        self._signal = signal
        self._emitted = False
        self._lock = Lock()

    def emit_once(self) -> None:
        with self._lock:
            if self._emitted:
                return
            self._emitted = True
        self._event_logger.emit(
            "runtime.telemetry.export_failed",
            logging.WARNING,
            telemetry_signal=self._signal,
            failure_category=FailureCategory.TELEMETRY_EXPORT_FAILURE,
        )


class FailureIsolatingSpanExporter(SpanExporter):
    pass

    def __init__(
        self,
        inner: SpanExporter,
        event_logger: StructuredEventLogger,
    ) -> None:
        self._inner = inner
        self._warning = _ExportWarning(event_logger, "traces")
        self._disabled = False
        self._state_lock = Lock()

    def _disable(self) -> None:
        with self._state_lock:
            self._disabled = True
        self._warning.emit_once()

    def export(self, spans) -> SpanExportResult:
        with self._state_lock:
            if self._disabled:
                return SpanExportResult.FAILURE
        try:
            result = self._inner.export(spans)
        except Exception:
            self._disable()
            return SpanExportResult.FAILURE
        if result is not SpanExportResult.SUCCESS:
            self._disable()
        return result

    def shutdown(self) -> None:
        try:
            self._inner.shutdown()
        except Exception:
            self._disable()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        with self._state_lock:
            if self._disabled:
                return False
        try:
            return self._inner.force_flush(timeout_millis)
        except Exception:
            self._disable()
            return False


class FailureIsolatingMetricExporter(MetricExporter):
    pass

    def __init__(
        self,
        inner: MetricExporter,
        event_logger: StructuredEventLogger,
    ) -> None:
        super().__init__(
            preferred_temporality=inner._preferred_temporality,
            preferred_aggregation=inner._preferred_aggregation,
        )
        self._inner = inner
        self._warning = _ExportWarning(event_logger, "metrics")
        self._disabled = False
        self._state_lock = Lock()

    def _disable(self) -> None:
        with self._state_lock:
            self._disabled = True
        self._warning.emit_once()

    def export(
        self,
        metrics_data,
        timeout_millis: float = 10_000,
        **kwargs,
    ) -> MetricExportResult:
        with self._state_lock:
            if self._disabled:
                return MetricExportResult.FAILURE
        try:
            result = self._inner.export(
                metrics_data,
                timeout_millis=timeout_millis,
                **kwargs,
            )
        except Exception:
            self._disable()
            return MetricExportResult.FAILURE
        if result is not MetricExportResult.SUCCESS:
            self._disable()
        return result

    def shutdown(self, timeout_millis: float = 30_000, **kwargs) -> None:
        try:
            self._inner.shutdown(timeout_millis=timeout_millis, **kwargs)
        except Exception:
            self._disable()

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        with self._state_lock:
            if self._disabled:
                return False
        try:
            return self._inner.force_flush(timeout_millis)
        except Exception:
            self._disable()
            return False


@dataclass
class Observability:
    pass

    runtime_telemetry: RuntimeTelemetry
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    event_logger: StructuredEventLogger | None = None
    _instrumented_apps: WeakSet[FastAPI] = field(default_factory=WeakSet)
    _shutdown_complete: bool = False

    def instrument_app(self, application: FastAPI) -> None:
        if self.tracer_provider is None or application in self._instrumented_apps:
            return
        FastAPIInstrumentor.instrument_app(
            application,
            tracer_provider=self.tracer_provider,
            meter_provider=NoOpMeterProvider(),
            excluded_urls=r".*/health$",
            http_capture_headers_server_request=[],
            http_capture_headers_server_response=[],
            http_capture_headers_sanitize_fields=[],
            exclude_spans=["receive", "send"],
        )
        self._instrumented_apps.add(application)

    def shutdown(self) -> None:
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        try:
            if self.meter_provider is not None:
                self.meter_provider.shutdown(
                    timeout_millis=EXPORT_TIMEOUT_MILLIS
                )
        except Exception:
            if self.event_logger is not None:
                self.event_logger.emit(
                    "runtime.telemetry.export_failed",
                    logging.WARNING,
                    telemetry_signal="metrics_shutdown",
                    failure_category=FailureCategory.TELEMETRY_EXPORT_FAILURE,
                )
        try:
            if self.tracer_provider is not None:
                self.tracer_provider.shutdown()
        except Exception:
            if self.event_logger is not None:
                self.event_logger.emit(
                    "runtime.telemetry.export_failed",
                    logging.WARNING,
                    telemetry_signal="traces_shutdown",
                    failure_category=FailureCategory.TELEMETRY_EXPORT_FAILURE,
                )


def _quiet_otlp_internal_loggers() -> None:
    pass

    for logger_name in (
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
    ):
        exporter_logger = logging.getLogger(logger_name)
        exporter_logger.handlers.clear()
        exporter_logger.addHandler(logging.NullHandler())
        exporter_logger.propagate = False


def _disabled_observability(
    event_logger: StructuredEventLogger,
) -> Observability:
    tracer = trace.NoOpTracerProvider().get_tracer("promptql.runtime")
    meter = metrics.NoOpMeterProvider().get_meter("promptql.runtime")
    return Observability(
        runtime_telemetry=RuntimeTelemetry(tracer, meter, event_logger),
        event_logger=event_logger,
    )


def create_observability(
    settings: TelemetrySettings | None = None,
) -> Observability:
    pass

    event_logger = StructuredEventLogger(configure_structured_logger())
    try:
        resolved_settings = settings or TelemetrySettings.from_environment()
        if not resolved_settings.enabled:
            return _disabled_observability(event_logger)

        resource = Resource.create(
            {SERVICE_NAME: resolved_settings.service_name}
        )
        tracer_provider = TracerProvider(
            resource=resource,
            shutdown_on_exit=False,
        )
        metric_readers = []

        if resolved_settings.console_enabled:
            console_span_exporter = FailureIsolatingSpanExporter(
                ConsoleSpanExporter(),
                event_logger,
            )
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    console_span_exporter,
                    max_queue_size=MAX_SPAN_QUEUE_SIZE,
                    max_export_batch_size=MAX_SPAN_EXPORT_BATCH_SIZE,
                    export_timeout_millis=EXPORT_TIMEOUT_MILLIS,
                )
            )
            metric_readers.append(
                PeriodicExportingMetricReader(
                    FailureIsolatingMetricExporter(
                        ConsoleMetricExporter(),
                        event_logger,
                    ),
                    export_interval_millis=METRIC_EXPORT_INTERVAL_MILLIS,
                    export_timeout_millis=EXPORT_TIMEOUT_MILLIS,
                )
            )

        if resolved_settings.otlp_endpoint is not None:
            _quiet_otlp_internal_loggers()
            trace_exporter = FailureIsolatingSpanExporter(
                OTLPSpanExporter(
                    endpoint=(
                        f"{resolved_settings.otlp_endpoint}/v1/traces"
                    ),
                    headers=resolved_settings.otlp_headers,
                    timeout=EXPORT_TIMEOUT_MILLIS / 1_000,
                ),
                event_logger,
            )
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    trace_exporter,
                    max_queue_size=MAX_SPAN_QUEUE_SIZE,
                    max_export_batch_size=MAX_SPAN_EXPORT_BATCH_SIZE,
                    export_timeout_millis=EXPORT_TIMEOUT_MILLIS,
                )
            )
            metric_readers.append(
                PeriodicExportingMetricReader(
                    FailureIsolatingMetricExporter(
                        OTLPMetricExporter(
                            endpoint=(
                                f"{resolved_settings.otlp_endpoint}/v1/metrics"
                            ),
                            headers=resolved_settings.otlp_headers,
                            timeout=EXPORT_TIMEOUT_MILLIS / 1_000,
                        ),
                        event_logger,
                    ),
                    export_interval_millis=METRIC_EXPORT_INTERVAL_MILLIS,
                    export_timeout_millis=EXPORT_TIMEOUT_MILLIS,
                )
            )

        meter_provider = MeterProvider(
            metric_readers=metric_readers,
            resource=resource,
            shutdown_on_exit=False,
        )
        runtime_telemetry = RuntimeTelemetry(
            tracer_provider.get_tracer("promptql.runtime", "1"),
            meter_provider.get_meter("promptql.runtime", "1"),
            event_logger,
        )
        return Observability(
            runtime_telemetry=runtime_telemetry,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            event_logger=event_logger,
        )
    except Exception:


        event_logger.emit(
            "runtime.telemetry.export_failed",
            logging.WARNING,
            telemetry_signal="setup",
            failure_category=FailureCategory.TELEMETRY_EXPORT_FAILURE,
        )
        return _disabled_observability(event_logger)

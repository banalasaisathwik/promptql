pass

import io
import logging
from dataclasses import dataclass

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.observability import RuntimeTelemetry
from app.observability.structured_logging import StructuredEventLogger


@dataclass
class TelemetryTestHarness:
    telemetry: RuntimeTelemetry
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader
    log_stream: io.StringIO

    def metric_points(self, metric_name: str):
        metrics_data = self.metric_reader.get_metrics_data()
        if metrics_data is None:
            return []
        points = []
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    if metric.name == metric_name:
                        points.extend(metric.data.data_points)
        return points

    def shutdown(self) -> None:
        self.meter_provider.shutdown()
        self.tracer_provider.shutdown()


def create_telemetry_harness() -> TelemetryTestHarness:
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(shutdown_on_exit=False)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(
        metric_readers=[metric_reader],
        shutdown_on_exit=False,
    )

    log_stream = io.StringIO()
    logger = logging.Logger("promptql.observability.test")
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    telemetry = RuntimeTelemetry(
        tracer_provider.get_tracer("promptql.test"),
        meter_provider.get_meter("promptql.test"),
        StructuredEventLogger(logger),
    )
    return TelemetryTestHarness(
        telemetry=telemetry,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_exporter=span_exporter,
        metric_reader=metric_reader,
        log_stream=log_stream,
    )

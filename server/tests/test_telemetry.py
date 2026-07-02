"""
Tests for the OpenTelemetry metrics + traces layer (app/telemetry.py).

These wire in-memory OTEL readers/exporters (no collector, no network) and run
a deterministic lexical ``resolve_kits`` to assert the right metrics and spans
are emitted — and that no task text leaks into either.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app import resolver, telemetry


def _write_kit(base: Path) -> None:
    instr = base / "kit-alpha" / "v1" / "instructions"
    instr.mkdir(parents=True)
    sections = [
        {
            "file": "invariant.md",
            "title": "Architecture invariants",
            "gloss": "Non-negotiables for FastAPI layering",
            "always_load": True,
            "body": "## Invariants\n\nKeep it layered.\n",
        },
        {
            "file": "endpoints.md",
            "title": "REST endpoints",
            "gloss": "How to add a REST API endpoint route",
            "always_load": False,
            "body": "## Endpoints\n\nAdd routers and paths.\n",
        },
    ]
    lines = ['summary = "Alpha summary."', ""]
    for section in sections:
        (instr / section["file"]).write_text(section["body"], encoding="utf-8")
        lines += [
            "[[sections]]",
            f'file = "{section["file"]}"',
            f'title = "{section["title"]}"',
            f'gloss = "{section["gloss"]}"',
            f"always_load = {'true' if section['always_load'] else 'false'}",
            "",
        ]
    (instr / "index.toml").write_text("\n".join(lines), encoding="utf-8")
    (base / "kit-alpha" / "applicability.json").write_text(
        json.dumps(
            {
                "kit_type": "module",
                "summary": "FastAPI backend guidance for Python services.",
                "domains": ["api-design", "backend"],
                "languages": ["python"],
                "frameworks": ["fastapi"],
                "contexts": ["backend"],
                "requires": {
                    "languages": [],
                    "frameworks": [],
                    "capabilities": [],
                    "contexts": [],
                },
                "excludes": {
                    "languages": [],
                    "frameworks": [],
                    "capabilities": [],
                    "contexts": [],
                },
                "optional_signals": ["rest-api"],
                "related_kits": [],
                "priority": 70,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Wire a catalog + in-memory OTEL providers and the lexical floor."""
    _write_kit(tmp_path)
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": tmp_path})(),
    )
    monkeypatch.setattr(resolver, "_build_trait_engines", lambda: [])

    telemetry.reset_for_test()
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    settings = type("S", (), {"metrics_section_level": True})()
    telemetry.init_telemetry(
        settings,
        meter_provider=meter_provider,
        tracer_provider=tracer_provider,
    )
    yield reader, exporter
    telemetry.reset_for_test()


def _points(reader: InMemoryMetricReader) -> dict[str, list[Any]]:
    """Return ``{metric_name: [data_point, ...]}`` from a reader."""
    data = reader.get_metrics_data()
    out: dict[str, list[Any]] = {}
    if data is None:
        return out
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                out.setdefault(metric.name, []).extend(metric.data.data_points)
    return out


def test_resolve_emits_core_metrics(harness: Any) -> None:
    reader, _exporter = harness
    resolver.resolve_kits(task="add a FastAPI REST endpoint")
    points = _points(reader)

    # Call-level metrics.
    assert points["qm.resolve.calls"][0].value == 1
    engine_pts = points["qm.resolve.engine"]
    assert any(p.attributes.get("engine") == "lexical" for p in engine_pts)

    # Headline delivered-tokens histogram.
    delivered = points["qm.resolve.delivered_tokens"][0]
    assert delivered.count == 1
    assert delivered.sum > 0


def test_resolve_records_sampling_as_its_own_engine(harness: Any) -> None:
    """MCP-sampling resolves surface ``sampling`` in ``qm.resolve.engine``.

    Sampling is inferred in the tool wrapper (:mod:`app.main`) and handed to
    the resolver as ``pre_inferred``; this guards that its ``engine`` label
    reaches the metric as a distinct value rather than being lost or lumped in
    with the fallback chain.
    """
    from app.resolver import InferredTrait, InferredTraits

    reader, _exporter = harness
    pre_inferred = InferredTraits(
        languages=["python"],
        frameworks=["fastapi"],
        capabilities=[],
        contexts=["backend"],
        provenance=[InferredTrait("languages", "python", "sampling")],
        engine="sampling",
    )
    resolver.resolve_kits(
        task="add a FastAPI REST endpoint", pre_inferred=pre_inferred
    )
    points = _points(reader)

    engines = {p.attributes.get("engine") for p in points["qm.resolve.engine"]}
    assert "sampling" in engines


def test_resolve_emits_kit_and_section_deliveries(harness: Any) -> None:
    reader, _exporter = harness
    resolver.resolve_kits(task="add a FastAPI REST endpoint")
    points = _points(reader)

    kit_pts = points["qm.kit.deliveries"]
    inlined = [
        p
        for p in kit_pts
        if p.attributes.get("kit") == "kit-alpha"
        and p.attributes.get("disposition") == "inlined"
    ]
    assert inlined
    # Domain attribution covers both declared domains.
    domains = {p.attributes.get("domain") for p in kit_pts}
    assert {"api-design", "backend"} <= domains

    # Section-level metrics are on in this harness.
    section_pts = points["qm.section.deliveries"]
    assert any(
        p.attributes.get("section_id") == "invariant" for p in section_pts
    )


def test_catalog_gauges_report_per_domain(harness: Any) -> None:
    reader, _exporter = harness
    # Touch the pipeline so the catalog is loaded at least once.
    resolver.resolve_kits(task="add a FastAPI REST endpoint")
    points = _points(reader)

    kit_gauge = points["qm.catalog.kits"]
    by_domain = {p.attributes.get("domain"): p.value for p in kit_gauge}
    assert by_domain.get("api-design") == 1
    assert by_domain.get("backend") == 1
    assert points["qm.catalog.total_tokens"]
    assert points["qm.catalog.always_load_tokens"]


def test_resolve_emits_pipeline_spans(harness: Any) -> None:
    _reader, exporter = harness
    resolver.resolve_kits(task="add a FastAPI REST endpoint")
    names = {span.name for span in exporter.get_finished_spans()}
    assert {"resolve.infer", "resolve.select", "resolve.assemble"} <= names


def test_no_task_text_in_metrics_or_spans(harness: Any) -> None:
    reader, exporter = harness
    task = "add a FastAPI REST endpoint"
    resolver.resolve_kits(task=task)

    for pts in _points(reader).values():
        for point in pts:
            for value in point.attributes.values():
                assert task not in str(value)

    for span in exporter.get_finished_spans():
        for value in (span.attributes or {}).values():
            assert task not in str(value)


class _FakeResult:
    """Stand-in for an OTLP export-result enum member (has a ``.name``)."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeExporter:
    """Exporter double whose ``export`` returns a queued result."""

    def __init__(self, results: list[str]) -> None:
        self._results = list(results)
        self.calls: list[tuple] = []

    def export(self, *args: Any, **kwargs: Any) -> _FakeResult:
        self.calls.append(args)
        return _FakeResult(self._results.pop(0))

    def shutdown(self) -> None:
        """Delegated-through attribute the proxy must expose."""


def test_export_health_empty_without_otlp() -> None:
    telemetry.reset_for_test()
    assert telemetry.export_health() == []


def test_wrapper_records_success_and_failure() -> None:
    telemetry.reset_for_test()
    inner = _FakeExporter(["SUCCESS", "FAILURE"])
    wrapped = telemetry._wrap_exporter("metrics", inner)

    # Configured-but-not-exported shows up immediately with ok=None.
    health = telemetry.export_health()
    assert health == [{"signal": "metrics", "ok": None, "age_seconds": None}]

    wrapped.export({"some": "batch"})
    assert telemetry.export_health()[0]["ok"] is True

    wrapped.export({"some": "batch"})
    entry = telemetry.export_health()[0]
    assert entry["ok"] is False
    assert entry["age_seconds"] is not None and entry["age_seconds"] >= 0.0
    # Non-export attributes delegate to the wrapped exporter.
    wrapped.shutdown()
    assert inner.calls  # export was really delegated


def test_wrapper_records_failure_on_exception() -> None:
    telemetry.reset_for_test()

    class _Boom:
        def export(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("network down")

    wrapped = telemetry._wrap_exporter("traces", _Boom())
    with pytest.raises(RuntimeError):
        wrapped.export(["span"])
    assert telemetry.export_health()[0]["ok"] is False


def test_logging_handler_uses_contrib_without_deprecation() -> None:
    """The stdlib->OTLP bridge must use the non-deprecated contrib handler.

    opentelemetry-sdk 1.43 deprecated its own ``LoggingHandler``; we must build
    the one from opentelemetry-instrumentation-logging and emit no
    ``DeprecationWarning`` doing so.
    """
    from opentelemetry.sdk._logs import LoggerProvider

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        handler = telemetry._build_logging_handler(LoggerProvider())

    assert handler is not None
    assert "instrumentation.logging" in type(handler).__module__


def test_records_are_noop_before_init() -> None:
    """Recording helpers must be safe to call before init / without OTEL."""
    telemetry.reset_for_test()
    # These must not raise even though no provider/instruments exist yet.
    telemetry.record_gap_request()
    telemetry.record_gap_detected()
    telemetry.record_tool_call("get_kit", True, 1.0)
    telemetry.record_kit_delivery(
        kit="x", disposition="full", tokens=1, section_ids=[]
    )
    with telemetry.span("noop") as active:
        active.set_attribute("k", "v")

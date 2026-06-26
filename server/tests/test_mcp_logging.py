"""Tests for the MCP tool-call audit middleware."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app import telemetry
from app.mcp_logging import ToolCallAuditMiddleware


def _ctx(*, session_id="sess-1", client_id="vscode", tool_name="select_kits"):
    """Build a minimal MiddlewareContext-like stub."""
    return SimpleNamespace(
        fastmcp_context=SimpleNamespace(
            session_id=session_id, client_id=client_id
        ),
        message=SimpleNamespace(name=tool_name),
    )


def test_on_call_tool_logs_name_session_and_sequence(caplog):
    mw = ToolCallAuditMiddleware()

    async def call_next(ctx):
        return "ok-result"

    with caplog.at_level(logging.INFO, logger="app.mcp_audit"):
        r1 = asyncio.run(
            mw.on_call_tool(_ctx(tool_name="select_kits"), call_next)
        )
        r2 = asyncio.run(mw.on_call_tool(_ctx(tool_name="get_kit"), call_next))

    assert r1 == "ok-result" and r2 == "ok-result"
    lines = [r.getMessage() for r in caplog.records]
    assert any(
        "event=tool_call" in m and "tool=select_kits" in m and "seq=1" in m
        for m in lines
    )
    # Sequence is monotonic per session.
    assert any(
        "event=tool_call" in m and "tool=get_kit" in m and "seq=2" in m
        for m in lines
    )
    assert all("session=sess-1" in m for m in lines)


def test_sequence_is_per_session(caplog):
    mw = ToolCallAuditMiddleware()

    async def call_next(ctx):
        return None

    with caplog.at_level(logging.INFO, logger="app.mcp_audit"):
        asyncio.run(mw.on_call_tool(_ctx(session_id="a"), call_next))
        asyncio.run(mw.on_call_tool(_ctx(session_id="b"), call_next))

    lines = [r.getMessage() for r in caplog.records]
    assert any("session=a" in m and "seq=1" in m for m in lines)
    assert any("session=b" in m and "seq=1" in m for m in lines)


def test_on_initialize_logs_session_start(caplog):
    mw = ToolCallAuditMiddleware()

    async def call_next(ctx):
        return "init-result"

    with caplog.at_level(logging.INFO, logger="app.mcp_audit"):
        result = asyncio.run(mw.on_initialize(_ctx(), call_next))

    assert result == "init-result"
    lines = [r.getMessage() for r in caplog.records]
    assert any("event=initialize" in m and "session=sess-1" in m for m in lines)


def test_tool_error_is_logged_and_reraised(caplog):
    mw = ToolCallAuditMiddleware()

    async def call_next(ctx):
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="app.mcp_audit"):
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(mw.on_call_tool(_ctx(), call_next))

    lines = [r.getMessage() for r in caplog.records]
    assert any("event=tool_call" in m and "ok=False" in m for m in lines)


def test_logging_failure_never_breaks_the_call(monkeypatch):
    """A broken logger must not propagate out of a tool call."""
    mw = ToolCallAuditMiddleware()

    def explode(*args, **kwargs):
        raise ValueError("logger down")

    monkeypatch.setattr("app.mcp_logging.logger.info", explode)

    async def call_next(ctx):
        return "still-ok"

    # on_call_tool succeeds despite the logger raising in the finally block.
    assert asyncio.run(mw.on_call_tool(_ctx(), call_next)) == "still-ok"
    # on_initialize likewise.
    assert asyncio.run(mw.on_initialize(_ctx(), call_next)) == "still-ok"


@pytest.fixture()
def otel_capture() -> Any:
    """Wire in-memory OTEL providers for the middleware to emit into."""
    telemetry.reset_for_test()
    reader = InMemoryMetricReader()
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.init_telemetry(
        type("S", (), {"metrics_section_level": False})(),
        meter_provider=MeterProvider(metric_readers=[reader]),
        tracer_provider=tracer_provider,
    )
    yield reader, exporter
    telemetry.reset_for_test()


def test_on_call_tool_emits_span_and_duration(otel_capture):
    reader, exporter = otel_capture
    mw = ToolCallAuditMiddleware()

    async def call_next(ctx):
        return "ok"

    asyncio.run(mw.on_call_tool(_ctx(tool_name="resolve_kits"), call_next))

    spans = exporter.get_finished_spans()
    assert any(s.name == "mcp.tool.resolve_kits" for s in spans)

    data = reader.get_metrics_data()
    names = {
        m.name
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
    }
    assert "qm.tool.duration" in names
    assert "qm.tool.calls" in names


def test_telemetry_failure_never_breaks_the_call(otel_capture, monkeypatch):
    """A broken telemetry recorder must not propagate out of a tool call."""
    mw = ToolCallAuditMiddleware()

    def explode(*args, **kwargs):
        raise ValueError("telemetry down")

    # record_tool_call swallows its own errors; even if it did not, the call
    # must still return. Force the failure to prove the discipline.
    monkeypatch.setattr(telemetry, "record_tool_call", explode)

    async def call_next(ctx):
        return "still-ok"

    assert asyncio.run(mw.on_call_tool(_ctx(), call_next)) == "still-ok"

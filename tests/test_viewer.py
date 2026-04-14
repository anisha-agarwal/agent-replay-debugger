"""Tests for the HTML viewer generator."""

from ard.schema import Event, Span, Trace
from ard.viewer import generate_html


class TestGenerateHtml:
    def test_replaces_placeholder(self):
        trace = Trace(
            trace_id="test-1",
            framework="test",
            started_at="2026-04-10T10:00:00Z",
        )
        html = generate_html(trace)
        assert "TRACE_DATA_PLACEHOLDER" not in html
        assert '"trace_id": "test-1"' in html

    def test_contains_viewer_structure(self):
        trace = Trace(
            trace_id="test-1",
            framework="test",
            started_at="2026-04-10T10:00:00Z",
        )
        html = generate_html(trace)
        assert "Agent Replay Debugger" in html
        assert 'id="header"' in html
        assert 'id="stats"' in html
        assert 'id="dag"' in html
        assert 'id="events"' in html

    def test_embeds_trace_data(self):
        trace = Trace(
            trace_id="viewer-test",
            framework="my-framework",
            session_type="execution",
            title="My test session",
            status="completed",
            started_at="2026-04-10T10:00:00Z",
            spans=[Span(span_id="s1", name="step1", kind="step", status="passed")],
            events=[Event(timestamp="2026-04-10T10:00:00Z", type="lifecycle", name="started")],
        )
        html = generate_html(trace)
        assert '"framework": "my-framework"' in html
        assert '"title": "My test session"' in html
        assert '"span_id": "s1"' in html

    def test_self_contained(self):
        trace = Trace(
            trace_id="test-1",
            framework="test",
            started_at="2026-04-10T10:00:00Z",
        )
        html = generate_html(trace)
        assert "<style>" in html
        assert "<script>" in html
        assert "DOMContentLoaded" in html

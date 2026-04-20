"""Tests for trace diff."""

from ard.diff import diff_traces, _extract_files, _pct_change
from ard.schema import Span, ToolCall, Trace


def _make_trace(title, spans, events=None):
    t = Trace(
        trace_id="t",
        framework="test",
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T01:00:00Z",
        title=title,
        spans=spans,
        events=events or [],
    )
    t.compute_summary()
    return t


class TestDiffTraces:
    def test_identical_traces(self):
        spans = [
            Span(
                span_id="a",
                name="step-a",
                kind="step",
                status="passed",
                started_at="2026-01-01T00:00:00Z",
                ended_at="2026-01-01T00:05:00Z",
            )
        ]
        a = _make_trace("run 1", spans)
        b = _make_trace("run 2", spans)
        d = diff_traces(a, b)
        assert d.faster_spans == 0
        assert d.slower_spans == 0
        assert d.new_spans == 0
        assert d.removed_spans == 0
        assert d.status_changes == 0

    def test_duration_delta(self):
        a = _make_trace(
            "fast",
            [
                Span(
                    span_id="a",
                    name="work",
                    kind="step",
                    status="passed",
                    started_at="2026-01-01T00:00:00Z",
                    ended_at="2026-01-01T00:05:00Z",
                )
            ],
        )
        b = _make_trace(
            "slow",
            [
                Span(
                    span_id="a",
                    name="work",
                    kind="step",
                    status="passed",
                    started_at="2026-01-01T00:00:00Z",
                    ended_at="2026-01-01T00:10:00Z",
                )
            ],
        )
        d = diff_traces(a, b)
        assert d.slower_spans == 1
        assert d.span_diffs[0].duration_delta_ms > 0

    def test_faster_span(self):
        a = _make_trace(
            "slow",
            [
                Span(
                    span_id="a",
                    name="work",
                    kind="step",
                    status="passed",
                    started_at="2026-01-01T00:00:00Z",
                    ended_at="2026-01-01T00:10:00Z",
                )
            ],
        )
        b = _make_trace(
            "fast",
            [
                Span(
                    span_id="a",
                    name="work",
                    kind="step",
                    status="passed",
                    started_at="2026-01-01T00:00:00Z",
                    ended_at="2026-01-01T00:05:00Z",
                )
            ],
        )
        d = diff_traces(a, b)
        assert d.faster_spans == 1
        assert d.span_diffs[0].duration_delta_ms < 0

    def test_new_span(self):
        a = _make_trace("v1", [])
        b = _make_trace("v2", [Span(span_id="new", name="new-step", kind="step", status="passed")])
        d = diff_traces(a, b)
        assert d.new_spans == 1
        assert d.span_diffs[0].only_in == "b"

    def test_removed_span(self):
        a = _make_trace("v1", [Span(span_id="old", name="old-step", kind="step", status="passed")])
        b = _make_trace("v2", [])
        d = diff_traces(a, b)
        assert d.removed_spans == 1
        assert d.span_diffs[0].only_in == "a"

    def test_status_change(self):
        a = _make_trace("v1", [Span(span_id="a", name="test", kind="step", status="passed")])
        b = _make_trace("v2", [Span(span_id="a", name="test", kind="step", status="failed")])
        d = diff_traces(a, b)
        assert d.status_changes == 1

    def test_tool_count_delta(self):
        a = _make_trace(
            "v1",
            [
                Span(
                    span_id="a",
                    name="code",
                    kind="step",
                    status="passed",
                    tool_calls=[ToolCall(kind="file_read", target="a.ts")],
                )
            ],
        )
        b = _make_trace(
            "v2",
            [
                Span(
                    span_id="a",
                    name="code",
                    kind="step",
                    status="passed",
                    tool_calls=[
                        ToolCall(kind="file_read", target="a.ts"),
                        ToolCall(kind="file_write", target="b.ts"),
                        ToolCall(kind="command", target="npm test"),
                    ],
                )
            ],
        )
        d = diff_traces(a, b)
        assert d.span_diffs[0].tools_delta == 2

    def test_file_diffs(self):
        a = _make_trace(
            "v1",
            [
                Span(
                    span_id="a",
                    name="code",
                    kind="step",
                    status="passed",
                    tool_calls=[
                        ToolCall(kind="file_read", target="shared.ts"),
                        ToolCall(kind="file_write", target="only-a.ts"),
                    ],
                )
            ],
        )
        b = _make_trace(
            "v2",
            [
                Span(
                    span_id="a",
                    name="code",
                    kind="step",
                    status="passed",
                    tool_calls=[
                        ToolCall(kind="file_read", target="shared.ts"),
                        ToolCall(kind="file_write", target="only-b.ts"),
                    ],
                )
            ],
        )
        d = diff_traces(a, b)
        assert d.files_both == 1
        assert d.files_only_a == 1
        assert d.files_only_b == 1

    def test_to_dict(self):
        a = _make_trace("a", [Span(span_id="s", name="s", kind="step", status="passed")])
        b = _make_trace("b", [Span(span_id="s", name="s", kind="step", status="passed")])
        d = diff_traces(a, b)
        result = d.to_dict()
        assert result["title_a"] == "a"
        assert result["title_b"] == "b"
        assert isinstance(result["span_diffs"], list)
        assert isinstance(result["file_diffs"], list)

    def test_no_duration(self):
        a = _make_trace("a", [Span(span_id="s", name="s", kind="step", status="passed")])
        b = _make_trace("b", [Span(span_id="s", name="s", kind="step", status="passed")])
        d = diff_traces(a, b)
        assert d.span_diffs[0].duration_delta_ms is None


class TestHelpers:
    def test_pct_change(self):
        assert _pct_change(100, 150) == 50.0
        assert _pct_change(100, 50) == -50.0
        assert _pct_change(0, 100) is None
        assert _pct_change(None, 100) is None
        assert _pct_change(100, None) is None

    def test_extract_files(self):
        trace = _make_trace(
            "t",
            [
                Span(
                    span_id="s",
                    name="s",
                    kind="step",
                    status="passed",
                    tool_calls=[
                        ToolCall(kind="file_read", target="a.ts"),
                        ToolCall(kind="file_write", target="b.ts"),
                        ToolCall(kind="command", target="npm test"),
                    ],
                )
            ],
        )
        files = _extract_files(trace)
        assert files == {"a.ts", "b.ts"}

    def test_extract_files_empty_target(self):
        trace = _make_trace(
            "t",
            [
                Span(
                    span_id="s",
                    name="s",
                    kind="step",
                    status="passed",
                    tool_calls=[ToolCall(kind="file_read", target="")],
                )
            ],
        )
        files = _extract_files(trace)
        assert files == set()

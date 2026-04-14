"""Tests for the universal trace schema."""

from ard.schema import Artifact, Event, Span, ToolCall, Trace, TraceSummary, _duration_ms


class TestDurationMs:
    def test_valid_timestamps(self):
        assert _duration_ms("2026-03-31T14:00:00Z", "2026-03-31T14:35:00Z") == 2_100_000

    def test_none_start(self):
        assert _duration_ms(None, "2026-03-31T14:35:00Z") is None

    def test_none_end(self):
        assert _duration_ms("2026-03-31T14:00:00Z", None) is None

    def test_both_none(self):
        assert _duration_ms(None, None) is None

    def test_invalid_timestamp(self):
        assert _duration_ms("bad", "2026-03-31T14:35:00Z") is None


class TestToolCall:
    def test_roundtrip(self):
        tc = ToolCall(kind="file_read", target="/src/main.ts", timestamp="14:00:05")
        d = tc.to_dict()
        tc2 = ToolCall.from_dict(d)
        assert tc2.kind == "file_read"
        assert tc2.target == "/src/main.ts"
        assert tc2.timestamp == "14:00:05"

    def test_minimal(self):
        tc = ToolCall(kind="command", target="npm test")
        d = tc.to_dict()
        assert "timestamp" not in d
        assert "result" not in d

    def test_with_result(self):
        tc = ToolCall(kind="command", target="ls", result="file1.txt\nfile2.txt")
        d = tc.to_dict()
        assert d["result"] == "file1.txt\nfile2.txt"
        tc2 = ToolCall.from_dict(d)
        assert tc2.result == "file1.txt\nfile2.txt"


class TestSpan:
    def test_duration_computed(self):
        span = Span(
            span_id="code",
            name="code",
            kind="step",
            status="passed",
            started_at="2026-03-31T14:00:00Z",
            ended_at="2026-03-31T14:35:00Z",
        )
        assert span.duration_ms == 2_100_000

    def test_roundtrip(self):
        span = Span(
            span_id="test",
            name="test",
            kind="step",
            status="failed",
            retries=2,
            error="test failed",
            tool_calls=[ToolCall(kind="command", target="npm test")],
            metadata={"checklist": [{"id": "1"}]},
        )
        d = span.to_dict()
        span2 = Span.from_dict(d)
        assert span2.span_id == "test"
        assert span2.retries == 2
        assert span2.error == "test failed"
        assert len(span2.tool_calls) == 1
        assert span2.metadata["checklist"] == [{"id": "1"}]

    def test_all_optional_fields(self):
        span = Span(
            span_id="s1",
            name="s1",
            kind="step",
            status="passed",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T01:00:00Z",
            duration_ms=3600000,
            parent_id="parent",
            retries=3,
            error="some error",
        )
        d = span.to_dict()
        assert d["started_at"] == "2026-01-01T00:00:00Z"
        assert d["ended_at"] == "2026-01-01T01:00:00Z"
        assert d["duration_ms"] == 3600000
        assert d["parent_id"] == "parent"
        assert d["retries"] == 3
        assert d["error"] == "some error"


class TestEvent:
    def test_roundtrip(self):
        evt = Event(
            timestamp="2026-03-31T14:00:00Z",
            type="step",
            name="step_passed",
            span_id="code",
            data={"retries": 0},
        )
        d = evt.to_dict()
        evt2 = Event.from_dict(d)
        assert evt2.timestamp == "2026-03-31T14:00:00Z"
        assert evt2.span_id == "code"
        assert evt2.data == {"retries": 0}


class TestArtifact:
    def test_roundtrip(self):
        art = Artifact(
            name="final-plan.md",
            artifact_type="document",
            span_id="judge",
            content="# Plan\nDo the thing.",
        )
        d = art.to_dict()
        art2 = Artifact.from_dict(d)
        assert art2.name == "final-plan.md"
        assert art2.content == "# Plan\nDo the thing."

    def test_with_path(self):
        art = Artifact(
            name="output.md",
            artifact_type="document",
            path="/tmp/output.md",
        )
        d = art.to_dict()
        assert d["path"] == "/tmp/output.md"
        assert "content" not in d


class TestTraceSummary:
    def test_roundtrip(self):
        s = TraceSummary(total_duration_ms=5000, passed=3, failed=1, retries=2)
        d = s.to_dict()
        s2 = TraceSummary.from_dict(d)
        assert s2.total_duration_ms == 5000
        assert s2.passed == 3
        assert s2.failed == 1


class TestTrace:
    def test_roundtrip(self):
        trace = Trace(
            trace_id="test-123",
            framework="forge",
            session_type="executor",
            title="test run",
            status="completed",
            started_at="2026-03-31T14:00:00Z",
            ended_at="2026-03-31T14:35:00Z",
            spans=[
                Span(span_id="code", name="code", kind="step", status="passed"),
            ],
            events=[
                Event(
                    timestamp="2026-03-31T14:00:00Z",
                    type="lifecycle",
                    name="pipeline_started",
                ),
            ],
            artifacts=[
                Artifact(name="output.md", artifact_type="document"),
            ],
            dependency_graph={"code": []},
        )
        trace.compute_summary()

        d = trace.to_dict()
        trace2 = Trace.from_dict(d)
        assert trace2.trace_id == "test-123"
        assert len(trace2.spans) == 1
        assert len(trace2.events) == 1
        assert len(trace2.artifacts) == 1
        assert trace2.dependency_graph == {"code": []}
        assert trace2.summary.passed == 1

    def test_compute_summary(self):
        trace = Trace(
            trace_id="t1",
            framework="test",
            started_at="2026-03-31T14:00:00Z",
            ended_at="2026-03-31T14:05:00Z",
            spans=[
                Span(
                    span_id="a",
                    name="a",
                    kind="step",
                    status="passed",
                    tool_calls=[
                        ToolCall(kind="file_read", target="f1"),
                        ToolCall(kind="file_write", target="f2"),
                        ToolCall(kind="command", target="ls"),
                    ],
                ),
                Span(span_id="b", name="b", kind="step", status="failed", retries=1),
                Span(span_id="c", name="c", kind="step", status="skipped"),
            ],
            events=[
                Event(timestamp="t", type="error", name="step_failed"),
            ],
        )
        s = trace.compute_summary()
        assert s.total_duration_ms == 300_000
        assert s.span_count == 3
        assert s.passed == 1
        assert s.failed == 1
        assert s.skipped == 1
        assert s.retries == 1
        assert s.files_read == 1
        assert s.files_written == 1
        assert s.commands_run == 1
        assert s.errors == 1

    def test_validate_valid(self):
        trace = Trace(
            trace_id="t1",
            framework="test",
            started_at="2026-03-31T14:00:00Z",
        )
        assert trace.validate() == []

    def test_validate_missing_fields(self):
        trace = Trace(trace_id="", framework="", started_at="")
        issues = trace.validate()
        assert len(issues) == 3
        assert any("trace_id" in i for i in issues)
        assert any("started_at" in i for i in issues)
        assert any("framework" in i for i in issues)

    def test_validate_bad_spans(self):
        trace = Trace(
            trace_id="t1",
            framework="test",
            started_at="2026-01-01T00:00:00Z",
            spans=[
                Span(span_id="", name="unnamed", kind="", status="passed"),
            ],
        )
        issues = trace.validate()
        assert any("span missing span_id" in i for i in issues)
        assert any("span missing kind" in i for i in issues)

    def test_validate_bad_events(self):
        trace = Trace(
            trace_id="t1",
            framework="test",
            started_at="2026-01-01T00:00:00Z",
            events=[
                Event(timestamp="", type="", name="bad_event"),
            ],
        )
        issues = trace.validate()
        assert any("event missing timestamp" in i for i in issues)
        assert any("event missing type" in i for i in issues)

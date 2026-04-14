"""Tests for the generic JSON adapter."""

import json
from pathlib import Path

import pytest

from ard.adapters.generic import GenericAdapter

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def adapter():
    return GenericAdapter()


@pytest.fixture
def generic_session():
    return FIXTURES_DIR / "generic_session"


class TestDetect:
    def test_detects_directory_with_trace_json(self, adapter, generic_session):
        assert adapter.detect(generic_session) is True

    def test_detects_trace_json_file_directly(self, adapter, generic_session):
        assert adapter.detect(generic_session / "trace.json") is True

    def test_rejects_empty_dir(self, adapter, tmp_path):
        assert adapter.detect(tmp_path) is False

    def test_rejects_dir_without_trace_json(self, adapter, tmp_path):
        (tmp_path / "other.json").write_text("{}")
        assert adapter.detect(tmp_path) is False


class TestLoad:
    def test_loads_from_directory(self, adapter, generic_session):
        trace = adapter.load(generic_session)
        assert trace.trace_id == "generic-test-001"
        assert trace.framework == "custom-agent"
        assert trace.status == "completed"

    def test_loads_from_file(self, adapter, generic_session):
        trace = adapter.load(generic_session / "trace.json")
        assert trace.trace_id == "generic-test-001"

    def test_spans(self, adapter, generic_session):
        trace = adapter.load(generic_session)
        assert len(trace.spans) == 3
        names = [s.name for s in trace.spans]
        assert names == ["investigate", "fix", "verify"]

    def test_events(self, adapter, generic_session):
        trace = adapter.load(generic_session)
        assert len(trace.events) == 7
        assert trace.events[0].name == "session_started"
        assert trace.events[-1].name == "session_completed"

    def test_dependency_graph(self, adapter, generic_session):
        trace = adapter.load(generic_session)
        assert trace.dependency_graph == {
            "investigate": [],
            "fix": ["investigate"],
            "verify": ["fix"],
        }

    def test_artifacts(self, adapter, generic_session):
        trace = adapter.load(generic_session)
        assert len(trace.artifacts) == 1
        assert trace.artifacts[0].name == "fix-summary.md"

    def test_summary_computed(self, adapter, generic_session):
        trace = adapter.load(generic_session)
        assert trace.summary.span_count == 3
        assert trace.summary.passed == 3

    def test_tool_calls(self, adapter, generic_session):
        trace = adapter.load(generic_session)
        investigate = trace.spans[0]
        assert len(investigate.tool_calls) == 2
        assert investigate.tool_calls[0].kind == "file_read"

    def test_invalid_trace_raises(self, adapter, tmp_path):
        bad = tmp_path / "trace.json"
        bad.write_text(json.dumps({"trace_id": "", "framework": "", "started_at": ""}))
        with pytest.raises(ValueError, match="Invalid trace.json"):
            adapter.load(bad)

    def test_corrupt_json_raises(self, adapter, tmp_path):
        bad = tmp_path / "trace.json"
        bad.write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            adapter.load(bad)


class TestAutoDetect:
    def test_auto_detects_generic(self, generic_session):
        from ard.adapters.base import detect_adapter

        adapter = detect_adapter(generic_session)
        assert adapter is not None
        trace = adapter.load(generic_session)
        assert trace.framework == "custom-agent"

    def test_auto_detects_trace_file(self, generic_session):
        from ard.adapters.base import detect_adapter

        adapter = detect_adapter(generic_session / "trace.json")
        assert adapter is not None

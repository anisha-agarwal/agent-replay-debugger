"""Tests for the forge adapter."""

import json

import pytest

from ard.adapters.forge import ForgeAdapter, _parse_activity_log, _read_jsonl


@pytest.fixture
def adapter():
    return ForgeAdapter()


class TestDetect:
    def test_detects_executor(self, adapter, executor_session):
        assert adapter.detect(executor_session) is True

    def test_detects_planner(self, adapter, planner_session):
        assert adapter.detect(planner_session) is True

    def test_rejects_unknown(self, adapter, tmp_path):
        assert adapter.detect(tmp_path) is False

    def test_rejects_empty_dir(self, adapter, tmp_path):
        (tmp_path / "random.txt").write_text("hello")
        assert adapter.detect(tmp_path) is False


class TestLoadExecutor:
    def test_basic_fields(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        assert trace.framework == "forge"
        assert trace.session_type == "executor"
        assert trace.title == "full"
        assert trace.status == "failed"
        assert trace.started_at == "2026-03-31T14:00:00Z"

    def test_spans(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        assert len(trace.spans) == 3
        span_map = {s.span_id: s for s in trace.spans}

        assert span_map["code"].status == "passed"
        assert span_map["code"].kind == "step"
        assert span_map["lint"].status == "passed"
        assert span_map["test"].status == "failed"
        assert span_map["test"].retries == 1
        assert "404" in span_map["test"].error

    def test_events(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        assert len(trace.events) >= 11  # base events + possible transcript events
        assert trace.events[0].name == "pipeline_started"
        assert trace.events[0].type == "lifecycle"
        # Verify pipeline_failed exists in events
        assert any(e.name == "pipeline_failed" for e in trace.events)

    def test_dependency_graph(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        assert trace.dependency_graph == {"code": [], "lint": ["code"], "test": ["code"]}

    def test_tool_calls_from_activity_log(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        code_span = next(s for s in trace.spans if s.span_id == "code")
        assert len(code_span.tool_calls) >= 5  # 2 reads + 2 writes + 1 command from log
        kinds = {tc.kind for tc in code_span.tool_calls}
        assert "file_read" in kinds
        assert "file_write" in kinds
        assert "command" in kinds

    def test_checklist_in_metadata(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        code_span = next(s for s in trace.spans if s.span_id == "code")
        assert "checklist" in code_span.metadata

    def test_artifacts(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        assert len(trace.artifacts) >= 2  # at least checklist + actions
        names = {a.name for a in trace.artifacts}
        assert "code-checklist.json" in names
        assert "code-actions.json" in names

    def test_summary(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        assert trace.summary.passed == 2
        assert trace.summary.failed == 1
        assert trace.summary.retries == 1
        assert trace.summary.span_count == 3

    def test_metadata(self, adapter, executor_session):
        trace = adapter.load(executor_session)
        assert trace.metadata["pipeline"] == "full"
        assert trace.metadata["preset"] == "default"


class TestLoadPlanner:
    def test_basic_fields(self, adapter, planner_session):
        trace = adapter.load(planner_session)
        assert trace.framework == "forge"
        assert trace.session_type == "planner"
        assert trace.status == "completed"
        assert "Refactor" in trace.title

    def test_spans(self, adapter, planner_session):
        trace = adapter.load(planner_session)
        assert len(trace.spans) == 6  # all 6 phases
        span_map = {s.span_id: s for s in trace.spans}

        assert span_map["recon"].status == "passed"
        assert span_map["recon"].kind == "phase"
        assert span_map["judge"].status == "passed"
        assert span_map["enrichment"].status == "skipped"

    def test_events(self, adapter, planner_session):
        trace = adapter.load(planner_session)
        assert len(trace.events) == 12
        assert trace.events[0].name == "planner_started"
        assert trace.events[-1].name == "planner_completed"

    def test_dependency_chain(self, adapter, planner_session):
        trace = adapter.load(planner_session)
        graph = trace.dependency_graph
        assert graph["recon"] == []
        assert graph["architects"] == ["recon"]
        assert graph["critics"] == ["architects"]
        assert graph["refiners"] == ["critics"]
        assert graph["judge"] == ["refiners"]
        assert graph["enrichment"] == ["judge"]

    def test_artifacts(self, adapter, planner_session):
        trace = adapter.load(planner_session)
        names = {a.name for a in trace.artifacts}
        assert "design-a.md" in names
        assert "final-plan.md" in names

    def test_artifact_content(self, adapter, planner_session):
        trace = adapter.load(planner_session)
        plan = next(a for a in trace.artifacts if a.name == "final-plan.md")
        assert "Router Refactor" in plan.content

    def test_tool_calls_from_activity(self, adapter, planner_session):
        trace = adapter.load(planner_session)
        recon = next(s for s in trace.spans if s.span_id == "recon")
        assert len(recon.tool_calls) == 3
        assert all(tc.kind == "file_read" for tc in recon.tool_calls)


class TestActivityLogParsing:
    def test_parses_all_action_types(self, tmp_path):
        log = tmp_path / "activity.log"
        log.write_text(
            "[14:00:05] step1  read: /src/file.ts\n"
            "[14:00:06] step1  write: /src/file.ts\n"
            "[14:00:07] step1  bash: npm test\n"
            "[14:00:08] step1  error: something broke\n"
        )
        result = _parse_activity_log(log)
        assert len(result["step1"]) == 4
        kinds = [tc.kind for tc in result["step1"]]
        assert kinds == ["file_read", "file_write", "command", "command"]

    def test_groups_by_step(self, tmp_path):
        log = tmp_path / "activity.log"
        log.write_text(
            "[14:00:05] code  read: /src/a.ts\n"
            "[14:00:06] lint  bash: eslint .\n"
            "[14:00:07] code  write: /src/b.ts\n"
        )
        result = _parse_activity_log(log)
        assert len(result["code"]) == 2
        assert len(result["lint"]) == 1

    def test_missing_file(self, tmp_path):
        result = _parse_activity_log(tmp_path / "nonexistent.log")
        assert result == {}

    def test_malformed_lines_skipped(self, tmp_path):
        log = tmp_path / "activity.log"
        log.write_text("not a valid line\n[14:00:05] step1  read: /src/file.ts\n")
        result = _parse_activity_log(log)
        assert len(result["step1"]) == 1


class TestReadJsonl:
    def test_reads_valid_jsonl(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text('{"a": 1}\n{"b": 2}\n')
        result = _read_jsonl(f)
        assert len(result) == 2

    def test_skips_corrupt_lines(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text('{"a": 1}\nnot json\n{"b": 2}\n')
        result = _read_jsonl(f)
        assert len(result) == 2

    def test_missing_file(self, tmp_path):
        result = _read_jsonl(tmp_path / "nope.jsonl")
        assert result == []

    def test_skips_empty_lines(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text('{"a": 1}\n\n\n{"b": 2}\n')
        result = _read_jsonl(f)
        assert len(result) == 2


class TestTranscriptEvents:
    def test_transcript_injects_reasoning_and_tool_events(self, adapter, tmp_path):
        state = {
            "phase": "execution",
            "pipeline": "full",
            "steps": {"code": {"status": "complete", "started_at": "2026-03-31T14:00:00Z"}},
            "step_order": ["code"],
            "dependency_graph": {"code": []},
            "killed": False,
            "created_at": "2026-03-31T14:00:00Z",
        }
        (tmp_path / "agent-state.json").write_text(json.dumps(state))
        (tmp_path / "code-transcript.log").write_text(
            "I'll read the file first.\n"
            "[Read] /src/main.ts\n"
            "Now I'll fix it.\n"
            "[Edit] /src/main.ts\n"
        )
        trace = adapter.load(tmp_path)
        reasoning = [e for e in trace.events if e.type == "reasoning"]
        tools = [e for e in trace.events if e.type == "tool"]
        assert len(reasoning) == 2
        assert len(tools) == 2
        assert reasoning[0].data["text"] == "I'll read the file first."

    def test_transcript_reasoning_in_metadata(self, adapter, tmp_path):
        state = {
            "phase": "execution",
            "pipeline": "full",
            "steps": {"code": {"status": "complete", "started_at": "2026-03-31T14:00:00Z"}},
            "step_order": ["code"],
            "dependency_graph": {"code": []},
            "killed": False,
            "created_at": "2026-03-31T14:00:00Z",
        }
        (tmp_path / "agent-state.json").write_text(json.dumps(state))
        (tmp_path / "code-transcript.log").write_text("Agent thinking here.\n")
        trace = adapter.load(tmp_path)
        code_span = trace.spans[0]
        assert "reasoning" in code_span.metadata
        assert len(code_span.metadata["reasoning"]) == 1


class TestArtifactCollection:
    def test_verdict_files(self, adapter, tmp_path):
        state = {
            "phase": "execution",
            "pipeline": "full",
            "steps": {"code": {"status": "complete"}},
            "step_order": ["code"],
            "dependency_graph": {"code": []},
            "killed": False,
            "created_at": "2026-03-31T14:00:00Z",
        }
        (tmp_path / "agent-state.json").write_text(json.dumps(state))
        (tmp_path / "code-review-verdict.json").write_text(json.dumps({"verdict": "CLEAN"}))
        trace = adapter.load(tmp_path)
        verdicts = [a for a in trace.artifacts if a.artifact_type == "verdict"]
        assert len(verdicts) == 1
        assert "CLEAN" in verdicts[0].content

    def test_pipeline_output(self, adapter, tmp_path):
        state = {
            "phase": "execution",
            "pipeline": "full",
            "steps": {"code": {"status": "complete"}},
            "step_order": ["code"],
            "dependency_graph": {"code": []},
            "killed": False,
            "created_at": "2026-03-31T14:00:00Z",
        }
        (tmp_path / "agent-state.json").write_text(json.dumps(state))
        (tmp_path / "pipeline-output.md").write_text("# Summary\nAll done.")
        trace = adapter.load(tmp_path)
        docs = [a for a in trace.artifacts if a.name == "pipeline-output.md"]
        assert len(docs) == 1
        assert "All done" in docs[0].content

    def test_actions_fallback_when_no_activity_log(self, adapter, tmp_path):
        state = {
            "phase": "execution",
            "pipeline": "full",
            "steps": {"lint": {"status": "complete"}},
            "step_order": ["lint"],
            "dependency_graph": {"lint": []},
            "killed": False,
            "created_at": "2026-03-31T14:00:00Z",
        }
        (tmp_path / "agent-state.json").write_text(json.dumps(state))
        (tmp_path / "lint-actions.json").write_text(
            json.dumps(
                {
                    "files_read": ["a.ts"],
                    "files_written": ["b.ts"],
                    "commands": ["eslint ."],
                }
            )
        )
        trace = adapter.load(tmp_path)
        lint_span = trace.spans[0]
        assert len(lint_span.tool_calls) == 3


class TestOverallStatus:
    def test_running_status(self, adapter, tmp_path):
        state = {
            "phase": "execution",
            "pipeline": "full",
            "steps": {"code": {"status": "in_progress"}},
            "step_order": ["code"],
            "dependency_graph": {"code": []},
            "killed": False,
            "created_at": "2026-03-31T14:00:00Z",
        }
        (tmp_path / "agent-state.json").write_text(json.dumps(state))
        trace = adapter.load(tmp_path)
        assert trace.status == "running"


class TestEdgeCases:
    def test_no_state_file_raises(self, adapter, tmp_path):
        with pytest.raises(ValueError, match="No forge state file found"):
            adapter.load(tmp_path)

    def test_killed_session(self, adapter, tmp_path):
        state = {
            "phase": "execution",
            "pipeline": "full",
            "steps": {"code": {"status": "in_progress"}},
            "step_order": ["code"],
            "dependency_graph": {"code": []},
            "killed": True,
            "kill_reason": "SIGINT",
            "created_at": "2026-03-31T14:00:00Z",
            "updated_at": "2026-03-31T14:05:00Z",
        }
        (tmp_path / "agent-state.json").write_text(json.dumps(state))
        trace = adapter.load(tmp_path)
        assert trace.status == "killed"

    def test_empty_steps(self, adapter, tmp_path):
        state = {
            "phase": "execution",
            "pipeline": "test",
            "steps": {},
            "step_order": [],
            "dependency_graph": {},
            "killed": False,
            "created_at": "2026-03-31T14:00:00Z",
        }
        (tmp_path / "agent-state.json").write_text(json.dumps(state))
        trace = adapter.load(tmp_path)
        assert len(trace.spans) == 0
        assert trace.summary.span_count == 0

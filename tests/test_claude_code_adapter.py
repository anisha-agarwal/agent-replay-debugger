"""Tests for the Claude Code session adapter."""

import json
from pathlib import Path

import pytest

from ard.adapters.claude_code import ClaudeCodeAdapter


@pytest.fixture
def adapter():
    return ClaudeCodeAdapter()


def _write_session(path: Path, messages: list[dict]) -> Path:
    """Write a minimal Claude Code session JSONL."""
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return path


def _make_user_msg(text: str, ts: str = "2026-04-10T10:00:00Z") -> dict:
    return {
        "type": "user",
        "sessionId": "test-session",
        "timestamp": ts,
        "message": {"role": "user", "content": text},
    }


def _make_assistant_msg(content: list[dict], ts: str = "2026-04-10T10:00:01Z") -> dict:
    return {
        "type": "assistant",
        "sessionId": "test-session",
        "timestamp": ts,
        "message": {"role": "assistant", "content": content},
    }


class TestDetect:
    def test_detects_jsonl_file(self, adapter, tmp_path):
        f = _write_session(tmp_path / "session.jsonl", [_make_user_msg("hello")])
        assert adapter.detect(f) is True

    def test_detects_dir_with_jsonl(self, adapter, tmp_path):
        _write_session(tmp_path / "abc.jsonl", [_make_user_msg("hello")])
        assert adapter.detect(tmp_path) is True

    def test_rejects_non_claude_jsonl(self, adapter, tmp_path):
        f = tmp_path / "other.jsonl"
        f.write_text('{"type": "log", "data": 123}\n')
        assert adapter.detect(f) is False

    def test_rejects_empty_dir(self, adapter, tmp_path):
        assert adapter.detect(tmp_path) is False

    def test_rejects_non_jsonl(self, adapter, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"type": "user", "sessionId": "x"}')
        assert adapter.detect(f) is False


class TestLoad:
    def test_basic_fields(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_user_msg("fix the login bug", "2026-04-10T10:00:00Z"),
                _make_assistant_msg(
                    [{"type": "text", "text": "I'll look into it"}], "2026-04-10T10:00:01Z"
                ),
            ],
        )
        trace = adapter.load(f)
        assert trace.framework == "claude-code"
        assert trace.session_type == "conversation"
        assert trace.status == "completed"
        assert "login bug" in trace.title

    def test_user_message_events(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_user_msg("do the thing"),
            ],
        )
        trace = adapter.load(f)
        user_events = [e for e in trace.events if e.name == "user_message"]
        assert len(user_events) == 1
        assert "do the thing" in user_events[0].data["text"]

    def test_reasoning_events(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [{"type": "thinking", "thinking": "I should read the file first"}]
                ),
                _make_assistant_msg([{"type": "text", "text": "Let me check the code"}]),
            ],
        )
        trace = adapter.load(f)
        reasoning = [e for e in trace.events if e.type == "reasoning"]
        assert len(reasoning) == 2
        names = {e.name for e in reasoning}
        assert "agent_thinking" in names
        assert "agent_response" in names

    def test_tool_call_events(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"file_path": "/src/main.ts"},
                        },
                    ]
                ),
                _make_assistant_msg(
                    [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}},
                    ]
                ),
                _make_assistant_msg(
                    [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": "/src/main.ts"},
                        },
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        tool_events = [e for e in trace.events if e.type == "tool"]
        assert len(tool_events) == 3
        assert tool_events[0].data["tool"] == "Read"
        assert tool_events[1].data["tool"] == "Bash"
        assert tool_events[2].data["tool"] == "Edit"

    def test_tool_calls_in_span(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "/src/a.ts"}},
                        {"type": "tool_use", "name": "Write", "input": {"file_path": "/src/b.ts"}},
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert len(trace.spans) == 1
        assert len(trace.spans[0].tool_calls) == 2
        assert trace.spans[0].tool_calls[0].kind == "file_read"
        assert trace.spans[0].tool_calls[1].kind == "file_write"

    def test_timestamps(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_user_msg("start", "2026-04-10T10:00:00Z"),
                _make_assistant_msg([{"type": "text", "text": "done"}], "2026-04-10T10:30:00Z"),
            ],
        )
        trace = adapter.load(f)
        assert trace.started_at == "2026-04-10T10:00:00Z"
        assert trace.ended_at == "2026-04-10T10:30:00Z"

    def test_summary_computed(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "/a"}},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert trace.summary.files_read == 1
        assert trace.summary.commands_run == 1

    def test_custom_title(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                {"type": "custom-title", "title": "My cool session"},
                _make_user_msg("do stuff"),
            ],
        )
        trace = adapter.load(f)
        assert trace.title == "My cool session"

    def test_redacts_secrets(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_user_msg("my key is sk-ant-api03-FAKEFAKEFAKEFAKEFAKE"),
                _make_assistant_msg([{"type": "text", "text": "Found password=Secret123!"}]),
            ],
        )
        trace = adapter.load(f)
        for event in trace.events:
            text = event.data.get("text", "")
            assert "sk-ant-api03" not in text
            assert "Secret123" not in text

    def test_empty_session(self, adapter, tmp_path):
        f = _write_session(tmp_path / "s.jsonl", [])
        trace = adapter.load(f)
        assert len(trace.events) == 0
        assert len(trace.spans) == 0

    def test_skips_non_assistant_non_user(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                {"type": "progress", "timestamp": "2026-04-10T10:00:00Z"},
                {"type": "system", "timestamp": "2026-04-10T10:00:01Z"},
                _make_user_msg("hello", "2026-04-10T10:00:02Z"),
            ],
        )
        trace = adapter.load(f)
        assert len(trace.events) == 1


class TestEdgeCases:
    def test_non_list_assistant_content(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg("just a string"),
            ],
        )
        trace = adapter.load(f)
        assert len(trace.events) == 0

    def test_blank_lines_skipped(self, adapter, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            json.dumps(_make_user_msg("hello"))
            + "\n\n\n"
            + json.dumps(_make_user_msg("world"))
            + "\n"
        )
        trace = adapter.load(f)
        user_events = [e for e in trace.events if e.name == "user_message"]
        assert len(user_events) == 2

    def test_corrupt_lines_skipped(self, adapter, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            json.dumps(_make_user_msg("hello"))
            + "\nnot json\n"
            + json.dumps(_make_user_msg("world"))
            + "\n"
        )
        trace = adapter.load(f)
        user_events = [e for e in trace.events if e.name == "user_message"]
        assert len(user_events) == 2

    def test_glob_target(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {"type": "tool_use", "name": "Glob", "input": {"pattern": "src/**/*.ts"}},
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert "src/**/*.ts" in trace.spans[0].tool_calls[0].target

    def test_webfetch_target(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {
                            "type": "tool_use",
                            "name": "WebFetch",
                            "input": {"url": "https://example.com"},
                        },
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert "example.com" in trace.spans[0].tool_calls[0].target

    def test_unknown_tool_target(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {"type": "tool_use", "name": "UnknownTool", "input": {"foo": "bar"}},
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert len(trace.spans[0].tool_calls) == 1

    def test_find_log_in_directory(self, adapter, tmp_path):
        _write_session(tmp_path / "session.jsonl", [_make_user_msg("hello")])
        assert adapter.detect(tmp_path) is True
        trace = adapter.load(tmp_path)
        assert trace.framework == "claude-code"

    def test_find_log_no_match_raises(self, adapter, tmp_path):
        (tmp_path / "not-claude.jsonl").write_text('{"type": "log"}\n')
        with pytest.raises(ValueError, match="No Claude Code log found"):
            adapter.load(tmp_path)

    def test_detect_many_lines_stops_early(self, adapter, tmp_path):
        """Detection only checks first 6 lines — a valid session marker at line 7 is missed."""
        lines = ['{"type": "log", "data": 1}\n'] * 7 + [json.dumps(_make_user_msg("hi")) + "\n"]
        f = tmp_path / "late.jsonl"
        f.write_text("".join(lines))
        assert adapter.detect(f) is False

    def test_detect_corrupt_file(self, adapter, tmp_path):
        """Corrupt JSONL should not crash detection."""
        f = tmp_path / "bad.jsonl"
        f.write_text("{{{{not json\n")
        assert adapter.detect(f) is False


class TestToolTargetExtraction:
    def test_read_target(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"file_path": "/src/app.tsx"},
                        },
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert "/src/app.tsx" in trace.spans[0].tool_calls[0].target

    def test_bash_target_truncated(self, adapter, tmp_path):
        long_cmd = "x" * 300
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {"type": "tool_use", "name": "Bash", "input": {"command": long_cmd}},
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert len(trace.spans[0].tool_calls[0].target) <= 200

    def test_grep_target(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {"type": "tool_use", "name": "Grep", "input": {"pattern": "TODO"}},
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert "TODO" in trace.spans[0].tool_calls[0].target

    def test_agent_target(self, adapter, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                _make_assistant_msg(
                    [
                        {
                            "type": "tool_use",
                            "name": "Agent",
                            "input": {"description": "Search codebase"},
                        },
                    ]
                ),
            ],
        )
        trace = adapter.load(f)
        assert "Search codebase" in trace.spans[0].tool_calls[0].target


class TestAutoDetect:
    def test_auto_detects_claude_code(self, tmp_path):
        from ard.adapters.base import detect_adapter

        _write_session(tmp_path / "session.jsonl", [_make_user_msg("hello")])
        adapter = detect_adapter(tmp_path / "session.jsonl")
        assert adapter is not None
        trace = adapter.load(tmp_path / "session.jsonl")
        assert trace.framework == "claude-code"

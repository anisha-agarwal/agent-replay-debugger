"""Tests for the CLI — uses direct function calls for coverage."""

import json
import os
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from ard.cli import cmd_list, cmd_pick, cmd_trace, cmd_view, main

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestCmdTrace:
    def test_executor_json(self, capsys):
        args = Namespace(session_dir=str(FIXTURES_DIR / "executor_session"), pretty=False)
        assert cmd_trace(args) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["framework"] == "forge"
        assert data["session_type"] == "executor"
        assert len(data["spans"]) == 3

    def test_planner_json(self, capsys):
        args = Namespace(session_dir=str(FIXTURES_DIR / "planner_session"), pretty=False)
        assert cmd_trace(args) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["framework"] == "forge"
        assert data["session_type"] == "planner"

    def test_generic_json(self, capsys):
        args = Namespace(session_dir=str(FIXTURES_DIR / "generic_session"), pretty=False)
        assert cmd_trace(args) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["framework"] == "custom-agent"

    def test_pretty_flag(self, capsys):
        args = Namespace(session_dir=str(FIXTURES_DIR / "executor_session"), pretty=True)
        assert cmd_trace(args) == 0
        output = capsys.readouterr().out
        assert "\n" in output
        assert "  " in output

    def test_nonexistent_dir(self, capsys):
        args = Namespace(session_dir="/nonexistent/path", pretty=False)
        assert cmd_trace(args) == 1
        assert "does not exist" in capsys.readouterr().err

    def test_no_adapter(self, capsys, tmp_path):
        args = Namespace(session_dir=str(tmp_path), pretty=False)
        assert cmd_trace(args) == 1
        assert "no adapter" in capsys.readouterr().err


class TestCmdView:
    def test_output_file(self, capsys, tmp_path):
        output = tmp_path / "test.html"
        args = Namespace(session_dir=str(FIXTURES_DIR / "executor_session"), output=str(output))
        assert cmd_view(args) == 0
        html = output.read_text()
        assert "Agent Replay Debugger" in html
        assert '"framework": "forge"' in html
        assert "Written to" in capsys.readouterr().out

    def test_opens_browser(self, capsys):
        args = Namespace(session_dir=str(FIXTURES_DIR / "executor_session"), output=None)
        with patch("ard.cli.webbrowser.open") as mock_open:
            assert cmd_view(args) == 0
            mock_open.assert_called_once()
            call_arg = mock_open.call_args[0][0]
            assert call_arg.startswith("file://")
            assert call_arg.endswith(".html")
        assert "Opening" in capsys.readouterr().out

    def test_nonexistent_dir(self, capsys):
        args = Namespace(session_dir="/nonexistent/path", output=None)
        assert cmd_view(args) == 1
        assert "does not exist" in capsys.readouterr().err

    def test_no_adapter(self, capsys, tmp_path):
        args = Namespace(session_dir=str(tmp_path), output=None)
        assert cmd_view(args) == 1
        assert "no adapter" in capsys.readouterr().err


class TestCmdList:
    def test_with_sessions(self, capsys, tmp_path):
        # Create fake executor session
        executor_dir = tmp_path / "executor" / "my-session"
        executor_dir.mkdir(parents=True)
        (executor_dir / "agent-state.json").write_text(
            json.dumps(
                {
                    "steps": {"code": {"status": "complete"}},
                    "created_at": "2026-04-10T10:00:00Z",
                }
            )
        )
        # Create fake planner session
        planner_dir = tmp_path / "planner" / "plan-session"
        planner_dir.mkdir(parents=True)
        (planner_dir / ".planner-state.json").write_text(
            json.dumps(
                {
                    "phases": {"recon": {"status": "failed"}},
                    "created_at": "2026-04-10T09:00:00Z",
                }
            )
        )

        args = Namespace()
        with patch.dict(os.environ, {"FORGE_SESSIONS": str(tmp_path)}):
            assert cmd_list(args) == 0
        output = capsys.readouterr().out
        assert "my-session" in output
        assert "plan-session" in output
        assert "completed" in output
        assert "failed" in output

    def test_killed_session(self, capsys, tmp_path):
        executor_dir = tmp_path / "executor" / "killed-session"
        executor_dir.mkdir(parents=True)
        (executor_dir / "agent-state.json").write_text(
            json.dumps(
                {
                    "steps": {"code": {"status": "in_progress"}},
                    "killed": True,
                    "created_at": "2026-04-10T10:00:00Z",
                }
            )
        )
        args = Namespace()
        with patch.dict(os.environ, {"FORGE_SESSIONS": str(tmp_path)}):
            assert cmd_list(args) == 0
        assert "killed" in capsys.readouterr().out

    def test_running_session(self, capsys, tmp_path):
        executor_dir = tmp_path / "executor" / "running-session"
        executor_dir.mkdir(parents=True)
        (executor_dir / "agent-state.json").write_text(
            json.dumps(
                {
                    "steps": {"code": {"status": "in_progress"}},
                    "created_at": "2026-04-10T10:00:00Z",
                }
            )
        )
        args = Namespace()
        with patch.dict(os.environ, {"FORGE_SESSIONS": str(tmp_path)}):
            assert cmd_list(args) == 0
        assert "running" in capsys.readouterr().out

    def test_empty_sessions(self, capsys, tmp_path):
        (tmp_path / "executor").mkdir()
        (tmp_path / "planner").mkdir()
        args = Namespace()
        with patch.dict(os.environ, {"FORGE_SESSIONS": str(tmp_path)}):
            assert cmd_list(args) == 0
        assert "No sessions found" in capsys.readouterr().out

    def test_no_sessions_dir(self, capsys):
        args = Namespace()
        with patch.dict(os.environ, {"FORGE_SESSIONS": "/nonexistent/path"}):
            assert cmd_list(args) == 1
        assert "No sessions directory" in capsys.readouterr().err

    def test_corrupt_state_file(self, capsys, tmp_path):
        executor_dir = tmp_path / "executor" / "corrupt-session"
        executor_dir.mkdir(parents=True)
        (executor_dir / "agent-state.json").write_text("not json")
        args = Namespace()
        with patch.dict(os.environ, {"FORGE_SESSIONS": str(tmp_path)}):
            assert cmd_list(args) == 0
        output = capsys.readouterr().out
        assert "corrupt-session" in output
        assert "unknown" in output

    def test_skips_non_dir_entries(self, capsys, tmp_path):
        executor_dir = tmp_path / "executor"
        executor_dir.mkdir(parents=True)
        (executor_dir / "random-file.txt").write_text("not a session")
        args = Namespace()
        with patch.dict(os.environ, {"FORGE_SESSIONS": str(tmp_path)}):
            assert cmd_list(args) == 0
        assert "No sessions found" in capsys.readouterr().out


class TestCmdPick:
    def _make_project(self, tmp_path, name, sessions):
        """Create a fake Claude projects dir with JSONL sessions."""
        project_dir = tmp_path / f"-Users-dev-{name}"
        project_dir.mkdir(parents=True)
        for i, (content, size_pad) in enumerate(sessions):
            f = project_dir / f"session-{i}.jsonl"
            f.write_text(content + "x" * size_pad)
        return tmp_path

    def test_pick_latest(self, capsys, tmp_path):
        base = self._make_project(
            tmp_path,
            "myproject",
            [
                ('{"type":"user","sessionId":"s1"}\n', 200),
                ('{"type":"user","sessionId":"s2"}\n', 200),
            ],
        )
        args = Namespace(project="myproject", list=False, n=1)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", base):
            assert cmd_pick(args) == 0
        output = capsys.readouterr().out.strip()
        assert output.endswith(".jsonl")

    def test_pick_nth(self, capsys, tmp_path):
        base = self._make_project(
            tmp_path,
            "myproject",
            [
                ('{"type":"user","sessionId":"s1"}\n', 200),
                ('{"type":"user","sessionId":"s2"}\n', 200),
            ],
        )
        args = Namespace(project="myproject", list=False, n=2)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", base):
            assert cmd_pick(args) == 0

    def test_pick_list(self, capsys, tmp_path):
        base = self._make_project(
            tmp_path,
            "myproject",
            [
                ('{"type":"user","sessionId":"s1"}\n', 200),
            ],
        )
        args = Namespace(project="myproject", list=True, n=1)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", base):
            assert cmd_pick(args) == 0
        output = capsys.readouterr().out
        assert "session-0" in output

    def test_pick_not_found(self, capsys, tmp_path):
        self._make_project(
            tmp_path,
            "other",
            [
                ('{"type":"user","sessionId":"s1"}\n', 200),
            ],
        )
        args = Namespace(project="nonexistent", list=False, n=1)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", tmp_path):
            assert cmd_pick(args) == 1
        err = capsys.readouterr().err
        assert "not found" in err
        assert "Available" in err

    def test_pick_no_sessions(self, capsys, tmp_path):
        project_dir = tmp_path / "-Users-dev-emptyproject"
        project_dir.mkdir(parents=True)
        args = Namespace(project="emptyproject", list=False, n=1)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", tmp_path):
            assert cmd_pick(args) == 1
        assert "No sessions found" in capsys.readouterr().err

    def test_pick_direct_path(self, capsys, tmp_path):
        (tmp_path / "session.jsonl").write_text('{"type":"user","sessionId":"s"}\n' + "x" * 200)
        args = Namespace(project=str(tmp_path), list=False, n=1)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", Path("/nonexistent")):
            assert cmd_pick(args) == 0
        output = capsys.readouterr().out.strip()
        assert output.endswith(".jsonl")

    def test_pick_no_claude_dir(self, capsys):
        args = Namespace(project="something", list=False, n=1)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", Path("/nonexistent")):
            assert cmd_pick(args) == 1

    def test_pick_skips_non_dir_entries(self, capsys, tmp_path):
        (tmp_path / "random-file.txt").write_text("not a dir")
        self._make_project(
            tmp_path,
            "myproject",
            [
                ('{"type":"user","sessionId":"s1"}\n', 200),
            ],
        )
        args = Namespace(project="myproject", list=False, n=1)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", tmp_path):
            assert cmd_pick(args) == 0

    def test_pick_multiple_matches_prefers_longest(self, capsys, tmp_path):
        # Create two dirs that both match "champions"
        (tmp_path / "-Users-dev-champions").mkdir()
        (tmp_path / "-Users-dev-champions" / "s.jsonl").write_text(
            '{"type":"user","sessionId":"1"}\n' + "x" * 200
        )
        (tmp_path / "-Users-dev-chore-champions").mkdir()
        (tmp_path / "-Users-dev-chore-champions" / "s.jsonl").write_text(
            '{"type":"user","sessionId":"2"}\n' + "x" * 200
        )
        args = Namespace(project="champions", list=False, n=1)
        with patch("ard.cli.CLAUDE_PROJECTS_DIR", tmp_path):
            assert cmd_pick(args) == 0


class TestMain:
    def test_no_args(self):
        with patch("sys.argv", ["ard"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_trace_command(self, capsys):
        with patch("sys.argv", ["ard", "trace", str(FIXTURES_DIR / "executor_session")]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_view_command(self, tmp_path):
        output = tmp_path / "out.html"
        with patch(
            "sys.argv", ["ard", "view", str(FIXTURES_DIR / "executor_session"), "-o", str(output)]
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
            assert output.exists()

    def test_list_command(self, capsys):
        with patch("sys.argv", ["ard", "list"]):
            with patch.dict(os.environ, {"FORGE_SESSIONS": "/nonexistent"}):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    def test_pick_command(self):
        with patch("sys.argv", ["ard", "pick", "nonexistent"]):
            with patch("ard.cli.CLAUDE_PROJECTS_DIR", Path("/nonexistent")):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

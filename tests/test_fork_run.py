"""Tests for full re-execution fork."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ard.fork_run import _get_session_id, _find_project_dir, _find_newest_jsonl, fork_and_run


def _write_session(path, messages):
    with open(path, "w") as f:
        for m in messages:
            f.write(json.dumps(m) + "\n")
    return path


class TestGetSessionId:
    def test_finds_id(self, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "abc-123",
                    "message": {"role": "user", "content": "hi"},
                },
            ],
        )
        assert _get_session_id(f) == "abc-123"

    def test_skips_lines_without_id(self, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                {"type": "progress", "data": "stuff"},
                {
                    "type": "user",
                    "sessionId": "found-it",
                    "message": {"role": "user", "content": "hi"},
                },
            ],
        )
        assert _get_session_id(f) == "found-it"

    def test_raises_if_no_id(self, tmp_path):
        f = _write_session(
            tmp_path / "s.jsonl",
            [
                {"type": "progress", "data": "stuff"},
            ],
        )
        with pytest.raises(ValueError, match="No sessionId"):
            _get_session_id(f)

    def test_handles_corrupt_lines(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text("not json\n" + json.dumps({"type": "user", "sessionId": "ok"}) + "\n")
        assert _get_session_id(f) == "ok"

    def test_handles_blank_lines(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text("\n\n" + json.dumps({"type": "user", "sessionId": "ok"}) + "\n")
        assert _get_session_id(f) == "ok"


class TestFindProjectDir:
    def test_returns_parent(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text("")
        assert _find_project_dir(f) == tmp_path


class TestFindNewestJsonl:
    def test_finds_newest(self, tmp_path):
        import time

        old = tmp_path / "old.jsonl"
        old.write_text("old")
        time.sleep(0.05)
        before = time.time()
        time.sleep(0.05)
        new = tmp_path / "new.jsonl"
        new.write_text("new")
        result = _find_newest_jsonl(tmp_path, before)
        assert result == new

    def test_returns_none_if_nothing_newer(self, tmp_path):
        import time

        old = tmp_path / "old.jsonl"
        old.write_text("old")
        result = _find_newest_jsonl(tmp_path, time.time() + 100)
        assert result is None


class TestForkAndRun:
    def test_successful_fork(self, tmp_path):
        session = _write_session(
            tmp_path / "original.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "test-id",
                    "message": {"role": "user", "content": "hi"},
                },
            ],
        )

        # Mock subprocess to simulate claude running
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Agent says hello"
        mock_result.stderr = ""

        def fake_run(*args, **kwargs):
            # Simulate claude creating a new session file
            forked = tmp_path / "forked.jsonl"
            forked.write_text('{"type":"user","sessionId":"forked-id"}\n')
            return mock_result

        with patch("ard.fork_run.subprocess.run", side_effect=fake_run):
            result = fork_and_run(session, new_prompt="try differently", cwd=str(tmp_path))

        assert result["original_session"] == str(session)
        assert "forked.jsonl" in result["forked_session"]
        assert result["session_id"] == "test-id"

    def test_claude_failure(self, tmp_path):
        session = _write_session(
            tmp_path / "s.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "test-id",
                    "message": {"role": "user", "content": "hi"},
                },
            ],
        )
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "something went wrong"

        with patch("ard.fork_run.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="something went wrong"):
                fork_and_run(session, new_prompt="test")

    def test_no_forked_session_found(self, tmp_path):
        session = _write_session(
            tmp_path / "s.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "test-id",
                    "message": {"role": "user", "content": "hi"},
                },
            ],
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "done"
        mock_result.stderr = ""

        with patch("ard.fork_run.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Could not find"):
                fork_and_run(session, new_prompt="test")

    def test_budget_passed(self, tmp_path):
        session = _write_session(
            tmp_path / "s.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "test-id",
                    "message": {"role": "user", "content": "hi"},
                },
            ],
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""

        called_with = {}

        def capture_run(cmd, **kwargs):
            called_with["cmd"] = cmd
            forked = tmp_path / "forked.jsonl"
            forked.write_text('{"type":"user"}\n')
            return mock_result

        with patch("ard.fork_run.subprocess.run", side_effect=capture_run):
            fork_and_run(session, new_prompt="test", max_budget=2.50)

        assert "--max-budget-usd" in called_with["cmd"]
        assert "2.5" in called_with["cmd"]

    def test_long_output_truncated(self, tmp_path, capsys):
        session = _write_session(
            tmp_path / "s.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "test-id",
                    "message": {"role": "user", "content": "hi"},
                },
            ],
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "x" * 3000
        mock_result.stderr = ""

        def fake_run(*args, **kwargs):
            forked = tmp_path / "forked.jsonl"
            forked.write_text('{"type":"user"}\n')
            return mock_result

        with patch("ard.fork_run.subprocess.run", side_effect=fake_run):
            fork_and_run(session, new_prompt="test")

        output = capsys.readouterr().out
        assert "3000 chars total" in output

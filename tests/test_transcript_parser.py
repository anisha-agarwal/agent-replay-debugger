"""Tests for the forge transcript parser."""

from ard.adapters.forge import _parse_transcript


class TestParseTranscript:
    def test_reasoning_blocks(self, tmp_path):
        log = tmp_path / "code-transcript.log"
        log.write_text(
            "I'll start by reading the router file.\n"
            "[Read] /src/router.ts\n"
            "     1→import express from 'express';\n"
            "Now I'll fix the handler.\n"
        )
        entries = _parse_transcript(log)
        reasoning = [e for e in entries if e["type"] == "reasoning"]
        assert len(reasoning) == 2
        assert "router file" in reasoning[0]["text"]
        assert "fix the handler" in reasoning[1]["text"]

    def test_tool_calls(self, tmp_path):
        log = tmp_path / "code-transcript.log"
        log.write_text(
            "[Read] /src/main.ts\n"
            "[Write] /src/output.ts\n"
            "[Edit] /src/config.ts\n"
            "[Bash] npm test\n"
            "[Grep] TODO\n"
            "[Glob] src/**/*.ts\n"
        )
        entries = _parse_transcript(log)
        tools = [e for e in entries if e["type"] == "tool_call"]
        assert len(tools) == 6
        kinds = [t["kind"] for t in tools]
        assert kinds == [
            "file_read",
            "file_write",
            "file_write",
            "command",
            "file_read",
            "file_read",
        ]

    def test_skips_file_content_lines(self, tmp_path):
        log = tmp_path / "transcript.log"
        log.write_text(
            "Let me read the file.\n"
            "[Read] /src/app.ts\n"
            "     1→const x = 1;\n"
            "     2→const y = 2;\n"
            "     3→export default x + y;\n"
            "Now I understand the structure.\n"
        )
        entries = _parse_transcript(log)
        reasoning = [e for e in entries if e["type"] == "reasoning"]
        assert len(reasoning) == 2
        assert all("const x" not in r["text"] for r in reasoning)

    def test_skips_tool_result_messages(self, tmp_path):
        log = tmp_path / "transcript.log"
        log.write_text(
            "[Write] /src/new.ts\n"
            "File created successfully at: /src/new.ts\n"
            "[Edit] /src/old.ts\n"
            "The file /src/old.ts has been updated successfully.\n"
            "Good, both files updated.\n"
        )
        entries = _parse_transcript(log)
        reasoning = [e for e in entries if e["type"] == "reasoning"]
        assert len(reasoning) == 1
        assert "both files" in reasoning[0]["text"]

    def test_missing_file(self, tmp_path):
        entries = _parse_transcript(tmp_path / "nonexistent.log")
        assert entries == []

    def test_empty_file(self, tmp_path):
        log = tmp_path / "empty.log"
        log.write_text("")
        entries = _parse_transcript(log)
        assert entries == []

    def test_redacts_secrets_in_reasoning(self, tmp_path):
        log = tmp_path / "transcript.log"
        log.write_text("The API key is sk-ant-api03-FAKEFAKEFAKEFAKEFAKE\n")
        entries = _parse_transcript(log)
        assert len(entries) == 1
        assert "sk-ant" not in entries[0]["text"]
        assert "[REDACTED]" in entries[0]["text"]

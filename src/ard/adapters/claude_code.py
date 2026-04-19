"""Claude Code session adapter — reads Claude Code JSONL conversation logs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ard.adapters.forge import _redact
from ard.schema import Event, Span, ToolCall, Trace

# Map Claude Code tool names to ToolCall kinds
TOOL_KIND_MAP: dict[str, str] = {
    "Read": "file_read",
    "Glob": "file_read",
    "Grep": "file_read",
    "Write": "file_write",
    "Edit": "file_write",
    "NotebookEdit": "file_write",
    "Bash": "command",
    "Agent": "command",
    "WebFetch": "command",
    "WebSearch": "command",
    "ToolSearch": "command",
    "EnterPlanMode": "command",
    "ExitPlanMode": "command",
    "Skill": "command",
}


def _extract_tool_target(name: str, tool_input: dict[str, Any]) -> str:
    """Extract the most relevant target string from a tool call's input."""
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        return tool_input.get("file_path", "")
    if name == "Bash":
        cmd = tool_input.get("command", "")
        return cmd[:200] if len(cmd) > 200 else cmd
    if name in ("Glob",):
        return tool_input.get("pattern", "")
    if name == "Grep":
        return tool_input.get("pattern", "")
    if name == "Agent":
        return tool_input.get("description", tool_input.get("prompt", ""))[:150]
    if name == "WebFetch":
        return tool_input.get("url", "")
    return str(tool_input)[:150]


def _make_span_id(index: int, text: str) -> str:
    """Generate a short span ID from user message."""
    clean = _redact(text)
    words = clean.split()[:6]
    slug = "-".join(w.lower().strip(".,!?\"'()") for w in words if w.strip(".,!?\"'()"))
    slug = slug[:40] if slug else "task"
    return f"{index}-{slug}"


class ClaudeCodeAdapter:
    """Adapter for Claude Code JSONL session logs."""

    def detect(self, session_dir: Path) -> bool:
        """Detect if this is a Claude Code session log (a .jsonl file)."""
        if session_dir.is_file() and session_dir.suffix == ".jsonl":
            return self._is_claude_code_log(session_dir)
        if session_dir.is_dir():
            for f in session_dir.iterdir():
                if f.suffix == ".jsonl" and self._is_claude_code_log(f):
                    return True
        return False

    def _is_claude_code_log(self, path: Path) -> bool:
        """Check if a JSONL file looks like a Claude Code session."""
        try:
            with open(path) as f:
                for i, line in enumerate(f):
                    if i > 5:
                        break
                    d = json.loads(line)
                    if d.get("type") in ("user", "assistant") and "sessionId" in d:
                        return True
        except (json.JSONDecodeError, OSError):
            pass
        return False

    def _find_log(self, session_dir: Path) -> Path:
        """Find the JSONL log file."""
        if session_dir.is_file():
            return session_dir
        for f in sorted(session_dir.iterdir(), key=lambda p: p.stat().st_size, reverse=True):
            if f.suffix == ".jsonl" and self._is_claude_code_log(f):
                return f
        raise ValueError(f"No Claude Code log found in {session_dir}")

    def load(self, session_dir: Path) -> Trace:
        """Load a Claude Code session into a universal Trace."""
        log_path = self._find_log(session_dir)

        messages: list[dict[str, Any]] = []
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        events: list[Event] = []
        session_id = ""
        title = ""
        first_ts = ""
        last_ts = ""

        # Track spans: each user message starts a new span
        span_groups: list[dict[str, Any]] = []
        current_group: dict[str, Any] | None = None

        def _new_group(text: str, ts: str) -> dict[str, Any]:
            idx = len(span_groups)
            return {
                "span_id": _make_span_id(idx, text),
                "title": _redact(text[:80]),
                "started_at": ts,
                "ended_at": ts,
                "tool_calls": [],
                "reasoning": [],
            }

        for msg in messages:
            msg_type = msg.get("type", "")
            ts = msg.get("timestamp", "")

            if not first_ts and ts:
                first_ts = ts
            if ts:
                last_ts = ts

            if not session_id:
                session_id = msg.get("sessionId", "")

            if msg_type == "custom-title":
                title = msg.get("title", "")

            if msg_type == "user":
                content = msg.get("message", {}).get("content", "")
                if isinstance(content, str) and content.strip():
                    text = content.strip()[:300]

                    # Finalize previous group and start new one
                    if current_group:
                        span_groups.append(current_group)
                    current_group = _new_group(text, ts)

                    events.append(
                        Event(
                            timestamp=ts,
                            type="reasoning",
                            name="user_message",
                            span_id=current_group["span_id"],
                            data={"text": _redact(text)},
                        )
                    )
                    if not title and len(text) > 5:
                        title = text[:80]

            elif msg_type == "assistant":
                content = msg.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue

                # Ensure we have a group (assistant before any user message)
                if not current_group:
                    current_group = _new_group("initial", ts)

                for block in content:
                    block_type = block.get("type", "")
                    span_id = current_group["span_id"]

                    if block_type == "thinking":
                        text = (block.get("thinking", "") or "")[:500]
                        if text.strip():
                            current_group["reasoning"].append(text)
                            events.append(
                                Event(
                                    timestamp=ts,
                                    type="reasoning",
                                    name="agent_thinking",
                                    span_id=span_id,
                                    data={"text": _redact(text)},
                                )
                            )

                    elif block_type == "text":
                        text = (block.get("text", "") or "")[:500]
                        if text.strip():
                            events.append(
                                Event(
                                    timestamp=ts,
                                    type="reasoning",
                                    name="agent_response",
                                    span_id=span_id,
                                    data={"text": _redact(text)},
                                )
                            )

                    elif block_type == "tool_use":
                        tool_name = block.get("name", "")
                        tool_input = block.get("input", {})
                        kind = TOOL_KIND_MAP.get(tool_name, "command")
                        target = _extract_tool_target(tool_name, tool_input)

                        tc = ToolCall(
                            kind=kind,
                            target=_redact(target),
                            timestamp=ts,
                        )
                        current_group["tool_calls"].append(tc)
                        events.append(
                            Event(
                                timestamp=ts,
                                type="tool",
                                name=f"tool_{tool_name}",
                                span_id=span_id,
                                data={
                                    "tool": tool_name,
                                    "target": _redact(target),
                                },
                            )
                        )

                    if ts:
                        current_group["ended_at"] = ts

        # Finalize last group
        if current_group:
            span_groups.append(current_group)

        # Build spans from groups
        spans: list[Span] = []
        for g in span_groups:
            spans.append(
                Span(
                    span_id=g["span_id"],
                    name=g["title"],
                    kind="agent",
                    status="passed" if g["tool_calls"] or g["reasoning"] else "pending",
                    started_at=g["started_at"],
                    ended_at=g["ended_at"],
                    tool_calls=g["tool_calls"],
                    metadata={
                        "reasoning": [_redact(r) for r in g["reasoning"][:50]],
                    }
                    if g["reasoning"]
                    else {},
                )
            )

        # Build linear dependency chain
        dep_graph: dict[str, list[str]] = {}
        for i, span in enumerate(spans):
            dep_graph[span.span_id] = [spans[i - 1].span_id] if i > 0 else []

        trace = Trace(
            trace_id=session_id or log_path.stem,
            framework="claude-code",
            session_type="conversation",
            title=_redact(title) if title else log_path.stem,
            status="completed",
            started_at=first_ts,
            ended_at=last_ts,
            metadata={"session_id": session_id},
            spans=spans,
            events=events,
            artifacts=[],
            dependency_graph=dep_graph if len(spans) > 1 else None,
        )
        trace.compute_summary()
        return trace

"""Forge framework adapter — reads forge session directories into universal traces."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ard.schema import Artifact, Event, Span, ToolCall, Trace

# Patterns that look like secrets — redact these from all output
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-api\S+"),  # Anthropic API keys
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),  # OpenAI-style keys
    re.compile(r"sbp_[a-f0-9]{20,}"),  # Supabase tokens
    re.compile(r"ghp_\w{20,}"),  # GitHub PATs
    re.compile(r"gho_\w{20,}"),  # GitHub OAuth tokens
    re.compile(r"xoxb-\S+"),  # Slack bot tokens
    re.compile(r"xoxp-\S+"),  # Slack user tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),  # JWTs
    re.compile(
        r"(?i)(password|secret|api[_-]?key|access[_-]?token|service[_-]?role[_-]?key)"
        r"\s*[=:]\s*\S+"
    ),  # key=value secrets
]

# PII patterns — replaced with placeholders rather than [REDACTED] for readability
_PII_REPLACEMENTS = [
    # Email addresses → [email]
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    # Phone numbers (US-ish) → [phone]
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[phone]"),
    # IPv4 → [ip]
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    # macOS user paths → /Users/dev
    (re.compile(r"/Users/[a-zA-Z0-9._-]+"), "/Users/dev"),
    # Linux user paths → /home/dev
    (re.compile(r"/home/[a-zA-Z0-9._-]+"), "/home/dev"),
    # UUIDs → [uuid]
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "[uuid]"),
    # GitHub URLs with usernames → github.com/user/repo
    (re.compile(r"github\.com/[a-zA-Z0-9_-]+/"), "github.com/user/"),
    # .claude project paths containing usernames
    (re.compile(r"\.claude/projects/-[A-Za-z]+-[a-zA-Z0-9._-]+-"), ".claude/projects/-dev-"),
    # Claude project slugs like "anisha-chore-champions"
    (re.compile(r"(?<=/|-)[a-z]{3,15}(?=-[a-z]+-[a-z]+/)"), "dev"),
]


def _redact(text: str) -> str:
    """Redact secrets and PII from text."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    for pattern, replacement in _PII_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


# Forge event type → universal event type
EVENT_TYPE_MAP: dict[str, str] = {
    "pipeline_started": "lifecycle",
    "pipeline_completed": "lifecycle",
    "pipeline_failed": "lifecycle",
    "pipeline_killed": "lifecycle",
    "planner_started": "lifecycle",
    "planner_completed": "lifecycle",
    "planner_failed": "lifecycle",
    "planner_killed": "lifecycle",
    "step_started": "step",
    "step_passed": "step",
    "step_failed": "error",
    "step_reset": "step",
    "step_skipped": "step",
    "phase_started": "phase",
    "phase_completed": "phase",
    "phase_failed": "error",
    "judge_verdict": "verdict",
}

# Planner phases in execution order
PLANNER_PHASES = ["recon", "architects", "critics", "refiners", "judge", "enrichment"]

# Known planner output documents per phase
PLANNER_OUTPUTS: dict[str, list[str]] = {
    "recon": ["codebase-brief.md"],
    "architects": ["design-a.md", "design-b.md"],
    "critics": ["critique-a.md", "critique-b.md"],
    "refiners": ["refined-a.md", "refined-b.md"],
    "judge": ["final-plan.md"],
}

# Activity log line pattern: [HH:MM:SS] step_name  action: detail
ACTIVITY_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s+(\S+)\s{2,}(\w+):\s+(.+)$")

# Map activity log action keywords to ToolCall kinds
ACTION_KIND_MAP: dict[str, str] = {
    "read": "file_read",
    "write": "file_write",
    "bash": "command",
    "error": "command",
}

# Transcript tool call pattern: [Read], [Write], [Edit], [Bash], etc.
TRANSCRIPT_TOOL_RE = re.compile(r"^\[(\w+)\]\s*(.*)")

# Map transcript tool names to ToolCall kinds
TRANSCRIPT_TOOL_MAP: dict[str, str] = {
    "Read": "file_read",
    "Write": "file_write",
    "Edit": "file_write",
    "Glob": "file_read",
    "Grep": "file_read",
    "Bash": "command",
    "ToolSearch": "command",
    "TodoWrite": "command",
    "NotebookEdit": "file_write",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON file, returning None if missing or corrupt."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _read_text(path: Path, max_bytes: int = 100_000, redact: bool = True) -> str | None:
    """Read a text file, returning None if missing. Truncate large files."""
    try:
        text = path.read_text()
        text = text[:max_bytes] if len(text) > max_bytes else text
        return _redact(text) if redact else text
    except FileNotFoundError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping corrupt lines."""
    results: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except FileNotFoundError:
        pass
    return results


def _parse_activity_log(path: Path) -> dict[str, list[ToolCall]]:
    """Parse an activity log into ToolCall lists keyed by step/phase name."""
    calls_by_span: dict[str, list[ToolCall]] = {}
    text = _read_text(path)
    if not text:
        return calls_by_span

    for line in text.splitlines():
        m = ACTIVITY_RE.match(line)
        if not m:
            continue
        time_str, span_name, action, detail = m.groups()
        kind = ACTION_KIND_MAP.get(action, "command")
        tc = ToolCall(kind=kind, target=detail.strip(), timestamp=time_str)
        calls_by_span.setdefault(span_name, []).append(tc)

    return calls_by_span


def _parse_transcript(path: Path) -> list[dict[str, Any]]:
    """Parse a transcript log into a sequence of reasoning and tool call entries.

    Returns a list of dicts, each with:
      - type: "reasoning" | "tool_call"
      - text: the reasoning text or tool result
      - tool: tool name (for tool_call)
      - kind: ToolCall kind (for tool_call)
      - target: file path or command (for tool_call)
    """
    text = _read_text(path, max_bytes=500_000)
    if not text:
        return []

    entries: list[dict[str, Any]] = []
    reasoning_lines: list[str] = []

    def flush_reasoning() -> None:
        if reasoning_lines:
            content = _redact("\n".join(reasoning_lines).strip())
            if content:
                entries.append({"type": "reasoning", "text": content})
            reasoning_lines.clear()

    for line in text.splitlines():
        m = TRANSCRIPT_TOOL_RE.match(line)
        if m:
            flush_reasoning()
            tool_name = m.group(1)
            target = m.group(2).strip()
            kind = TRANSCRIPT_TOOL_MAP.get(tool_name)
            if kind:
                entries.append(
                    {
                        "type": "tool_call",
                        "tool": tool_name,
                        "kind": kind,
                        "target": target,
                    }
                )
        else:
            # Skip tool result lines (indented file contents, success messages)
            stripped = line.strip()
            if stripped and not stripped.startswith(("File created", "File updated", "The file")):
                # Check if it looks like agent reasoning (not indented file content)
                if not line.startswith("     ") and not line.startswith("\t"):
                    reasoning_lines.append(stripped)

    flush_reasoning()
    return entries


def _status_from_forge(status: str) -> str:
    """Map forge step/phase status to universal status."""
    mapping = {
        "pending": "pending",
        "in_progress": "running",
        "running": "running",
        "complete": "passed",
        "completed": "passed",
        "failed": "failed",
        "skipped": "skipped",
    }
    return mapping.get(status, status)


def _overall_status(state: dict[str, Any]) -> str:
    """Determine overall trace status from state."""
    if state.get("killed"):
        return "killed"

    items = state.get("steps") or state.get("phases") or {}
    statuses = {v.get("status", "pending") for v in items.values()}

    if "failed" in statuses:
        return "failed"
    if "in_progress" in statuses or "running" in statuses:
        return "running"
    if all(s in ("complete", "completed", "skipped") for s in statuses) and statuses:
        return "completed"
    return "running"


class ForgeAdapter:
    """Adapter for the forge agent framework."""

    def detect(self, session_dir: Path) -> bool:
        """Detect if this is a forge session (executor or planner)."""
        return (session_dir / "agent-state.json").exists() or (
            session_dir / ".planner-state.json"
        ).exists()

    def load(self, session_dir: Path) -> Trace:
        """Load a forge session directory into a universal Trace."""
        executor_state = _read_json(session_dir / "agent-state.json")
        planner_state = _read_json(session_dir / ".planner-state.json")

        if executor_state:
            return self._load_executor(session_dir, executor_state)
        elif planner_state:
            return self._load_planner(session_dir, planner_state)
        else:
            raise ValueError(f"No forge state file found in {session_dir}")

    def _load_executor(self, session_dir: Path, state: dict[str, Any]) -> Trace:
        """Load an executor session."""
        steps = state.get("steps", {})
        step_order = state.get("step_order", list(steps.keys()))
        dep_graph = state.get("dependency_graph", {})

        # Parse events
        events = self._parse_events(session_dir)

        # Parse activity log for tool calls
        activity = _parse_activity_log(session_dir / "pipeline-activity.log")

        # Parse transcripts for agent reasoning and tool calls
        transcripts: dict[str, list[dict[str, Any]]] = {}
        for step_name in step_order:
            transcript_path = session_dir / f"{step_name}-transcript.log"
            entries = _parse_transcript(transcript_path)
            if entries:
                transcripts[step_name] = entries

        # Build spans from steps
        spans: list[Span] = []
        for step_name in step_order:
            step_data = steps.get(step_name, {})

            # Prefer transcript-derived tool calls (richer), fall back to activity log
            transcript_entries = transcripts.get(step_name, [])
            if transcript_entries:
                tool_calls = [
                    ToolCall(kind=e["kind"], target=e["target"])
                    for e in transcript_entries
                    if e["type"] == "tool_call"
                ]
            else:
                tool_calls = activity.get(step_name, [])
                # Load step actions for additional tool call data
                actions = _read_json(session_dir / f"{step_name}-actions.json")
                if actions and not tool_calls:
                    for f in actions.get("files_read", []):
                        tool_calls.append(ToolCall(kind="file_read", target=f))
                    for f in actions.get("files_written", []):
                        tool_calls.append(ToolCall(kind="file_write", target=f))
                    for c in actions.get("commands", []):
                        tool_calls.append(ToolCall(kind="command", target=c))

            # Load checklist into metadata
            meta: dict[str, Any] = {}
            checklist = _read_json(session_dir / f"{step_name}-checklist.json")
            if checklist:
                meta["checklist"] = checklist

            # Store agent reasoning in metadata
            reasoning = [e["text"] for e in transcript_entries if e["type"] == "reasoning"]
            if reasoning:
                meta["reasoning"] = reasoning

            span = Span(
                span_id=step_name,
                name=step_name,
                kind="step",
                status=_status_from_forge(step_data.get("status", "pending")),
                started_at=step_data.get("started_at"),
                ended_at=step_data.get("completed_at"),
                retries=step_data.get("retries", 0),
                error=_redact(step_data["last_error"]) if step_data.get("last_error") else None,
                tool_calls=tool_calls,
                metadata=meta,
            )
            spans.append(span)

        # Inject transcript-derived events into the event stream
        for step_name in step_order:
            step_data = steps.get(step_name, {})
            ts = step_data.get("started_at", "")
            for entry in transcripts.get(step_name, []):
                if entry["type"] == "reasoning":
                    events.append(
                        Event(
                            timestamp=ts,
                            type="reasoning",
                            name="agent_reasoning",
                            span_id=step_name,
                            data={"text": entry["text"][:500]},
                        )
                    )
                elif entry["type"] == "tool_call":
                    events.append(
                        Event(
                            timestamp=ts,
                            type="tool",
                            name=f"tool_{entry['kind']}",
                            span_id=step_name,
                            data={"tool": entry["tool"], "target": entry["target"]},
                        )
                    )

        # Sort events by (timestamp, type priority) to interleave properly
        type_priority = {
            "lifecycle": 0,
            "step": 1,
            "phase": 1,
            "reasoning": 2,
            "tool": 3,
            "error": 4,
            "verdict": 5,
        }
        events.sort(key=lambda e: (e.timestamp, type_priority.get(e.type, 9)))

        # Collect artifacts
        artifacts = self._collect_artifacts(session_dir, step_order)

        trace = Trace(
            trace_id=session_dir.name,
            framework="forge",
            session_type="executor",
            title=state.get("pipeline", session_dir.name),
            status=_overall_status(state),
            started_at=state.get("created_at", ""),
            ended_at=state.get("updated_at"),
            metadata={
                k: state[k]
                for k in ("pipeline", "preset", "plan_file", "model_profile")
                if k in state and state[k]
            },
            spans=spans,
            events=events,
            artifacts=artifacts,
            dependency_graph=dep_graph if dep_graph else None,
        )
        trace.compute_summary()
        return trace

    def _load_planner(self, session_dir: Path, state: dict[str, Any]) -> Trace:
        """Load a planner session."""
        phases = state.get("phases", {})

        # Parse events
        events = self._parse_events(session_dir)

        # Parse activity log
        activity = _parse_activity_log(session_dir / "planner-activity.log")

        # Build spans from phases
        spans: list[Span] = []
        for phase_name in PLANNER_PHASES:
            phase_data = phases.get(phase_name, {})
            tool_calls = activity.get(phase_name, [])

            span = Span(
                span_id=phase_name,
                name=phase_name,
                kind="phase",
                status=_status_from_forge(phase_data.get("status", "pending")),
                started_at=phase_data.get("started_at"),
                ended_at=phase_data.get("completed_at"),
                retries=phase_data.get("retries", 0),
                error=_redact(phase_data["last_error"]) if phase_data.get("last_error") else None,
                tool_calls=tool_calls,
            )
            spans.append(span)

        # Collect planner artifacts (output documents)
        artifacts: list[Artifact] = []
        for phase_name, doc_names in PLANNER_OUTPUTS.items():
            for doc_name in doc_names:
                content = _read_text(session_dir / doc_name)
                if content is not None:
                    artifacts.append(
                        Artifact(
                            name=doc_name,
                            artifact_type="document",
                            span_id=phase_name,
                            content=content,
                            path=str(session_dir / doc_name),
                        )
                    )

        # Fixed linear dependency chain
        dep_graph: dict[str, list[str]] = {}
        for i, phase in enumerate(PLANNER_PHASES):
            dep_graph[phase] = [PLANNER_PHASES[i - 1]] if i > 0 else []

        trace = Trace(
            trace_id=session_dir.name,
            framework="forge",
            session_type="planner",
            title=state.get("problem_statement", session_dir.name),
            status=_overall_status(state),
            started_at=state.get("created_at", ""),
            ended_at=state.get("updated_at"),
            metadata={
                k: state[k]
                for k in ("slug", "preset", "problem_statement", "core_tension")
                if k in state and state[k]
            },
            spans=spans,
            events=events,
            artifacts=artifacts,
            dependency_graph=dep_graph,
        )
        trace.compute_summary()
        return trace

    def _parse_events(self, session_dir: Path) -> list[Event]:
        """Parse events.jsonl into universal Event objects."""
        raw_events = _read_jsonl(session_dir / "events.jsonl")
        events: list[Event] = []

        for raw in raw_events:
            event_name = raw.get("event", "")
            event_type = EVENT_TYPE_MAP.get(event_name, "lifecycle")

            # Determine span_id from step or phase field
            span_id = raw.get("step") or raw.get("phase")

            # Build data dict with all extra fields
            data: dict[str, Any] = {}
            for k in ("error", "retries", "passed", "pass_count", "total", "checkpoint"):
                if k in raw and raw[k]:
                    data[k] = raw[k]

            events.append(
                Event(
                    timestamp=raw.get("ts", ""),
                    type=event_type,
                    name=event_name,
                    span_id=span_id,
                    data=data,
                )
            )

        return events

    def _collect_artifacts(self, session_dir: Path, step_names: list[str]) -> list[Artifact]:
        """Collect all artifacts from an executor session."""
        artifacts: list[Artifact] = []

        for step_name in step_names:
            # Checklist
            checklist = _read_json(session_dir / f"{step_name}-checklist.json")
            if checklist:
                artifacts.append(
                    Artifact(
                        name=f"{step_name}-checklist.json",
                        artifact_type="checklist",
                        span_id=step_name,
                        content=_redact(json.dumps(checklist, indent=2)),
                    )
                )

            # Actions
            actions = _read_json(session_dir / f"{step_name}-actions.json")
            if actions:
                artifacts.append(
                    Artifact(
                        name=f"{step_name}-actions.json",
                        artifact_type="checklist",
                        span_id=step_name,
                        content=_redact(json.dumps(actions, indent=2)),
                    )
                )

        # Verdict files
        for verdict_file in session_dir.glob("*-verdict.json"):
            verdict = _read_json(verdict_file)
            if verdict:
                # Determine span from filename (e.g. code-review-verdict.json → code_review)
                span_id = verdict_file.name.replace("-verdict.json", "").replace("-", "_")
                artifacts.append(
                    Artifact(
                        name=verdict_file.name,
                        artifact_type="verdict",
                        span_id=span_id,
                        content=_redact(json.dumps(verdict, indent=2)),
                    )
                )

        # Plan summary
        plan_summary = _read_text(session_dir / "pipeline-output.md")
        if plan_summary:
            artifacts.append(
                Artifact(
                    name="pipeline-output.md",
                    artifact_type="document",
                    content=plan_summary,
                )
            )

        return artifacts

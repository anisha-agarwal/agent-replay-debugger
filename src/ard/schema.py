"""Universal trace schema for agent execution replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _duration_ms(start: str | None, end: str | None) -> int | None:
    """Compute duration in milliseconds between two ISO timestamps."""
    if not start or not end:
        return None
    try:
        dt_start = _parse_iso(start)
        dt_end = _parse_iso(end)
        return int((dt_end - dt_start).total_seconds() * 1000)
    except (ValueError, TypeError):
        return None


@dataclass
class ToolCall:
    """A single tool invocation within a span (file read, write, command, etc.)."""

    kind: str  # file_read | file_write | command | llm_call
    target: str  # file path or command string
    timestamp: str | None = None
    result: str | None = None  # truncated output/error

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "target": self.target}
        if self.timestamp:
            d["timestamp"] = self.timestamp
        if self.result:
            d["result"] = self.result
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ToolCall:
        return cls(
            kind=d["kind"],
            target=d["target"],
            timestamp=d.get("timestamp"),
            result=d.get("result"),
        )


@dataclass
class Span:
    """A named execution unit: a step, phase, agent call, or tool invocation."""

    span_id: str
    name: str
    kind: str  # step | phase | agent | tool_call
    status: str  # pending | running | passed | failed | skipped
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    parent_id: str | None = None
    retries: int = 0
    error: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.duration_ms is None:
            self.duration_ms = _duration_ms(self.started_at, self.ended_at)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "span_id": self.span_id,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
        }
        if self.started_at:
            d["started_at"] = self.started_at
        if self.ended_at:
            d["ended_at"] = self.ended_at
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.parent_id:
            d["parent_id"] = self.parent_id
        if self.retries:
            d["retries"] = self.retries
        if self.error:
            d["error"] = self.error
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Span:
        return cls(
            span_id=d["span_id"],
            name=d["name"],
            kind=d["kind"],
            status=d["status"],
            started_at=d.get("started_at"),
            ended_at=d.get("ended_at"),
            duration_ms=d.get("duration_ms"),
            parent_id=d.get("parent_id"),
            retries=d.get("retries", 0),
            error=d.get("error"),
            tool_calls=[ToolCall.from_dict(tc) for tc in d.get("tool_calls", [])],
            metadata=d.get("metadata", {}),
        )


@dataclass
class Event:
    """A timestamped event in the agent execution stream."""

    timestamp: str  # ISO 8601
    type: str  # lifecycle | step | phase | error | verdict
    name: str  # original event name (e.g. step_passed)
    span_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp": self.timestamp,
            "type": self.type,
            "name": self.name,
        }
        if self.span_id:
            d["span_id"] = self.span_id
        if self.data:
            d["data"] = self.data
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Event:
        return cls(
            timestamp=d["timestamp"],
            type=d["type"],
            name=d["name"],
            span_id=d.get("span_id"),
            data=d.get("data", {}),
        )


@dataclass
class Artifact:
    """An output document or file produced during execution."""

    name: str
    artifact_type: str  # plan | checklist | review | transcript | document | verdict
    span_id: str | None = None
    content: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "artifact_type": self.artifact_type}
        if self.span_id:
            d["span_id"] = self.span_id
        if self.content is not None:
            d["content"] = self.content
        if self.path:
            d["path"] = self.path
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Artifact:
        return cls(
            name=d["name"],
            artifact_type=d["artifact_type"],
            span_id=d.get("span_id"),
            content=d.get("content"),
            path=d.get("path"),
        )


@dataclass
class TraceSummary:
    """Computed statistics for a trace."""

    total_duration_ms: int | None = None
    span_count: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    retries: int = 0
    files_read: int = 0
    files_written: int = 0
    commands_run: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_duration_ms": self.total_duration_ms,
            "span_count": self.span_count,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "retries": self.retries,
            "files_read": self.files_read,
            "files_written": self.files_written,
            "commands_run": self.commands_run,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceSummary:
        return cls(**{k: d.get(k, 0) for k in cls.__dataclass_fields__})


@dataclass
class Trace:
    """Top-level container for an agent execution trace."""

    trace_id: str
    schema_version: str = "1.0"
    framework: str = ""
    session_type: str = ""  # executor | planner | custom
    title: str = ""
    status: str = ""  # completed | failed | running | killed
    started_at: str = ""
    ended_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    dependency_graph: dict[str, list[str]] | None = None
    summary: TraceSummary = field(default_factory=TraceSummary)

    def compute_summary(self) -> TraceSummary:
        """Compute summary statistics from spans and events."""
        s = TraceSummary()
        s.total_duration_ms = _duration_ms(self.started_at, self.ended_at)
        s.span_count = len(self.spans)
        for span in self.spans:
            if span.status == "passed":
                s.passed += 1
            elif span.status == "failed":
                s.failed += 1
            elif span.status == "skipped":
                s.skipped += 1
            s.retries += span.retries
            for tc in span.tool_calls:
                if tc.kind == "file_read":
                    s.files_read += 1
                elif tc.kind == "file_write":
                    s.files_written += 1
                elif tc.kind == "command":
                    s.commands_run += 1
        s.errors = sum(1 for e in self.events if e.type == "error")
        self.summary = s
        return s

    def validate(self) -> list[str]:
        """Validate the trace and return a list of issues (empty = valid)."""
        issues: list[str] = []
        if not self.trace_id:
            issues.append("trace_id is required")
        if not self.started_at:
            issues.append("started_at is required")
        if not self.framework:
            issues.append("framework is required")
        for span in self.spans:
            if not span.span_id:
                issues.append(f"span missing span_id: {span.name}")
            if not span.kind:
                issues.append(f"span missing kind: {span.span_id}")
        for event in self.events:
            if not event.timestamp:
                issues.append(f"event missing timestamp: {event.name}")
            if not event.type:
                issues.append(f"event missing type: {event.name}")
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "framework": self.framework,
            "session_type": self.session_type,
            "title": self.title,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "metadata": self.metadata,
            "spans": [s.to_dict() for s in self.spans],
            "events": [e.to_dict() for e in self.events],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "dependency_graph": self.dependency_graph,
            "summary": self.summary.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trace:
        trace = cls(
            trace_id=d["trace_id"],
            schema_version=d.get("schema_version", "1.0"),
            framework=d.get("framework", ""),
            session_type=d.get("session_type", ""),
            title=d.get("title", ""),
            status=d.get("status", ""),
            started_at=d.get("started_at", ""),
            ended_at=d.get("ended_at"),
            metadata=d.get("metadata", {}),
            spans=[Span.from_dict(s) for s in d.get("spans", [])],
            events=[Event.from_dict(e) for e in d.get("events", [])],
            artifacts=[Artifact.from_dict(a) for a in d.get("artifacts", [])],
            dependency_graph=d.get("dependency_graph"),
            summary=TraceSummary.from_dict(d["summary"]) if "summary" in d else TraceSummary(),
        )
        return trace

"""Trace diff — compare two agent execution traces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ard.schema import Trace


@dataclass
class SpanDiff:
    """Comparison of a single span between two traces."""

    name: str
    status_a: str | None = None
    status_b: str | None = None
    duration_a: int | None = None
    duration_b: int | None = None
    duration_delta_ms: int | None = None
    duration_pct_change: float | None = None
    tools_a: int = 0
    tools_b: int = 0
    tools_delta: int = 0
    only_in: str | None = None  # "a", "b", or None (in both)


@dataclass
class FileDiff:
    """File touched comparison."""

    path: str
    in_a: bool = False
    in_b: bool = False


@dataclass
class TraceDiff:
    """Full comparison between two traces."""

    title_a: str = ""
    title_b: str = ""
    duration_a: int | None = None
    duration_b: int | None = None
    duration_delta_ms: int | None = None
    duration_pct_change: float | None = None
    spans_a: int = 0
    spans_b: int = 0
    events_a: int = 0
    events_b: int = 0
    span_diffs: list[SpanDiff] = field(default_factory=list)
    file_diffs: list[FileDiff] = field(default_factory=list)
    # Counts
    faster_spans: int = 0
    slower_spans: int = 0
    new_spans: int = 0
    removed_spans: int = 0
    status_changes: int = 0
    files_only_a: int = 0
    files_only_b: int = 0
    files_both: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title_a": self.title_a,
            "title_b": self.title_b,
            "duration_a": self.duration_a,
            "duration_b": self.duration_b,
            "duration_delta_ms": self.duration_delta_ms,
            "duration_pct_change": self.duration_pct_change,
            "spans_a": self.spans_a,
            "spans_b": self.spans_b,
            "events_a": self.events_a,
            "events_b": self.events_b,
            "span_diffs": [
                {k: v for k, v in sd.__dict__.items() if v is not None} for sd in self.span_diffs
            ],
            "file_diffs": [fd.__dict__ for fd in self.file_diffs],
            "faster_spans": self.faster_spans,
            "slower_spans": self.slower_spans,
            "new_spans": self.new_spans,
            "removed_spans": self.removed_spans,
            "status_changes": self.status_changes,
            "files_only_a": self.files_only_a,
            "files_only_b": self.files_only_b,
            "files_both": self.files_both,
        }


def _extract_files(trace: Trace) -> set[str]:
    """Extract all file paths from tool calls."""
    files: set[str] = set()
    for span in trace.spans:
        for tc in span.tool_calls:
            if tc.kind in ("file_read", "file_write") and tc.target:
                files.add(tc.target)
    return files


def _pct_change(old: int | None, new: int | None) -> float | None:
    if old is None or new is None or old == 0:
        return None
    return round((new - old) / old * 100, 1)


def diff_traces(trace_a: Trace, trace_b: Trace) -> TraceDiff:
    """Compare two traces and produce a structured diff."""
    result = TraceDiff(
        title_a=trace_a.title,
        title_b=trace_b.title,
        duration_a=trace_a.summary.total_duration_ms,
        duration_b=trace_b.summary.total_duration_ms,
        spans_a=len(trace_a.spans),
        spans_b=len(trace_b.spans),
        events_a=len(trace_a.events),
        events_b=len(trace_b.events),
    )

    # Duration delta
    if result.duration_a is not None and result.duration_b is not None:
        result.duration_delta_ms = result.duration_b - result.duration_a
        result.duration_pct_change = _pct_change(result.duration_a, result.duration_b)

    # Build span maps by name
    spans_a = {s.name: s for s in trace_a.spans}
    spans_b = {s.name: s for s in trace_b.spans}
    all_names = list(dict.fromkeys(list(spans_a.keys()) + list(spans_b.keys())))

    for name in all_names:
        sa = spans_a.get(name)
        sb = spans_b.get(name)

        sd = SpanDiff(name=name)

        if sa and not sb:
            sd.only_in = "a"
            sd.status_a = sa.status
            sd.duration_a = sa.duration_ms
            sd.tools_a = len(sa.tool_calls)
            result.removed_spans += 1
        elif sb and not sa:
            sd.only_in = "b"
            sd.status_b = sb.status
            sd.duration_b = sb.duration_ms
            sd.tools_b = len(sb.tool_calls)
            result.new_spans += 1
        else:
            sd.status_a = sa.status
            sd.status_b = sb.status
            sd.duration_a = sa.duration_ms
            sd.duration_b = sb.duration_ms
            sd.tools_a = len(sa.tool_calls)
            sd.tools_b = len(sb.tool_calls)
            sd.tools_delta = sd.tools_b - sd.tools_a

            if sd.duration_a is not None and sd.duration_b is not None:
                sd.duration_delta_ms = sd.duration_b - sd.duration_a
                sd.duration_pct_change = _pct_change(sd.duration_a, sd.duration_b)
                if sd.duration_delta_ms < 0:
                    result.faster_spans += 1
                elif sd.duration_delta_ms > 0:
                    result.slower_spans += 1

            if sd.status_a != sd.status_b:
                result.status_changes += 1

        result.span_diffs.append(sd)

    # File diffs
    files_a = _extract_files(trace_a)
    files_b = _extract_files(trace_b)
    all_files = sorted(files_a | files_b)

    for path in all_files:
        in_a = path in files_a
        in_b = path in files_b
        result.file_diffs.append(FileDiff(path=path, in_a=in_a, in_b=in_b))
        if in_a and in_b:
            result.files_both += 1
        elif in_a:
            result.files_only_a += 1
        else:
            result.files_only_b += 1

    return result

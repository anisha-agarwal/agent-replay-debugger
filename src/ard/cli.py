"""CLI entry point for the Agent Replay Debugger."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import webbrowser
from pathlib import Path

from ard.adapters.base import detect_adapter
from ard.viewer import generate_html


def cmd_trace(args: argparse.Namespace) -> int:
    """Output a universal trace JSON for a session directory or file."""
    session_dir = Path(args.session_dir).resolve()
    if not session_dir.exists():
        print(f"Error: {session_dir} does not exist", file=sys.stderr)
        return 1

    adapter = detect_adapter(session_dir)
    if not adapter:
        print(f"Error: no adapter found for {session_dir}", file=sys.stderr)
        return 1

    trace = adapter.load(session_dir)
    indent = 2 if args.pretty else None
    print(json.dumps(trace.to_dict(), indent=indent))
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    """Generate and open an interactive HTML trace viewer."""
    session_dir = Path(args.session_dir).resolve()
    if not session_dir.exists():
        print(f"Error: {session_dir} does not exist", file=sys.stderr)
        return 1

    adapter = detect_adapter(session_dir)
    if not adapter:
        print(f"Error: no adapter found for {session_dir}", file=sys.stderr)
        return 1

    trace = adapter.load(session_dir)
    html = generate_html(trace)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(html)
        print(f"Written to {output_path}")
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(html)
            tmp_path = f.name
        print(f"Opening {tmp_path}")
        webbrowser.open(f"file://{tmp_path}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List available forge sessions."""
    sessions_base = Path(os.environ.get("FORGE_SESSIONS", Path.home() / ".forge" / "sessions"))

    if not sessions_base.is_dir():
        print(f"No sessions directory found at {sessions_base}", file=sys.stderr)
        return 1

    rows: list[tuple[str, str, str, str]] = []

    for subsystem in ("executor", "planner"):
        sub_dir = sessions_base / subsystem
        if not sub_dir.is_dir():
            continue
        for session_dir in sorted(sub_dir.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue

            # Quick read of state file for status
            state_file = (
                session_dir / "agent-state.json"
                if subsystem == "executor"
                else session_dir / ".planner-state.json"
            )
            status = "unknown"
            created = ""
            try:
                state = json.loads(state_file.read_text())
                if state.get("killed"):
                    status = "killed"
                else:
                    items = state.get("steps") or state.get("phases") or {}
                    statuses = {v.get("status", "pending") for v in items.values()}
                    if "failed" in statuses:
                        status = "failed"
                    elif all(s in ("complete", "completed", "skipped") for s in statuses):
                        status = "completed"
                    else:
                        status = "running"
                created = state.get("created_at", "")[:19]
            except (FileNotFoundError, json.JSONDecodeError):
                pass

            rows.append((session_dir.name, subsystem, status, created))

    if not rows:
        print("No sessions found.")
        return 0

    # Print formatted table
    headers = ("SESSION", "TYPE", "STATUS", "CREATED")
    col_widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))]

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print("  ".join(row[i].ljust(col_widths[i]) for i in range(len(row))))

    return 0


CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _find_project_dir(name: str) -> Path | None:
    """Find a Claude Code project directory by partial name match."""
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return None
    candidates = []
    for d in CLAUDE_PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        # Match against the last segment of the encoded path
        # e.g. "-Users-anisha-chore-champions" matches "chore-champions"
        parts = d.name.split("-")
        # Rebuild possible project names from the end
        for i in range(len(parts)):
            candidate = "-".join(parts[i:])
            if candidate.lower() == name.lower():
                candidates.append(d)
                break
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # Prefer the longest path (most specific match)
        return max(candidates, key=lambda p: len(p.name))
    return None


def _list_sessions(project_dir: Path) -> list[tuple[str, float, int]]:
    """List JSONL sessions in a project dir, sorted by mtime desc.
    Returns (path, mtime, size) tuples."""
    sessions = []
    for f in project_dir.iterdir():
        if f.suffix == ".jsonl" and f.stat().st_size > 100:
            sessions.append((str(f), f.stat().st_mtime, f.stat().st_size))
    sessions.sort(key=lambda x: x[1], reverse=True)
    return sessions


def cmd_pick(args: argparse.Namespace) -> int:
    """Find and output a Claude Code session path."""
    project_dir = _find_project_dir(args.project)
    if not project_dir:
        # Try as a direct path
        direct = Path(args.project)
        if direct.is_dir():
            project_dir = direct
        else:
            available = []
            if CLAUDE_PROJECTS_DIR.is_dir():
                available = [d.name for d in CLAUDE_PROJECTS_DIR.iterdir() if d.is_dir()]
            print(f"Error: project '{args.project}' not found", file=sys.stderr)
            if available:
                print(f"Available: {', '.join(sorted(available))}", file=sys.stderr)
            return 1

    sessions = _list_sessions(project_dir)
    if not sessions:
        print(f"No sessions found in {project_dir}", file=sys.stderr)
        return 1

    if args.list:
        from datetime import datetime, timezone

        print(f"Sessions in {project_dir.name}:\n")
        for path, mtime, size in sessions:
            dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            size_kb = size // 1024
            name = Path(path).stem[:36]
            print(f"  {name}  {dt:%Y-%m-%d %H:%M}  {size_kb}KB")
        return 0

    # Default: pick latest
    idx = 0
    if args.n and args.n > 1:
        idx = min(args.n - 1, len(sessions) - 1)

    path = sessions[idx][0]
    print(path)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ard",
        description="Agent Replay Debugger — visualize agent execution traces",
    )
    subparsers = parser.add_subparsers(dest="command")

    # trace
    p_trace = subparsers.add_parser("trace", help="Output universal trace JSON")
    p_trace.add_argument("session_dir", help="Path to session directory")
    p_trace.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    # view
    p_view = subparsers.add_parser("view", help="Open interactive HTML trace viewer")
    p_view.add_argument("session_dir", help="Path to session directory")
    p_view.add_argument("--output", "-o", help="Write HTML to file instead of opening")

    # list
    subparsers.add_parser("list", help="List available sessions")

    # pick
    p_pick = subparsers.add_parser("pick", help="Find a Claude Code session by project name")
    p_pick.add_argument("project", help="Project name (e.g. 'chore-champions') or path")
    p_pick.add_argument("--list", "-l", action="store_true", help="List all sessions for project")
    p_pick.add_argument(
        "-n", type=int, default=1, help="Pick nth most recent (default: 1 = latest)"
    )

    args = parser.parse_args()

    if args.command == "trace":
        sys.exit(cmd_trace(args))
    elif args.command == "view":
        sys.exit(cmd_view(args))
    elif args.command == "list":
        sys.exit(cmd_list(args))
    elif args.command == "pick":
        sys.exit(cmd_pick(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

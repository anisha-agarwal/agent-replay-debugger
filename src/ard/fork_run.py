"""Full re-execution fork — resumes a Claude Code session with a modified prompt."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any


def _get_session_id(session_path: Path) -> str:
    """Extract the session ID from a Claude Code JSONL."""
    with open(session_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                sid = d.get("sessionId", "")
                if sid:
                    return sid
            except json.JSONDecodeError:
                continue
    raise ValueError(f"No sessionId found in {session_path}")


def _find_project_dir(session_path: Path) -> Path:
    """Find the project directory containing the session."""
    return session_path.parent


def _find_newest_jsonl(project_dir: Path, after_mtime: float) -> Path | None:
    """Find the newest .jsonl in project_dir created after the given mtime."""
    newest = None
    newest_mtime = after_mtime
    for f in project_dir.iterdir():
        if f.suffix == ".jsonl" and f.stat().st_mtime > newest_mtime:
            newest = f
            newest_mtime = f.stat().st_mtime
    return newest


def fork_and_run(
    session_path: Path,
    new_prompt: str,
    cwd: str | None = None,
    max_budget: float | None = None,
) -> dict[str, Any]:
    """Fork a Claude Code session and re-execute with a new prompt.

    Returns dict with original and forked session paths.
    """
    session_id = _get_session_id(session_path)
    project_dir = _find_project_dir(session_path)

    # Record time before forking so we can find the new session
    before_time = time.time()

    # Build claude command
    cmd = [
        "claude",
        "--resume",
        session_id,
        "--fork-session",
        "-p",
        new_prompt,
        "--output-format",
        "text",
    ]

    if max_budget:
        cmd.extend(["--max-budget-usd", str(max_budget)])

    work_dir = cwd or str(Path.cwd())

    print(f"Forking session {session_id[:8]}...")
    print(f'Running: claude --resume {session_id[:8]}... --fork-session -p "{new_prompt[:60]}..."')
    print(f"Working directory: {work_dir}")
    print()

    result = subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        error = result.stderr[:500] if result.stderr else "Unknown error"
        raise RuntimeError(f"Claude Code failed (exit {result.returncode}): {error}")

    # Print agent output
    if result.stdout:
        print("--- Agent output ---")
        print(result.stdout[:2000])
        if len(result.stdout) > 2000:
            print(f"... ({len(result.stdout)} chars total)")
        print("--- End output ---")
        print()

    # Find the new forked session
    forked_path = _find_newest_jsonl(project_dir, before_time)
    if not forked_path:
        raise RuntimeError(
            "Could not find the forked session trace. "
            "The claude command may not have created a new session."
        )

    return {
        "original_session": str(session_path),
        "forked_session": str(forked_path),
        "session_id": session_id,
        "prompt": new_prompt,
        "agent_output": result.stdout[:5000] if result.stdout else "",
    }

# agent-replay-debugger

[![CI](https://github.com/anisha-agarwal/agent-replay-debugger/actions/workflows/ci.yml/badge.svg)](https://github.com/anisha-agarwal/agent-replay-debugger/actions/workflows/ci.yml)
![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.12+-blue)
![Dependencies](https://img.shields.io/badge/dependencies-0-green)

Framework-agnostic CLI that turns AI agent execution traces into interactive HTML timelines. See what your agent was thinking — every reasoning block, every tool call, every decision.

**[Live demo](https://anisha-agarwal.github.io/agent-replay-debugger/)** · **[GitHub](https://github.com/anisha-agarwal/agent-replay-debugger)**

## Why

When an agent fails 30 minutes into a task, you're left staring at the end result with no idea which decision broke things. Existing tools (LangSmith, Arize, AgentOps) are passive log viewers locked to specific frameworks.

ARD is different:
- **Framework-agnostic** — pluggable adapter protocol, not locked to one framework
- **Local-first** — runs on your machine, no SaaS, works offline
- **Shows actual reasoning** — not just lifecycle status events
- **Zero runtime dependencies** — pure Python standard library

## Install

```bash
pip install agent-replay-debugger
```

Or with uv:

```bash
uv pip install agent-replay-debugger
```

Or from source:

```bash
git clone https://github.com/anisha-agarwal/agent-replay-debugger
cd agent-replay-debugger
uv sync
```

## Usage

### View a trace

```bash
# Forge session directory
ard view ~/.forge/sessions/executor/my-session/

# Claude Code session file
ard view ~/.claude/projects/my-project/session-id.jsonl

# Save to file instead of opening browser
ard view ./session/ --output trace.html
```

This generates a self-contained HTML file (all data inlined, no server needed) and opens it in your browser.

### Export as JSON

```bash
ard trace ./session/ --pretty
```

Outputs the universal trace format to stdout. Pipe it, save it, diff it.

### List sessions

```bash
ard list
```

Shows all available forge sessions with type, status, and creation date.

### Pick a session by project name

```bash
# Get the latest Claude Code session for a project
ard pick chore-champions

# List all sessions for a project
ard pick chore-champions --list

# Get the 2nd most recent session
ard pick chore-champions -n 2

# Pipe directly into view
ard view $(ard pick chore-champions)
```

Matches project names by partial suffix — `chore-champions` finds `~/.claude/projects/-Users-you-chore-champions/`.

## What the viewer shows

- **Summary stats** — duration, passed/failed spans, retries, files touched, commands run
- **DAG visualization** — pipeline dependencies with duration and tool count per node. Click any node to filter the timeline to that span.
- **Duration bar** — proportional timeline showing where time was spent
- **Event timeline** — every reasoning block, tool call, state transition, and error. Expandable cards with full payloads. Consecutive reasoning events collapse into groups.
- **Bottleneck indicators** — gaps >30s between events are flagged
- **Keyboard navigation** — j/k to move, Enter to expand
- **Filters** — by span, event type, or text search

## Adapters

ARD uses a pluggable adapter system. Each adapter converts framework-specific trace data into a universal schema.

### Built-in adapters

| Adapter | Detects | What it parses |
|---------|---------|----------------|
| **Forge** | `agent-state.json` or `.planner-state.json` in directory | State files, events.jsonl, transcripts, activity logs, checklists, verdicts |
| **Claude Code** | `.jsonl` file with `sessionId` field | User messages, assistant reasoning (thinking + text), all tool calls |
| **Generic JSON** | `trace.json` file in directory (or passed directly) | Any `trace.json` conforming to the universal schema — works with any framework |

### Writing your own adapter

Create a single Python file that implements two methods:

```python
from pathlib import Path
from ard.schema import Trace

class MyAdapter:
    def detect(self, session_dir: Path) -> bool:
        """Return True if this adapter can handle the given path."""
        return (session_dir / "my-framework-state.json").exists()

    def load(self, session_dir: Path) -> Trace:
        """Convert framework data into a universal Trace."""
        # Parse your framework's files...
        return Trace(
            trace_id="my-session",
            framework="my-framework",
            session_type="execution",
            started_at="2026-01-01T00:00:00Z",
            spans=[...],
            events=[...],
        )
```

Register it in `src/ard/adapters/base.py`:

```python
from ard.adapters.my_adapter import MyAdapter

adapters: list[TraceAdapter] = [ForgeAdapter(), ClaudeCodeAdapter(), MyAdapter()]
```

## Universal trace schema

```
Trace
├── trace_id, framework, session_type, title, status
├── started_at, ended_at
├── spans[]          — named execution units (steps, phases, agent calls)
│   ├── span_id, name, kind, status
│   ├── started_at, ended_at, duration_ms, retries, error
│   ├── tool_calls[] — file reads, writes, commands, LLM calls
│   └── metadata     — checklists, reasoning blocks, etc.
├── events[]         — timestamped stream driving the timeline
│   ├── timestamp, type, name, span_id, data
├── artifacts[]      — output documents (plans, verdicts, etc.)
├── dependency_graph — span_id → [dependency_span_ids]
└── summary          — computed stats
```

## Security

All output is automatically scrubbed before it reaches the viewer:

- API keys (Anthropic, OpenAI, Supabase, GitHub, Slack)
- JWTs
- `password=`, `api_key=`, `secret=`, `access_token=` patterns
- Email addresses
- User home paths (`/Users/you` → `/Users/dev`)
- UUIDs
- GitHub usernames in URLs

You can safely share ARD output without leaking credentials or PII.

## Development

```bash
git clone https://github.com/anisha-agarwal/agent-replay-debugger
cd agent-replay-debugger
uv sync --extra dev

# Run tests
uv run pytest -v

# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/
```

## License

MIT

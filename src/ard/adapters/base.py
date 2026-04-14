"""Base adapter protocol for trace loading."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ard.schema import Trace


class TraceAdapter(Protocol):
    """Protocol that all framework adapters must implement."""

    def detect(self, session_dir: Path) -> bool:
        """Return True if this adapter can handle the given session directory."""
        ...

    def load(self, session_dir: Path) -> Trace:
        """Load a session directory and convert it to a universal Trace."""
        ...


def detect_adapter(session_dir: Path) -> TraceAdapter | None:
    """Auto-detect the appropriate adapter for a session directory."""
    from ard.adapters.claude_code import ClaudeCodeAdapter
    from ard.adapters.forge import ForgeAdapter
    from ard.adapters.generic import GenericAdapter

    adapters: list[TraceAdapter] = [ForgeAdapter(), ClaudeCodeAdapter(), GenericAdapter()]
    for adapter in adapters:
        if adapter.detect(session_dir):
            return adapter
    return None

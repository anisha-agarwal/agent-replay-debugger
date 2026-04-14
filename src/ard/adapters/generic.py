"""Generic JSON adapter — reads a trace.json file conforming to the universal schema."""

from __future__ import annotations

import json
from pathlib import Path

from ard.schema import Trace


class GenericAdapter:
    """Adapter that reads a trace.json file already in universal schema format."""

    def detect(self, session_dir: Path) -> bool:
        if session_dir.is_file() and session_dir.name == "trace.json":
            return True
        if session_dir.is_dir() and (session_dir / "trace.json").exists():
            return True
        return False

    def load(self, session_dir: Path) -> Trace:
        path = session_dir if session_dir.is_file() else session_dir / "trace.json"
        data = json.loads(path.read_text())
        trace = Trace.from_dict(data)
        issues = trace.validate()
        if issues:
            raise ValueError(f"Invalid trace.json: {'; '.join(issues)}")
        trace.compute_summary()
        return trace

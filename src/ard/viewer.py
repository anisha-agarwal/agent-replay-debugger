"""HTML viewer generator — injects trace data into the viewer template."""

from __future__ import annotations

import json
from importlib import resources

from ard.schema import Trace


def generate_html(trace: Trace) -> str:
    """Generate a self-contained HTML file with trace data embedded."""
    template = resources.files("ard").joinpath("viewer_template.html").read_text()
    trace_json = json.dumps(trace.to_dict(), indent=2)
    return template.replace("__TRACE_DATA_PLACEHOLDER__", trace_json)

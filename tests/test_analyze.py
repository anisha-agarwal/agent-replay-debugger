"""Tests for LLM-powered trace annotation."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ard.analyze import annotate_trace
from ard.schema import Event, Span, Trace


def _make_trace(reasoning_texts: list[str]) -> Trace:
    events = [
        Event(
            timestamp="2026-04-10T10:00:00Z",
            type="reasoning",
            name="agent_response",
            data={"text": text},
        )
        for text in reasoning_texts
    ]
    return Trace(
        trace_id="test",
        framework="test",
        started_at="2026-04-10T10:00:00Z",
        spans=[Span(span_id="s1", name="s1", kind="agent", status="passed")],
        events=events,
    )


class TestAnnotateTrace:
    def test_adds_categories(self):
        trace = _make_trace(["Let me plan the approach", "Reading the file now"])
        api_response = [
            {"category": "planning", "flag": None},
            {"category": "investigating", "flag": None},
        ]
        with patch("ard.analyze._call_api", return_value=api_response):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
                result = annotate_trace(trace)
        assert result.events[0].data["category"] == "planning"
        assert result.events[1].data["category"] == "investigating"

    def test_adds_flags(self):
        trace = _make_trace(["Oops wrong file, let me go back"])
        api_response = [{"category": "debugging", "flag": "backtracking"}]
        with patch("ard.analyze._call_api", return_value=api_response):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
                result = annotate_trace(trace)
        assert result.events[0].data["flag"] == "backtracking"

    def test_no_flag_when_null(self):
        trace = _make_trace(["Normal reasoning"])
        api_response = [{"category": "implementing", "flag": None}]
        with patch("ard.analyze._call_api", return_value=api_response):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
                result = annotate_trace(trace)
        assert "flag" not in result.events[0].data

    def test_skips_non_reasoning_events(self):
        trace = Trace(
            trace_id="test",
            framework="test",
            started_at="2026-04-10T10:00:00Z",
            events=[
                Event(timestamp="t", type="tool", name="tool_Read", data={"tool": "Read"}),
            ],
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
            result = annotate_trace(trace)
        assert "category" not in result.events[0].data

    def test_no_api_key_raises(self):
        trace = _make_trace(["test"])
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                annotate_trace(trace)

    def test_api_failure_continues(self, capsys):
        trace = _make_trace(["test reasoning"])
        with patch("ard.analyze._call_api", side_effect=Exception("API error")):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
                result = annotate_trace(trace)
        assert "category" not in result.events[0].data
        assert "Warning" in capsys.readouterr().out

    def test_batching(self):
        texts = [f"reasoning block {i}" for i in range(50)]
        trace = _make_trace(texts)
        call_count = 0

        def mock_api(reasoning_texts, api_key):
            nonlocal call_count
            call_count += 1
            return [{"category": "implementing", "flag": None}] * len(reasoning_texts)

        with patch("ard.analyze._call_api", side_effect=mock_api):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
                result = annotate_trace(trace)
        assert call_count == 2  # 50 items, batch of 40 = 2 calls
        assert result.events[0].data["category"] == "implementing"

    def test_empty_trace(self):
        trace = Trace(
            trace_id="test",
            framework="test",
            started_at="2026-04-10T10:00:00Z",
            events=[],
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
            result = annotate_trace(trace)
        assert len(result.events) == 0


class TestCallAPI:
    def test_parses_response(self):
        mock_response_body = json.dumps(
            {"content": [{"text": '[{"category": "planning", "flag": null}]'}]}
        ).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ard.analyze.urllib.request.urlopen", return_value=mock_resp):
            from ard.analyze import _call_api

            result = _call_api(["Let me plan this"], "fake-key")
        assert result == [{"category": "planning", "flag": None}]

    def test_handles_text_around_json(self):
        mock_response_body = json.dumps(
            {
                "content": [
                    {
                        "text": 'Here are the results:\n[{"category": "debugging", "flag": "backtracking"}]\nDone.'
                    }
                ]
            }
        ).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ard.analyze.urllib.request.urlopen", return_value=mock_resp):
            from ard.analyze import _call_api

            result = _call_api(["oops wrong file"], "fake-key")
        assert result[0]["flag"] == "backtracking"

    def test_fallback_on_no_json(self):
        mock_response_body = json.dumps(
            {"content": [{"text": "I cannot classify these."}]}
        ).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ard.analyze.urllib.request.urlopen", return_value=mock_resp):
            from ard.analyze import _call_api

            result = _call_api(["test"], "fake-key")
        assert result == [{"category": "explaining", "flag": None}]

    def test_malformed_array_extracts_objects(self):
        malformed = '[{"category": "planning", "flag": null} some garbage {"category": "debugging", "flag": "tangent"}]'
        mock_response_body = json.dumps({"content": [{"text": malformed}]}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ard.analyze.urllib.request.urlopen", return_value=mock_resp):
            from ard.analyze import _call_api

            result = _call_api(["plan this", "wrong turn"], "fake-key")
        assert len(result) == 2
        assert result[0]["category"] == "planning"
        assert result[1]["flag"] == "tangent"

    def test_control_characters_stripped(self):
        text_with_controls = '[{"category": "implementing",\x00 "flag": null}]'
        mock_response_body = json.dumps({"content": [{"text": text_with_controls}]}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ard.analyze.urllib.request.urlopen", return_value=mock_resp):
            from ard.analyze import _call_api

            result = _call_api(["build it"], "fake-key")
        assert result[0]["category"] == "implementing"

    def test_malformed_objects_skipped(self):
        text = '[{"category": "planning", "flag": null}, {broken object}, {"category": "testing", "flag": null}]'
        mock_response_body = json.dumps({"content": [{"text": text}]}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ard.analyze.urllib.request.urlopen", return_value=mock_resp):
            from ard.analyze import _call_api

            result = _call_api(["a", "b", "c"], "fake-key")
        assert len(result) == 2
        assert result[0]["category"] == "planning"
        assert result[1]["category"] == "testing"

    def test_completely_broken_json_fallback(self):
        mock_response_body = json.dumps({"content": [{"text": "[no valid objects here at all]"}]}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ard.analyze.urllib.request.urlopen", return_value=mock_resp):
            from ard.analyze import _call_api

            result = _call_api(["test", "test2"], "fake-key")
        assert len(result) == 2
        assert result[0]["category"] == "explaining"

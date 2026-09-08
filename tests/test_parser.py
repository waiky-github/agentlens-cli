"""Tests for JSONL parser and Hermes gateway.log best-effort parsing."""

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure the package root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentlens_cli.parser import parse_jsonl, parse_gateway_log


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _read_jsonl(path):
    """Return list of dicts from a JSONL file."""
    return list(parse_jsonl(str(path)))


# ── JSONL parsing ──────────────────────────────────────────────────


class TestParseJsonl:
    """JSONL parsing: event count, field presence, skip handling."""

    def test_parse_v2_events_count(self):
        events = _read_jsonl(EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl")
        assert len(events) == 20, f"expected 20 events, got {len(events)}"

    def test_parse_v2_required_fields(self):
        events = _read_jsonl(EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl")
        for evt in events:
            assert "event_id" in evt, f"missing event_id in {evt}"
            assert "type" in evt, f"missing type in {evt}"
            assert "timestamp" in evt, f"missing timestamp in {evt}"
            assert "payload" in evt, f"missing payload in {evt}"

    def test_parse_shadow_events_count(self):
        events = _read_jsonl(EXAMPLES_DIR / "shadow_agent_events.jsonl")
        assert len(events) == 7, f"expected 7 events, got {len(events)}"

    def test_parse_compliance_events_count(self):
        events = _read_jsonl(EXAMPLES_DIR / "compliance_violations.jsonl")
        assert len(events) == 5, f"expected 5 events, got {len(events)}"

    def test_parse_hermes_events_count(self):
        events = _read_jsonl(EXAMPLES_DIR / "hermes_gateway_events.jsonl")
        assert len(events) == 11268, f"expected 11268 events, got {len(events)}"

    def test_parse_hermes_event_types_present(self):
        events = _read_jsonl(EXAMPLES_DIR / "hermes_gateway_events.jsonl")
        types = set(e.get("type") for e in events)
        assert "user_message_arrived" in types
        assert "agent_response_sent" in types
        assert "model_call" in types
        assert "tool_invocation" in types
        assert "session_event" in types

    def test_parse_blank_lines_skipped(self):
        """Blank lines are skipped without error."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            f.write('\n{"event_id":"a","type":"test","timestamp":"2026-01-01T00:00:00Z","payload":{}}\n\n')
            f.write('{"event_id":"b","type":"test","timestamp":"2026-01-01T00:00:01Z","payload":{}}\n\n')
            tmp = f.name
        try:
            events = list(parse_jsonl(tmp))
            assert len(events) == 2, f"expected 2 events, got {len(events)}"
        finally:
            os.unlink(tmp)

    def test_parse_invalid_json_skipped(self):
        """Lines that are not valid JSON are skipped, not crashed."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            f.write('{"event_id":"a","type":"test","timestamp":"2026-01-01T00:00:00Z","payload":{}}\n')
            f.write('this is not valid json\n')
            f.write('{"event_id":"b","type":"test","timestamp":"2026-01-01T00:00:01Z","payload":{}}\n')
            tmp = f.name
        try:
            events = list(parse_jsonl(tmp))
            # 2 valid events, 1 line skipped
            assert len(events) == 2, f"expected 2 valid events, got {len(events)}"
        finally:
            os.unlink(tmp)


# ── Hermes gateway.log best-effort parsing ──────────────────────────


class TestParseGatewayLog:
    """Best-effort parsing of Hermes gateway.log text."""

    def test_tool_with_metrics_parsed(self):
        line = (
            "2026-06-03 11:08:00 agent.tool_executor: tool shell completed "
            "output_chars=12345 duration=2.5 agent:main"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(line + "\n")
            tmp = f.name
        try:
            events = list(parse_gateway_log(tmp))
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "tool_invocation"
            assert evt["payload"]["tool"] == "shell"
            assert evt["payload"]["output_chars"] == 12345
            assert evt["payload"]["duration_seconds"] == 2.5
        finally:
            os.unlink(tmp)

    def test_tool_simple_parsed(self):
        line = (
            "2026-06-03 11:08:00 agent.tool_executor: tool read completed agent:main"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(line + "\n")
            tmp = f.name
        try:
            events = list(parse_gateway_log(tmp))
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "tool_invocation"
            assert evt["payload"]["tool"] == "read"
        finally:
            os.unlink(tmp)

    def test_model_call_parsed(self):
        line = (
            "2026-06-03 11:08:00 agent.conversation_loop: API call "
            "tokens_in=18000 tokens_out=200 tokens_total=18200 agent:main"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(line + "\n")
            tmp = f.name
        try:
            events = list(parse_gateway_log(tmp))
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "model_call"
            assert evt["payload"]["tokens_in"] == 18000
            assert evt["payload"]["tokens_out"] == 200
            assert evt["payload"]["tokens_total"] == 18200
        finally:
            os.unlink(tmp)

    def test_user_message_parsed(self):
        line = "2026-06-03 11:08:00 Inbound dm message received from feishu"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(line + "\n")
            tmp = f.name
        try:
            events = list(parse_gateway_log(tmp))
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "user_message_arrived"
        finally:
            os.unlink(tmp)

    def test_session_split_parsed(self):
        line = "2026-06-03 11:08:00 Session split detected"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(line + "\n")
            tmp = f.name
        try:
            events = list(parse_gateway_log(tmp))
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "session_event"
            assert evt["payload"]["action"] == "session_split"
        finally:
            os.unlink(tmp)

    def test_agent_response_parsed(self):
        line = "2026-06-03 11:08:00 Flushing text batch of 42 chars"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(line + "\n")
            tmp = f.name
        try:
            events = list(parse_gateway_log(tmp))
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "agent_response_sent"
        finally:
            os.unlink(tmp)

    def test_unparseable_lines_skipped_not_crashed(self):
        """Lines that don't match any pattern are skipped without crashing."""
        line = "2026-06-03 11:08:00 Some random log line that means nothing to us"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(line + "\n")
            tmp = f.name
        try:
            events = list(parse_gateway_log(tmp))
            assert len(events) == 0, f"expected 0 events, got {len(events)}"
        finally:
            os.unlink(tmp)

    def test_parsed_events_have_required_fields(self):
        """All gateway-log-parsed events must have the standard fields."""
        lines = (
            "2026-06-03 11:08:00 agent.tool_executor: tool shell completed output_chars=100 duration=0.5 agent:main\n"
            "2026-06-03 11:08:00 agent.conversation_loop: API call tokens_in=1000 tokens_out=100 tokens_total=1100 agent:main\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(lines)
            tmp = f.name
        try:
            events = list(parse_gateway_log(tmp))
            assert len(events) == 2
            for evt in events:
                assert "event_id" in evt
                assert "type" in evt
                assert "source" in evt
                assert "payload" in evt
                assert "timestamp" in evt
                assert "evidence_ref" in evt
                assert "evidence_hash" in evt
                assert "message_summary" in evt
        finally:
            os.unlink(tmp)
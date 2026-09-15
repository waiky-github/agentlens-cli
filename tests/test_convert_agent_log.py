"""Tests for scripts/convert_agent_log.py — Hermes agent.log → JSONL converter."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the converter module
import importlib.util
_convert_path = Path(__file__).resolve().parent.parent / "scripts" / "convert_agent_log.py"
_spec = importlib.util.spec_from_file_location("convert_agent_log", str(_convert_path))
_convert = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_convert)


def _write_temp(content: str, ext: str = ".log") -> str:
    """Write content to a temp file and return path."""
    fd, tmp = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    return tmp


# ── Fixture lines ───────────────────────────────────────────────────

_NEW_MODEL_LINE = (
    "2026-09-14 10:00:00,123 INFO agent.conversation_loop: "
    "API call #5: model=deepseek-v4-flash provider=custom "
    "in=94889 out=529 total=95418 latency=7.2s "
    "cache=8192/94889 (9%)"
)

_NEW_MODEL_LINE_NO_CACHE = (
    "2026-09-14 11:00:00,456 INFO agent.conversation_loop: "
    "API call #10: model=glm-5.2 provider=opencode-go "
    "in=20218 out=5 total=20223 latency=3.1s"
)

_OLD_MODEL_LINE = (
    "2026-09-14 12:00:00,789 INFO agent.conversation_loop: "
    "API call tokens_in=18000 tokens_out=200 tokens_total=18200 agent:main"
)

_NEW_TOOL_LINE = (
    "2026-09-14 10:01:00,100 INFO agent.tool_executor: "
    "tool web_search completed (3.03s, 1564 chars)"
)

_NEW_TOOL_LINE_SMALL = (
    "2026-09-14 10:02:00,200 INFO agent.tool_executor: "
    "tool read_file completed (0.17s, 4113 chars)"
)

_NEW_TOOL_LINE_LARGE = (
    "2026-09-14 10:03:00,300 INFO agent.tool_executor: "
    "tool clarify completed (600.57s, 285 chars)"
)

_OLD_TOOL_LINE = (
    "2026-09-14 10:04:00,400 INFO agent.tool_executor: "
    "tool shell completed output_chars=12345 duration=2.5 agent:main"
)

_SIMPLE_TOOL_LINE = (
    "2026-09-14 10:05:00,500 INFO agent.tool_executor: "
    "tool read completed agent:main"
)

_NON_MATCHING_LINE = (
    "2026-09-14 10:06:00,600 INFO run_agent: "
    "OpenAI client created (chat_completion_stream_request, shared=False)"
)

_NO_TS_LINE = (
    "some random text without timestamp"
)

_GATEWAY_STYLE_LINE = (
    "2026-09-14 10:07:00,700 INFO gateway.run: "
    "inbound message: platform=feishu chat=oc_xxx msg='hello'"
)


class TestConvertAgentLogModelCall:
    """Model call parsing — new and old formats."""

    def test_new_format_model_call(self):
        tmp = _write_temp(_NEW_MODEL_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "model_call"
            p = evt["payload"]
            assert p["model"] == "deepseek-v4-flash"
            assert p["provider"] == "custom"
            assert p["tokens_in"] == 94889
            assert p["tokens_out"] == 529
            assert p["tokens_total"] == 95418
            assert p["latency_s"] == 7.2
            assert p["cache_hit"] == 8192
            assert p["cache_total"] == 94889
        finally:
            os.unlink(tmp)

    def test_new_format_no_cache(self):
        tmp = _write_temp(_NEW_MODEL_LINE_NO_CACHE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "model_call"
            p = evt["payload"]
            assert p["model"] == "glm-5.2"
            assert p["provider"] == "opencode-go"
            assert p["tokens_in"] == 20218
            assert p["tokens_out"] == 5
            assert p["tokens_total"] == 20223
            assert p["latency_s"] == 3.1
            assert "cache_hit" not in p
        finally:
            os.unlink(tmp)

    def test_old_format_model_call(self):
        tmp = _write_temp(_OLD_MODEL_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "model_call"
            p = evt["payload"]
            assert p["model"] == "unknown"
            assert p["provider"] == "unknown"
            assert p["tokens_in"] == 18000
            assert p["tokens_out"] == 200
            assert p["tokens_total"] == 18200
        finally:
            os.unlink(tmp)


class TestConvertAgentLogToolInvocation:
    """Tool invocation parsing — new and old formats."""

    def test_new_format_tool_with_chars(self):
        tmp = _write_temp(_NEW_TOOL_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "tool_invocation"
            p = evt["payload"]
            assert p["tool"] == "web_search"
            assert p["output_chars"] == 1564
            assert p["duration_s"] == 3.03
        finally:
            os.unlink(tmp)

    def test_new_format_tool_large_duration(self):
        tmp = _write_temp(_NEW_TOOL_LINE_LARGE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 1
            evt = events[0]
            p = evt["payload"]
            assert p["tool"] == "clarify"
            assert p["output_chars"] == 285
            assert p["duration_s"] == 600.57
        finally:
            os.unlink(tmp)

    def test_old_format_tool(self):
        tmp = _write_temp(_OLD_TOOL_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "tool_invocation"
            p = evt["payload"]
            assert p["tool"] == "shell"
            assert p["output_chars"] == 12345
            assert p["duration_s"] == 2.5
        finally:
            os.unlink(tmp)

    def test_simple_tool_no_metrics(self):
        tmp = _write_temp(_SIMPLE_TOOL_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 1
            evt = events[0]
            assert evt["type"] == "tool_invocation"
            p = evt["payload"]
            assert p["tool"] == "read"
            assert "output_chars" not in p
            assert "duration_s" not in p
        finally:
            os.unlink(tmp)


class TestConvertAgentLogGeneral:
    """General converter behavior."""

    def test_non_matching_lines_skipped(self):
        tmp = _write_temp(_NON_MATCHING_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 0
        finally:
            os.unlink(tmp)

    def test_no_timestamp_skipped(self):
        tmp = _write_temp(_NO_TS_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 0
        finally:
            os.unlink(tmp)

    def test_gateway_style_line_skipped(self):
        """Gateway.log style lines without model_call/tool should be skipped."""
        tmp = _write_temp(_GATEWAY_STYLE_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            assert len(events) == 0
        finally:
            os.unlink(tmp)

    def test_evidence_ref_present_and_valid(self):
        lines = (
            _NEW_MODEL_LINE + "\n"
            + _NEW_TOOL_LINE + "\n"
            + _OLD_MODEL_LINE + "\n"
        )
        tmp = _write_temp(lines)
        try:
            events = _convert.convert(tmp)
            assert len(events) == 3
            for evt in events:
                ref = evt.get("evidence_ref", "")
                assert ref, f"evidence_ref missing in {evt['event_id']}"
                assert ":" in ref, f"evidence_ref missing ':' separator: {ref}"
                # evidence_ref format: /path/to/file:line_no
                parts = ref.rsplit(":", 1)
                assert len(parts) == 2, f"evidence_ref format invalid: {ref}"
                assert parts[0] == tmp, f"evidence_ref path mismatch: {ref}"
                assert parts[1].isdigit(), f"evidence_ref line_no not numeric: {ref}"
        finally:
            os.unlink(tmp)

    def test_evidence_ref_line_no_correct(self):
        """Verify evidence_ref points to the correct line number."""
        lines = (
            "2026-09-14 10:00:00,000 INFO something ignored\n"
            + _NEW_MODEL_LINE + "\n"
            + "2026-09-14 10:02:00,000 INFO something else ignored\n"
            + _NEW_TOOL_LINE + "\n"
        )
        tmp = _write_temp(lines)
        try:
            events = _convert.convert(tmp)
            assert len(events) == 2
            assert events[0]["evidence_ref"].endswith(":2")  # model on line 2
            assert events[1]["evidence_ref"].endswith(":4")  # tool on line 4
        finally:
            os.unlink(tmp)

    def test_event_id_format(self):
        tmp = _write_temp(_NEW_MODEL_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            evt = events[0]
            assert evt["event_id"] == "agent-evt-0001"
        finally:
            os.unlink(tmp)

    def test_timestamp_iso_utc(self):
        tmp = _write_temp(_NEW_MODEL_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            evt = events[0]
            ts = evt["timestamp"]
            assert "T" in ts
            assert "+00:00" in ts or ts.endswith("Z")
        finally:
            os.unlink(tmp)

    def test_source_field(self):
        tmp = _write_temp(_NEW_TOOL_LINE + "\n")
        try:
            events = _convert.convert(tmp)
            evt = events[0]
            # 2026-09-15 起 source 用语义化标识 hermes:agent:log（避免影子检测
            # 把裸文件名误判为未注册智能体），不再是文件路径。
            assert evt["source"] == "hermes:agent:log"
        finally:
            os.unlink(tmp)

    def test_days_filter(self):
        """--days filter skips old events."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        old_dt = (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        old_line = (
            f"{old_dt},000 INFO agent.tool_executor: "
            "tool old_tool completed (1.0s, 100 chars)"
        )
        new_dt = now.strftime("%Y-%m-%d %H:%M:%S")
        new_line = (
            f"{new_dt},000 INFO agent.conversation_loop: "
            "API call #1: model=m1 provider=p1 in=100 out=10 total=110"
        )
        tmp = _write_temp(old_line + "\n" + new_line + "\n")
        try:
            events = _convert.convert(tmp, days=2)
            assert len(events) == 1, f"expected 1 recent event, got {len(events)}"
            assert events[0]["type"] == "model_call"
        finally:
            os.unlink(tmp)

    def test_multiple_events_sequential_ids(self):
        lines = (
            _NEW_MODEL_LINE + "\n"
            + _NEW_TOOL_LINE + "\n"
            + _NEW_MODEL_LINE_NO_CACHE + "\n"
        )
        tmp = _write_temp(lines)
        try:
            events = _convert.convert(tmp)
            assert len(events) == 3
            assert events[0]["event_id"] == "agent-evt-0001"
            assert events[1]["event_id"] == "agent-evt-0002"
            assert events[2]["event_id"] == "agent-evt-0003"
        finally:
            os.unlink(tmp)

    def test_required_fields_on_all_events(self):
        lines = (
            _NEW_MODEL_LINE + "\n"
            + _NEW_TOOL_LINE + "\n"
            + _OLD_TOOL_LINE + "\n"
        )
        tmp = _write_temp(lines)
        try:
            events = _convert.convert(tmp)
            for evt in events:
                assert "event_id" in evt
                assert "type" in evt
                assert "timestamp" in evt
                assert "source" in evt
                assert "payload" in evt
                assert "evidence_ref" in evt
        finally:
            os.unlink(tmp)
"""Event parser for JSONL event streams and Hermes gateway.log text."""

import json
import re
import sys
from typing import Iterator


def parse_jsonl(path: str) -> Iterator[dict]:
    """Parse a JSONL file, yielding each parsed event dict. Skips blank lines."""
    skipped = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError:
                skipped += 1
    if skipped:
        print(f"[gateway.log parser] skipped {skipped} unparseable lines", flush=True, file=sys.stderr)


# Patterns for Hermes gateway.log lines
_RE_TOOL = re.compile(
    r".*agent\.tool_executor:\s+tool\s+(\S+)\s+completed.*"
    r"output_chars[=:\s]*(\d+).*"
    r"duration[=:\s]*([\d.]+)",
    re.IGNORECASE,
)

_RE_TOOL_SIMPLE = re.compile(
    r".*agent\.tool_executor:\s+tool\s+(\S+)\s+completed.*",
    re.IGNORECASE,
)

_RE_MODEL = re.compile(
    r".*agent\.conversation_loop:\s+API call.*"
    r"tokens_in[=:\s]*(\d+).*"
    r"tokens_out[=:\s]*(\d+).*"
    r"tokens_total[=:\s]*(\d+).*",
    re.IGNORECASE,
)

_RE_USER_MSG = re.compile(
    r".*Inbound dm message received.*",
    re.IGNORECASE,
)

_RE_SESSION = re.compile(
    r".*Session split detected.*",
    re.IGNORECASE,
)

_RE_AGENT_RESP = re.compile(
    r".*Flushing text batch.*",
    re.IGNORECASE,
)


def _extract_agent_from_line(line: str) -> str:
    """Try to extract agent name from a log line."""
    m = re.search(r"agent[:=]\s*(\S+)", line)
    if m:
        return m.group(1)
    return "agent:main"


def parse_gateway_log(path: str) -> Iterator[dict]:
    """Best-effort parse of Hermes gateway.log text into events."""
    skipped = 0
    event_id = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue

            event_id += 1
            evt = None

            # Tool invocation
            m = _RE_TOOL.search(stripped)
            if m:
                evt = {
                    "event_id": f"parsed-evt-{event_id:05d}",
                    "type": "tool_invocation",
                    "source": "hermes:agent:log",
                    "payload": {
                        "agent": _extract_agent_from_line(stripped),
                        "tool": m.group(1),
                        "output_chars": int(m.group(2)),
                        "duration_seconds": float(m.group(3)),
                    },
                }
            else:
                # Try simpler tool pattern
                m2 = _RE_TOOL_SIMPLE.search(stripped)
                if m2:
                    evt = {
                        "event_id": f"parsed-evt-{event_id:05d}",
                        "type": "tool_invocation",
                        "source": "hermes:agent:log",
                        "payload": {
                            "agent": _extract_agent_from_line(stripped),
                            "tool": m2.group(1),
                        },
                    }

            # Model call
            if evt is None:
                m = _RE_MODEL.search(stripped)
                if m:
                    evt = {
                        "event_id": f"parsed-evt-{event_id:05d}",
                        "type": "model_call",
                        "source": "hermes:agent:log",
                        "payload": {
                            "agent": _extract_agent_from_line(stripped),
                            "model": "unknown",
                            "provider": "unknown",
                            "tokens_in": int(m.group(1)),
                            "tokens_out": int(m.group(2)),
                            "tokens_total": int(m.group(3)),
                        },
                    }

            # User message
            if evt is None:
                if _RE_USER_MSG.search(stripped):
                    evt = {
                        "event_id": f"parsed-evt-{event_id:05d}",
                        "type": "user_message_arrived",
                        "source": "hermes:gateway:log",
                        "payload": {},
                    }

            # Session event
            if evt is None:
                if _RE_SESSION.search(stripped):
                    evt = {
                        "event_id": f"parsed-evt-{event_id:05d}",
                        "type": "session_event",
                        "source": "hermes:gateway:log",
                        "payload": {"action": "session_split"},
                    }

            # Agent response
            if evt is None:
                if _RE_AGENT_RESP.search(stripped):
                    evt = {
                        "event_id": f"parsed-evt-{event_id:05d}",
                        "type": "agent_response_sent",
                        "source": "hermes:gateway:log",
                        "payload": {},
                    }

            if evt is None:
                skipped += 1
                continue

            evt["timestamp"] = None
            evt["evidence_ref"] = f"hermes:log:gateway.log:{line_no}"
            evt["evidence_hash"] = None
            evt["message_summary"] = None
            yield evt

    if skipped:
        print(
            f"[gateway.log parser] skipped {skipped} unparseable lines",
            flush=True,
            file=sys.stderr,
        )
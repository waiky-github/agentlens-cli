#!/usr/bin/env python3
"""
AutoGen log converter: converts AutoGen conversation/execution logs into agentlens-cli unified event stream JSONL.

Input format based on AutoGen public documentation (https://microsoft.github.io/autogen/):
  - AutoGen agents communicate via structured message dictionaries with fields:
      role, content, name, function_call, tool_calls.
  - Log lines are JSON objects, one per line:
      {"timestamp": "...", "type": "message", "source": "agent_name", "content": "...", "role": "assistant", "model": "gpt-4o", "tokens_in": ..., "tokens_out": ...}
      {"timestamp": "...", "type": "tool_call", "source": "agent_name", "tool": "web_search", "arguments": {...}, "output": "..."}
      {"timestamp": "...", "type": "approval", "source": "user_proxy", "action": "approved", "message": "..."}
      {"timestamp": "...", "type": "handoff", "source": "agent_a", "target": "agent_b"}
  - Unmatched lines are skipped with a stderr warning.

Usage:
    python converters/autogen_converter.py <input_log> <output_events.jsonl>
"""

import sys
import json
import os
from datetime import datetime, timezone
from typing import Optional


def _normalize_timestamp(ts_str: str) -> str:
    """Normalize timestamp to ISO-8601 with Z suffix."""
    ts_str = str(ts_str).strip()
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        return ts_str


def _make_event(
    event_id: str,
    etype: str,
    source: str,
    payload: dict,
    timestamp: str,
    evidence_ref: str,
    message_summary: Optional[str] = None,
) -> dict:
    return {
        "event_id": event_id,
        "type": etype,
        "timestamp": _normalize_timestamp(timestamp),
        "source": source,
        "payload": payload,
        "evidence_ref": evidence_ref,
        "evidence_hash": None,
        "message_summary": message_summary,
    }


def convert(input_path: str, output_path: str) -> int:
    """Convert an AutoGen conversation log to unified event stream JSONL.

    Returns the number of events written.
    """
    skipped = 0
    event_count = 0
    events = []

    with open(input_path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue

            # Parse as JSON
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                skipped += 1
                continue

            if not isinstance(obj, dict):
                skipped += 1
                continue

            evidence_ref = f"autogen:log:{os.path.basename(input_path)}:{line_no}"
            ts = obj.get("timestamp", "1970-01-01T00:00:00Z")
            log_type = obj.get("type", "")
            source_agent = obj.get("source", obj.get("name", "autogen:agent"))

            # ── message (assistant/user) → model_call or action_executed ──
            if log_type == "message":
                role = obj.get("role", "")
                content = obj.get("content", "")
                model = obj.get("model", "unknown")
                tokens_in = obj.get("tokens_in", 0)
                tokens_out = obj.get("tokens_out", 0)

                if role == "assistant" and (tokens_in > 0 or tokens_out > 0):
                    event_count += 1
                    evt = _make_event(
                        event_id=f"autogen-evt-{event_count:05d}",
                        etype="model_call",
                        source=f"autogen:agent:{source_agent}",
                        payload={
                            "agent": source_agent,
                            "model": model,
                            "provider": "openai",
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "tokens_total": tokens_in + tokens_out,
                        },
                        timestamp=ts,
                        evidence_ref=evidence_ref,
                        message_summary=f"model call by {source_agent}: {content[:100]}" if content else f"model call by {source_agent}",
                    )
                    events.append(evt)
                elif role == "assistant":
                    event_count += 1
                    evt = _make_event(
                        event_id=f"autogen-evt-{event_count:05d}",
                        etype="action_executed",
                        source=f"autogen:agent:{source_agent}",
                        payload={
                            "from": source_agent,
                            "action": "generate_response",
                            "content": content[:500] if content else "",
                        },
                        timestamp=ts,
                        evidence_ref=evidence_ref,
                        message_summary=f"assistant response: {source_agent}",
                    )
                    events.append(evt)
                elif role == "user":
                    event_count += 1
                    evt = _make_event(
                        event_id=f"autogen-evt-{event_count:05d}",
                        etype="user_message_arrived",
                        source=f"autogen:agent:{source_agent}",
                        payload={
                            "from": source_agent,
                            "content": content[:500] if content else "",
                        },
                        timestamp=ts,
                        evidence_ref=evidence_ref,
                        message_summary=f"user message from {source_agent}",
                    )
                    events.append(evt)
                else:
                    skipped += 1
                continue

            # ── tool_call → tool_invocation ──
            if log_type == "tool_call":
                event_count += 1
                tool_name = obj.get("tool", "unknown")
                output = obj.get("output", "")
                output_chars = len(output) if output else 0
                evt = _make_event(
                    event_id=f"autogen-evt-{event_count:05d}",
                    etype="tool_invocation",
                    source=f"autogen:agent:{source_agent}",
                    payload={
                        "agent": source_agent,
                        "tool": tool_name,
                        "output_chars": output_chars,
                        "arguments": obj.get("arguments", {}),
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"tool call: {tool_name} by {source_agent} ({output_chars} chars)",
                )
                events.append(evt)
                continue

            # ── approval → approval ──
            if log_type == "approval":
                event_count += 1
                action = obj.get("action", "approved")
                evt = _make_event(
                    event_id=f"autogen-evt-{event_count:05d}",
                    etype="approval",
                    source=f"autogen:agent:{source_agent}",
                    payload={
                        "from": source_agent,
                        "to": obj.get("target", "autogen:agent"),
                        "action": action,
                        "status": action,
                        "message": obj.get("message", ""),
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"approval: {action} by {source_agent}",
                )
                events.append(evt)
                continue

            # ── handoff → task_dispatch ──
            if log_type == "handoff":
                event_count += 1
                target = obj.get("target", "autogen:agent")
                evt = _make_event(
                    event_id=f"autogen-evt-{event_count:05d}",
                    etype="task_dispatch",
                    source=f"autogen:agent:{source_agent}",
                    payload={
                        "from": source_agent,
                        "to": target,
                        "task": obj.get("task", "handoff from " + source_agent),
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"handoff: {source_agent} -> {target}",
                )
                events.append(evt)
                continue

            # ── task_completion → task_completion ──
            if log_type == "task_completion":
                event_count += 1
                evt = _make_event(
                    event_id=f"autogen-evt-{event_count:05d}",
                    etype="task_completion",
                    source=f"autogen:agent:{source_agent}",
                    payload={
                        "from": source_agent,
                        "to": obj.get("target", "autogen:orchestrator"),
                        "task": obj.get("task", "unknown"),
                        "status": "completed",
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"task completed by {source_agent}",
                )
                events.append(evt)
                continue

            # ── Unknown type ──
            skipped += 1

    if skipped:
        print(
            f"[autogen_converter] skipped {skipped} unparseable lines",
            flush=True,
            file=sys.stderr,
        )

    with open(output_path, "w", encoding="utf-8") as fh:
        for evt in events:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")

    print(f"[autogen_converter] wrote {len(events)} events to {output_path}", file=sys.stderr)
    return len(events)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <input_log> <output_events.jsonl>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.isfile(input_path):
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    count = convert(input_path, output_path)
    if count == 0:
        print("Warning: no events produced from input", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
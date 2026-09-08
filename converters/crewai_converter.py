#!/usr/bin/env python3
"""
CrewAI log converter: converts CrewAI execution logs/traces into agentlens-cli unified event stream JSONL.

Input format based on CrewAI public documentation (https://docs.crewai.com/):
  - CrewAI structured execution logs with agent/task/tool/LLM markers.
  - Log lines typically include:
      [TIMESTAMP] [AGENT] ... (agent start/thought)
      [TIMESTAMP] [TASK] START: <task_name>  (task dispatch)
      [TIMESTAMP] [TASK] COMPLETE: <task_name>  (task completion)
      [TIMESTAMP] [TOOL] <tool_name> -> <output_chars> chars  (tool invocation)
      [TIMESTAMP] [LLM] tokens_in=<N> tokens_out=<N>  (model call)
  - Unmatched lines are skipped with a stderr warning.

Usage:
    python converters/crewai_converter.py <input_log> <output_events.jsonl>
"""

import sys
import re
import json
import os
from datetime import datetime, timezone
from typing import Optional


# ── Regex patterns for CrewAI structured log lines ──────────────────────────

# [2026-09-08 10:00:01] [TASK] START: research_competitor_pricing
_RE_TASK_START = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s*\[TASK\]\s*START:\s*(?P<task>.+)",
    re.IGNORECASE,
)

# [2026-09-08 10:05:30] [TASK] COMPLETE: research_competitor_pricing
_RE_TASK_COMPLETE = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s*\[TASK\]\s*COMPLETE:\s*(?P<task>.+)",
    re.IGNORECASE,
)

# [2026-09-08 10:02:15] [TOOL] web_search -> 4521 chars
_RE_TOOL = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s*\[TOOL\]\s*(?P<tool>\S+)\s*->\s*(?P<chars>\d+)\s*chars",
    re.IGNORECASE,
)

# [2026-09-08 10:01:00] [LLM] tokens_in=1200 tokens_out=350 model=gpt-4o
_RE_LLM = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s*\[LLM\]\s*"
    r"tokens_in=(?P<tokens_in>\d+)\s+"
    r"tokens_out=(?P<tokens_out>\d+)\s+"
    r"(?:model=(?P<model>\S+))?",
    re.IGNORECASE,
)

# [2026-09-08 10:00:00] [AGENT] market_researcher: executing task
_RE_AGENT_START = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s*\[AGENT\]\s*(?P<agent>[^:]+):\s*(?P<action>.+)",
    re.IGNORECASE,
)

# [2026-09-08 10:05:00] [AGENT] market_researcher: thought=I should search for pricing data
_RE_AGENT_THOUGHT = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s*\[AGENT\]\s*(?P<agent>[^:]+):\s*thought=(?P<thought>.+)",
    re.IGNORECASE,
)


def _normalize_timestamp(ts_str: str) -> str:
    """Normalize timestamp to ISO-8601 with Z suffix."""
    ts_str = ts_str.strip()
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
    """Convert a CrewAI execution log to unified event stream JSONL.

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

            evt = None
            evidence_ref = f"crewai:log:{os.path.basename(input_path)}:{line_no}"

            # ── TASK START → task_dispatch ──
            m = _RE_TASK_START.match(stripped)
            if m:
                event_count += 1
                evt = _make_event(
                    event_id=f"crewai-evt-{event_count:05d}",
                    etype="task_dispatch",
                    source="crewai:execution:log",
                    payload={
                        "from": "crewai:orchestrator",
                        "to": "crewai:agent",
                        "task": m.group("task"),
                    },
                    timestamp=m.group("ts"),
                    evidence_ref=evidence_ref,
                    message_summary=f"task dispatched: {m.group('task')}",
                )

            # ── TASK COMPLETE → task_completion ──
            if evt is None:
                m = _RE_TASK_COMPLETE.match(stripped)
                if m:
                    event_count += 1
                    evt = _make_event(
                        event_id=f"crewai-evt-{event_count:05d}",
                        etype="task_completion",
                        source="crewai:execution:log",
                        payload={
                            "from": "crewai:agent",
                            "to": "crewai:orchestrator",
                            "task": m.group("task"),
                            "status": "completed",
                        },
                        timestamp=m.group("ts"),
                        evidence_ref=evidence_ref,
                        message_summary=f"task completed: {m.group('task')}",
                    )

            # ── TOOL → tool_invocation ──
            if evt is None:
                m = _RE_TOOL.match(stripped)
                if m:
                    event_count += 1
                    evt = _make_event(
                        event_id=f"crewai-evt-{event_count:05d}",
                        etype="tool_invocation",
                        source="crewai:execution:log",
                        payload={
                            "agent": "crewai:agent",
                            "tool": m.group("tool"),
                            "output_chars": int(m.group("chars")),
                        },
                        timestamp=m.group("ts"),
                        evidence_ref=evidence_ref,
                        message_summary=f"tool call: {m.group('tool')} ({m.group('chars')} chars)",
                    )

            # ── LLM → model_call ──
            if evt is None:
                m = _RE_LLM.match(stripped)
                if m:
                    event_count += 1
                    evt = _make_event(
                        event_id=f"crewai-evt-{event_count:05d}",
                        etype="model_call",
                        source="crewai:execution:log",
                        payload={
                            "agent": "crewai:agent",
                            "model": m.group("model") or "unknown",
                            "provider": "openai",
                            "tokens_in": int(m.group("tokens_in")),
                            "tokens_out": int(m.group("tokens_out")),
                            "tokens_total": int(m.group("tokens_in")) + int(m.group("tokens_out")),
                        },
                        timestamp=m.group("ts"),
                        evidence_ref=evidence_ref,
                        message_summary=f"model call: {m.group('tokens_in')}+{m.group('tokens_out')} tokens",
                    )

            # ── AGENT thought → action_executed (observation) ──
            if evt is None:
                m = _RE_AGENT_THOUGHT.match(stripped)
                if m:
                    event_count += 1
                    evt = _make_event(
                        event_id=f"crewai-evt-{event_count:05d}",
                        etype="action_executed",
                        source="crewai:execution:log",
                        payload={
                            "from": m.group("agent"),
                            "action": "agent_thought",
                            "thought": m.group("thought"),
                        },
                        timestamp=m.group("ts"),
                        evidence_ref=evidence_ref,
                        message_summary=f"agent thought: {m.group('agent')}",
                    )

            if evt is None:
                skipped += 1
            else:
                events.append(evt)

    if skipped:
        print(
            f"[crewai_converter] skipped {skipped} unparseable lines",
            flush=True,
            file=sys.stderr,
        )

    # Write output
    with open(output_path, "w", encoding="utf-8") as fh:
        for evt in events:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")

    print(f"[crewai_converter] wrote {len(events)} events to {output_path}", file=sys.stderr)
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
#!/usr/bin/env python3
"""
LangGraph log converter: converts LangGraph execution traces into agentlens-cli unified event stream JSONL.

Input format based on LangGraph public documentation (https://langchain-ai.github.io/langgraph/):
  - LangGraph execution traces log state transitions, node executions, and tool/LLM calls.
  - Log lines are JSON objects with fields:
      {"timestamp": "...", "type": "node_start", "node": "agent", "state_keys": [...], "input": {...}}
      {"timestamp": "...", "type": "node_end", "node": "agent", "output": {...}, "duration_ms": 1234}
      {"timestamp": "...", "type": "llm_call", "model": "gpt-4o", "tokens_in": 500, "tokens_out": 200, "node": "agent"}
      {"timestamp": "...", "type": "tool_call", "tool": "web_search", "input": {...}, "output": "...", "node": "tools"}
      {"timestamp": "...", "type": "state_update", "node": "agent", "key": "messages", "changes": "..."}
      {"timestamp": "...", "type": "edge_traverse", "from": "agent", "to": "tools", "condition": "..."}
      {"timestamp": "...", "type": "graph_start", "graph": "my_agent", "input": {...}}
      {"timestamp": "...", "type": "graph_end", "graph": "my_agent", "output": {...}}
  - Unmatched lines are skipped with a stderr warning.

Usage:
    python converters/langgraph_converter.py <input_log> <output_events.jsonl>
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
    """Convert a LangGraph execution trace to unified event stream JSONL.

    Returns the number of events written.
    """
    skipped = 0
    event_count = 0
    events = []

    # Track graph state for context
    current_node = "unknown"
    current_graph = "unknown"

    with open(input_path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                skipped += 1
                continue

            if not isinstance(obj, dict):
                skipped += 1
                continue

            evidence_ref = f"langgraph:trace:{os.path.basename(input_path)}:{line_no}"
            ts = obj.get("timestamp", "1970-01-01T00:00:00Z")
            log_type = obj.get("type", "")

            # ── graph_start → task_dispatch ──
            if log_type == "graph_start":
                current_graph = obj.get("graph", "unknown")
                event_count += 1
                evt = _make_event(
                    event_id=f"lg-evt-{event_count:05d}",
                    etype="task_dispatch",
                    source=f"langgraph:graph:{current_graph}",
                    payload={
                        "from": "langgraph:orchestrator",
                        "to": f"langgraph:graph:{current_graph}",
                        "task": f"execute graph: {current_graph}",
                        "input": obj.get("input", {}),
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"graph execution started: {current_graph}",
                )
                events.append(evt)
                continue

            # ── graph_end → task_completion ──
            if log_type == "graph_end":
                event_count += 1
                evt = _make_event(
                    event_id=f"lg-evt-{event_count:05d}",
                    etype="task_completion",
                    source=f"langgraph:graph:{current_graph}",
                    payload={
                        "from": f"langgraph:graph:{current_graph}",
                        "to": "langgraph:orchestrator",
                        "task": f"execute graph: {current_graph}",
                        "status": "completed",
                        "output": obj.get("output", {}),
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"graph execution completed: {current_graph}",
                )
                events.append(evt)
                continue

            # ── node_start → action_executed ──
            if log_type == "node_start":
                current_node = obj.get("node", "unknown")
                event_count += 1
                evt = _make_event(
                    event_id=f"lg-evt-{event_count:05d}",
                    etype="action_executed",
                    source=f"langgraph:node:{current_node}",
                    payload={
                        "from": f"langgraph:node:{current_node}",
                        "action": "node_start",
                        "node": current_node,
                        "graph": current_graph,
                        "state_keys": obj.get("state_keys", []),
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"node started: {current_node} in {current_graph}",
                )
                events.append(evt)
                continue

            # ── node_end → action_executed ──
            if log_type == "node_end":
                duration_ms = obj.get("duration_ms", 0)
                event_count += 1
                evt = _make_event(
                    event_id=f"lg-evt-{event_count:05d}",
                    etype="action_executed",
                    source=f"langgraph:node:{current_node}",
                    payload={
                        "from": f"langgraph:node:{current_node}",
                        "action": "node_end",
                        "node": obj.get("node", current_node),
                        "graph": current_graph,
                        "duration_ms": duration_ms,
                        "output": obj.get("output", {}),
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"node completed: {current_node} ({duration_ms}ms)",
                )
                events.append(evt)
                continue

            # ── llm_call → model_call ──
            if log_type == "llm_call":
                event_count += 1
                node = obj.get("node", current_node)
                model = obj.get("model", "unknown")
                tokens_in = obj.get("tokens_in", 0)
                tokens_out = obj.get("tokens_out", 0)
                evt = _make_event(
                    event_id=f"lg-evt-{event_count:05d}",
                    etype="model_call",
                    source=f"langgraph:node:{node}",
                    payload={
                        "agent": f"langgraph:node:{node}",
                        "model": model,
                        "provider": "openai",
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "tokens_total": tokens_in + tokens_out,
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"LLM call in {node}: {model} {tokens_in}+{tokens_out} tokens",
                )
                events.append(evt)
                continue

            # ── tool_call → tool_invocation ──
            if log_type == "tool_call":
                event_count += 1
                node = obj.get("node", current_node)
                tool_name = obj.get("tool", "unknown")
                output = obj.get("output", "")
                output_chars = len(output) if isinstance(output, str) else len(json.dumps(output))
                evt = _make_event(
                    event_id=f"lg-evt-{event_count:05d}",
                    etype="tool_invocation",
                    source=f"langgraph:node:{node}",
                    payload={
                        "agent": f"langgraph:node:{node}",
                        "tool": tool_name,
                        "output_chars": output_chars,
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"tool call in {node}: {tool_name} ({output_chars} chars)",
                )
                events.append(evt)
                continue

            # ── edge_traverse → action_executed (state transition) ──
            if log_type == "edge_traverse":
                event_count += 1
                evt = _make_event(
                    event_id=f"lg-evt-{event_count:05d}",
                    etype="action_executed",
                    source=f"langgraph:graph:{current_graph}",
                    payload={
                        "from": obj.get("from", "unknown"),
                        "action": "edge_traverse",
                        "to": obj.get("to", "unknown"),
                        "condition": obj.get("condition", ""),
                        "graph": current_graph,
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"edge traverse: {obj.get('from', '?')} -> {obj.get('to', '?')}",
                )
                events.append(evt)
                continue

            # ── state_update → action_executed ──
            if log_type == "state_update":
                event_count += 1
                node = obj.get("node", current_node)
                evt = _make_event(
                    event_id=f"lg-evt-{event_count:05d}",
                    etype="action_executed",
                    source=f"langgraph:node:{node}",
                    payload={
                        "from": f"langgraph:node:{node}",
                        "action": "state_update",
                        "node": node,
                        "key": obj.get("key", "unknown"),
                        "graph": current_graph,
                    },
                    timestamp=ts,
                    evidence_ref=evidence_ref,
                    message_summary=f"state update: {node} changed {obj.get('key', '?')}",
                )
                events.append(evt)
                continue

            # ── Unknown type ──
            skipped += 1

    if skipped:
        print(
            f"[langgraph_converter] skipped {skipped} unparseable lines",
            flush=True,
            file=sys.stderr,
        )

    with open(output_path, "w", encoding="utf-8") as fh:
        for evt in events:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")

    print(f"[langgraph_converter] wrote {len(events)} events to {output_path}", file=sys.stderr)
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
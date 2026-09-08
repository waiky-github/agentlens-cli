"""Waste detection: detect, quantify, and recommend fixes for token waste."""

from collections import defaultdict
from datetime import datetime, timezone

from .config import CostModel, DEFAULT_COST_MODEL


# Thresholds from cost-governance SKILL.md
LARGE_OUTPUT_THRESHOLD = 10_000  # chars: output_chars > this = large injection
CHARS_PER_TOKEN_ESTIMATE = 4  # rough estimate: ~4 chars per token


def detect_waste(events: list[dict], cost_model: CostModel = None) -> dict:
    """Detect waste in events based on cost-governance SKILL.md rules."""
    if cost_model is None:
        cost_model = DEFAULT_COST_MODEL

    sorted_events = sorted(events, key=lambda e: e.get("timestamp", ""))
    findings = []

    # Build an ordered list of model_call / tool_invocation events
    tool_and_model = []
    for evt in sorted_events:
        if evt.get("type") in ("tool_invocation", "model_call"):
            tool_and_model.append(evt)

    # ============================================================
    # Detection 1: Large-output tool injection
    # ============================================================
    for i, evt in enumerate(tool_and_model):
        if evt.get("type") != "tool_invocation":
            continue
        payload = evt.get("payload", {}) or {}
        output_chars = payload.get("output_chars")
        if not output_chars or output_chars <= LARGE_OUTPUT_THRESHOLD:
            continue

        tool_name = payload.get("tool", "unknown")

        # Find the model_call right before this tool
        prev_model = None
        for j in range(i - 1, -1, -1):
            if tool_and_model[j].get("type") == "model_call":
                prev_model = tool_and_model[j]
                break

        # Find the model_call right after this tool
        next_model = None
        for j in range(i + 1, len(tool_and_model)):
            if tool_and_model[j].get("type") == "model_call":
                next_model = tool_and_model[j]
                break

        if next_model is None:
            continue

        next_tokens_in = next_model.get("payload", {}).get("tokens_in", 0) or 0
        prev_tokens_in = (
            prev_model.get("payload", {}).get("tokens_in", 0) or 0
            if prev_model
            else 0
        )

        if prev_model:
            extra_tokens_in = max(0, next_tokens_in - prev_tokens_in)
            token_estimate = max(1, output_chars // CHARS_PER_TOKEN_ESTIMATE)
            extra_tokens_in = min(extra_tokens_in, token_estimate)
        else:
            extra_tokens_in = max(1, output_chars // CHARS_PER_TOKEN_ESTIMATE)

        if extra_tokens_in <= 0:
            continue

        est_wasted_cost = cost_model.input_cost(extra_tokens_in)

        severity = "medium"
        if (
            prev_model
            and prev_tokens_in > 0
            and extra_tokens_in / prev_tokens_in > 0.10
        ):
            severity = "high"
        elif output_chars > 50_000:
            severity = "high"

        findings.append({
            "severity": severity,
            "title": "large-output tool injection ungoverned",
            "evidence_refs": [evt.get("event_id"), next_model.get("event_id")],
            "tool": tool_name,
            "injected_chars": output_chars,
            "extra_tokens_in": extra_tokens_in,
            "waste_ratio": round(extra_tokens_in / max(1, next_tokens_in), 4),
            "est_wasted_cost": round(est_wasted_cost, 6),
            "recommendation": (
                f"cap {tool_name} output_chars at 8,000; summarize-on-read"
            ),
            "fix_ref": f"tool-contract: {tool_name} output truncation",
            "recheck_metric": "extra_tokens_in",
        })

    # ============================================================
    # Detection 2: Repeated calls to same high-output tool
    # ============================================================
    tool_call_seqs = defaultdict(list)
    for evt in sorted_events:
        if evt.get("type") != "tool_invocation":
            continue
        payload = evt.get("payload", {}) or {}
        output_chars = payload.get("output_chars", 0) or 0
        if output_chars > 5_000:
            tool_name = payload.get("tool", "unknown")
            tool_call_seqs[tool_name].append(evt)

    for tool_name, calls in tool_call_seqs.items():
        if len(calls) < 2:
            continue
        groups = []
        current_group = [calls[0]]
        for i in range(1, len(calls)):
            try:
                t1 = datetime.fromisoformat(
                    calls[i - 1].get("timestamp", "").replace("Z", "+00:00")
                )
                t2 = datetime.fromisoformat(
                    calls[i].get("timestamp", "").replace("Z", "+00:00")
                )
                if (t2 - t1).total_seconds() < 300:
                    current_group.append(calls[i])
                else:
                    if len(current_group) >= 2:
                        groups.append(current_group)
                    current_group = [calls[i]]
            except (ValueError, TypeError):
                continue
        if len(current_group) >= 2:
            groups.append(current_group)

        for group in groups:
            total_output = sum(
                c.get("payload", {}).get("output_chars", 0) or 0 for c in group
            )
            wasted_chars = total_output - min(
                c.get("payload", {}).get("output_chars", 0) or 0 for c in group
            )
            wasted_tokens = wasted_chars // CHARS_PER_TOKEN_ESTIMATE
            if wasted_tokens <= 0:
                continue
            est_wasted_cost = cost_model.input_cost(wasted_tokens)

            findings.append({
                "severity": "medium",
                "title": f"repeated calls to same high-output tool: {tool_name}",
                "evidence_refs": [c.get("event_id") for c in group],
                "tool": tool_name,
                "call_count": len(group),
                "extra_tokens_in": wasted_tokens,
                "waste_ratio": 0.0,
                "est_wasted_cost": round(est_wasted_cost, 6),
                "recommendation": (
                    f"cache/dedupe {tool_name} output; fetch once, reference the same ref"
                ),
                "fix_ref": f"dedup: {tool_name} calls",
                "recheck_metric": "repeated_calls",
            })

    # ============================================================
    # Detection 3: Session-level context bloat
    #
    # Each session starts with a reasonable context (~18K tokens).
    # As the conversation progresses, tool output accumulates and
    # context grows with no compaction. A session boundary is
    # detected when tokens_in drops > 50% (context reset).
    # The waste is the excess tokens above the session baseline.
    # ============================================================
    all_model_calls = sorted(
        [e for e in tool_and_model if e.get("type") == "model_call"],
        key=lambda e: e.get("timestamp", ""),
    )

    if all_model_calls:
        # Group model calls into sessions by detecting context resets
        sessions = []
        current = [all_model_calls[0]]
        for i in range(1, len(all_model_calls)):
            prev_tokens = (
                all_model_calls[i - 1].get("payload", {}).get("tokens_in", 0) or 0
            )
            curr_tokens = (
                all_model_calls[i].get("payload", {}).get("tokens_in", 0) or 0
            )
            if prev_tokens > 0 and curr_tokens < prev_tokens * 0.5:
                sessions.append(current)
                current = [all_model_calls[i]]
            else:
                current.append(all_model_calls[i])
        if current:
            sessions.append(current)

        for sess in sessions:
            if len(sess) < 3:
                continue
            baseline = sess[0].get("payload", {}).get("tokens_in", 0) or 0
            if baseline <= 0:
                continue

            total_excess = 0
            for mc in sess[1:]:
                tokens_in = mc.get("payload", {}).get("tokens_in", 0) or 0
                excess = max(0, tokens_in - baseline)
                total_excess += excess

            if total_excess > 100_000:
                est_wasted_cost = cost_model.input_cost(total_excess)
                findings.append({
                    "severity": "high",
                    "title": "session-level context bloat: no deliberate compaction",
                    "evidence_refs": [
                        sess[0].get("event_id"),
                        sess[-1].get("event_id"),
                    ],
                    "call_count": len(sess),
                    "extra_tokens_in": total_excess,
                    "waste_ratio": round(
                        total_excess / max(1, sum(
                            mc.get("payload", {}).get("tokens_in", 0) or 0
                            for mc in sess
                        )), 4
                    ),
                    "est_wasted_cost": round(est_wasted_cost, 6),
                    "recommendation": (
                        "compact/reset context deliberately at session boundaries "
                        "instead of silently growing it"
                    ),
                    "fix_ref": "context-compaction: deliberate reset per session",
                    "recheck_metric": "extra_tokens_in",
                })

    # ============================================================
    # Detection 4: Low-value / looping calls (inefficient loops)
    # ============================================================
    for tool_name, calls in tool_call_seqs.items():
        if len(calls) < 5:
            continue
        for i in range(len(calls) - 5):
            window = calls[i:i + 6]
            try:
                t_first = datetime.fromisoformat(
                    window[0].get("timestamp", "").replace("Z", "+00:00")
                )
                t_last = datetime.fromisoformat(
                    window[-1].get("timestamp", "").replace("Z", "+00:00")
                )
                if (t_last - t_first).total_seconds() < 120:
                    total_output = sum(
                        c.get("payload", {}).get("output_chars", 0) or 0
                        for c in window
                    )
                    wasted_tokens = total_output // CHARS_PER_TOKEN_ESTIMATE
                    est_wasted_cost = cost_model.input_cost(wasted_tokens)
                    findings.append({
                        "severity": "medium",
                        "title": f"inefficient loop: rapid repeated calls to {tool_name}",
                        "evidence_refs": [c.get("event_id") for c in window],
                        "tool": tool_name,
                        "call_count": len(window),
                        "extra_tokens_in": wasted_tokens,
                        "waste_ratio": 0.0,
                        "est_wasted_cost": round(est_wasted_cost, 6),
                        "recommendation": (
                            f"batch {tool_name} calls into a single invocation"
                        ),
                        "fix_ref": f"batch: {tool_name} calls",
                        "recheck_metric": "repeated_calls",
                    })
                    break
            except (ValueError, TypeError):
                continue

    # ============================================================
    # Detection 4: Structural observations (LOW)
    # ============================================================
    agents_seen = set()
    for evt in sorted_events:
        payload = evt.get("payload", {}) or {}
        agent = payload.get("agent")
        if agent:
            agents_seen.add(agent)

    if agents_seen:
        findings.append({
            "severity": "low",
            "title": "no per-agent token caps observed",
            "evidence_refs": [],
            "extra_tokens_in": 0,
            "waste_ratio": 0.0,
            "est_wasted_cost": 0.0,
            "recommendation": (
                "set per-agent or per-window token budgets with a breach alert"
            ),
            "fix_ref": "agent-token-budget: per-agent cap",
            "recheck_metric": "tokens_per_agent",
        })

    # ============================================================
    # Detection 5: Cost-model gaps (INFO)
    # ============================================================
    findings.append({
        "severity": "info",
        "title": "cost-model gaps: no unit price in event stream — prices are estimates",
        "evidence_refs": [],
        "extra_tokens_in": 0,
        "waste_ratio": 0.0,
        "est_wasted_cost": 0.0,
        "recommendation": (
            "embed unit prices in event stream for accurate cost attribution"
        ),
        "fix_ref": "cost-model: embed prices",
        "recheck_metric": "price_accuracy",
    })

    # Deduplicate findings by evidence_refs (avoid double-counting)
    seen_refs = set()
    deduped = []
    for f in findings:
        key = tuple(sorted(f.get("evidence_refs", [])))
        if key and key in seen_refs:
            continue
        if key:
            seen_refs.add(key)
        deduped.append(f)

    total_est_wasted_cost = round(sum(f["est_wasted_cost"] for f in deduped), 6)

    return {
        "findings": deduped,
        "total_est_wasted_cost": total_est_wasted_cost,
    }
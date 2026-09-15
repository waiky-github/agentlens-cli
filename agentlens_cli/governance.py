"""Waste detection: detect, quantify, and recommend fixes for token waste."""

from collections import defaultdict
from datetime import datetime, timezone

from .config import CostModel, DEFAULT_COST_MODEL


# Thresholds from cost-governance SKILL.md
LARGE_OUTPUT_THRESHOLD = 10_000  # chars: output_chars > this = large injection
CHARS_PER_TOKEN_ESTIMATE = 4  # rough estimate: ~4 chars per token

# ── 配置漂移 / proximity 常量（2026-09-15 优化） ────────────────────
# 过松判定：compression.threshold > 0.3 或触发线（threshold×context_length）
# > 300k tokens。实证：治理前 creative 0.3 × 1M context = 30 万才触发，
# zine 会话峰值 291,728 差 8,272 未触发 → 全程 0 次压缩、单条 bloat 109 元。
CONFIG_LAX_THRESHOLD = 0.3
DEFAULT_CONTEXT_LENGTH = 1_000_000
DEFAULT_TRIGGER_LINE_TOKENS = int(CONFIG_LAX_THRESHOLD * DEFAULT_CONTEXT_LENGTH)  # 300k
# 临界会话：峰值 ≥ 触发线 × 0.8 且未压缩 → info 预警（临界风险提前暴露）
NEAR_LINE_RATIO = 0.8


def detect_waste(events: list[dict], cost_model: CostModel = None) -> dict:
    """Detect waste in events based on cost-governance SKILL.md rules."""
    if cost_model is None:
        cost_model = DEFAULT_COST_MODEL

    sorted_events = sorted(events, key=lambda e: e.get("timestamp") or "")
    findings = []

    # ── 配置快照（config_snapshot 事件，converter 注入） ───────────────
    # 供两个用途：① 配置漂移检测（threshold 不一致/过松）；② bloat
    # proximity——压缩触发线 = threshold×context_length（多 scope 取最严格）。
    snapshots = [e for e in sorted_events if e.get("type") == "config_snapshot"]
    per_scope: dict[str, dict] = {}
    for e in snapshots:
        p = e.get("payload", {}) or {}
        scope = str(p.get("scope") or p.get("agent") or "unknown")
        per_scope.setdefault(scope, p)
    trigger_lines = []
    for p in per_scope.values():
        thr = p.get("compression_threshold")
        if thr is None:
            continue
        ctx = p.get("context_length") or DEFAULT_CONTEXT_LENGTH
        trigger_lines.append(float(thr) * float(ctx))
    trigger_line_tokens = int(min(trigger_lines)) if trigger_lines else DEFAULT_TRIGGER_LINE_TOKENS

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
    #
    # Compaction-aware (2026-09-15): context_compression events from
    # the converter are matched to each session segment so findings
    # can distinguish "never compacted" (config off / threshold too
    # high) from "compacted but still bloated" (threshold too late).
    # ============================================================
    all_model_calls = sorted(
        [e for e in tool_and_model if e.get("type") == "model_call"],
        key=lambda e: e.get("timestamp") or "",
    )

    # 压缩事件（started/done），按时间戳排序，用于会话段归因
    compressions = sorted(
        [e for e in sorted_events if e.get("type") == "context_compression"],
        key=lambda e: e.get("timestamp") or "",
    )
    compression_ts = [e.get("timestamp") or "" for e in compressions]

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

            # 会话峰值 + 段内压缩次数（bloat / 临界分支共用）
            peak_tokens = max((mc.get("payload", {}).get("tokens_in", 0) or 0) for mc in sess)
            s_ts0 = sess[0].get("timestamp") or ""
            s_ts1 = sess[-1].get("timestamp") or ""
            n_comp = 0
            if compression_ts and s_ts0 and s_ts1:
                n_comp = sum(1 for c in compression_ts if s_ts0 <= c <= s_ts1)

            total_excess = 0
            total_excess_cache = 0
            for mc in sess[1:]:
                tokens_in = mc.get("payload", {}).get("tokens_in", 0) or 0
                cache_hit = mc.get("payload", {}).get("cache_hit", 0) or 0
                excess = max(0, tokens_in - baseline)
                total_excess += excess
                # Excess tokens are billed like any other input; the
                # cache-hit share of the excess is proportional to the
                # cache-hit share of the whole call (provider-side prefix
                # cache covers the stable prefix, so this is approximate).
                if tokens_in > 0 and excess > 0:
                    total_excess_cache += round(
                        excess * min(cache_hit, tokens_in) / tokens_in
                    )

            if total_excess > 100_000:
                est_wasted_cost = cost_model.input_cost(total_excess, cache_hit=total_excess_cache)

                if n_comp >= 1:
                    recommendation = (
                        f"session was compacted {n_comp}× but still reached "
                        f"{total_excess:,} excess tokens — lower compression.threshold "
                        "or split long tasks across sessions (/new) earlier"
                    )
                else:
                    recommendation = (
                        "compact/reset context deliberately at session boundaries "
                        "instead of silently growing it"
                    )

                findings.append({
                    "severity": "high",
                    "title": "session-level context bloat: no deliberate compaction",
                    "evidence_refs": [
                        sess[0].get("event_id"),
                        sess[-1].get("event_id"),
                    ],
                    "call_count": len(sess),
                    "extra_tokens_in": total_excess,
                    "compaction_count": n_comp,
                    # proximity（2026-09-15）：峰值距压缩触发线多远。
                    # zine 实证：峰值 291,728 vs 触发线 300,000 差 8,272 ——
                    # 「差一点没触发」比事后 bloat 更早暴露风险。
                    "peak_tokens_in": peak_tokens,
                    "trigger_line_tokens": trigger_line_tokens,
                    "distance_to_trigger": trigger_line_tokens - peak_tokens,
                    "waste_ratio": round(
                        total_excess / max(1, sum(
                            mc.get("payload", {}).get("tokens_in", 0) or 0
                            for mc in sess
                        )), 4
                    ),
                    "est_wasted_cost": round(est_wasted_cost, 6),
                    "recommendation": recommendation,
                    "fix_ref": "context-compaction: deliberate reset per session",
                    "recheck_metric": "extra_tokens_in",
                })

                # 临界会话：已 bloat 且峰值距触发线 < 20% → 补充提示触发线过低/过近
                if trigger_line_tokens - peak_tokens < 0.2 * trigger_line_tokens:
                    findings.append({
                        "severity": "info",
                        "title": "session peaked within 20% of compression trigger line",
                        "evidence_refs": [
                            sess[0].get("event_id"),
                            sess[-1].get("event_id"),
                        ],
                        "call_count": len(sess),
                        "peak_tokens_in": peak_tokens,
                        "trigger_line_tokens": trigger_line_tokens,
                        "distance_to_trigger": trigger_line_tokens - peak_tokens,
                        "extra_tokens_in": 0,
                        "waste_ratio": 0.0,
                        "est_wasted_cost": 0.0,
                        "recommendation": (
                            f"session peak {peak_tokens:,} is within 20% of the "
                            f"compression trigger line ({trigger_line_tokens:,}) — "
                            "compaction barely fired; consider lowering "
                            "compression.threshold for earlier, cheaper compaction"
                        ),
                        "fix_ref": "context-compaction: lower threshold",
                        "recheck_metric": "distance_to_trigger",
                    })

            # 未达 bloat 阈值但接近触发线且未压缩 → 临界风险预警
            elif n_comp == 0 and NEAR_LINE_RATIO * trigger_line_tokens <= peak_tokens < trigger_line_tokens:
                findings.append({
                    "severity": "info",
                    "title": "session approaching compression threshold (no compaction)",
                    "evidence_refs": [
                        sess[0].get("event_id"),
                        sess[-1].get("event_id"),
                    ],
                    "call_count": len(sess),
                    "peak_tokens_in": peak_tokens,
                    "trigger_line_tokens": trigger_line_tokens,
                    "distance_to_trigger": trigger_line_tokens - peak_tokens,
                    "extra_tokens_in": 0,
                    "waste_ratio": 0.0,
                    "est_wasted_cost": 0.0,
                    "recommendation": (
                        f"session peak {peak_tokens:,} is within "
                        f"{int((1 - NEAR_LINE_RATIO) * 100)}% of the compression "
                        f"trigger line ({trigger_line_tokens:,}) but never compacted — "
                        "lower compression.threshold so the next long session compacts "
                        "before it approaches bloat"
                    ),
                    "fix_ref": "context-compaction: lower threshold",
                    "recheck_metric": "distance_to_trigger",
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

    # ============================================================
    # Detection 6: Config drift — inconsistent / lax compression thresholds
    # ============================================================
    # 触发：converter 注入了 config_snapshot 事件。这是 watchdog 数据暴露的
    # 根因级发现（治理前 5 profile threshold 0.1/0.5 混用，审计本身没抓到）
    # —— 工具能审别人、漏了自己，缺的就是这一维。
    if snapshots and len(per_scope) >= 1:
        # 6a. 不一致：多 scope threshold 值不统一
        thr_by_scope = {
            s: p.get("compression_threshold")
            for s, p in per_scope.items()
            if p.get("compression_threshold") is not None
        }
        if len(thr_by_scope) >= 2 and len(set(thr_by_scope.values())) > 1:
            detail = "; ".join(
                f"{s}={v}" for s, v in sorted(thr_by_scope.items())
            )
            findings.append({
                "severity": "high",
                "title": "config drift: inconsistent compression thresholds",
                "evidence_refs": [e.get("event_id") for e in snapshots if e.get("event_id")],
                "extra_tokens_in": 0,
                "waste_ratio": 0.0,
                "est_wasted_cost": 0.0,
                "config_detail": detail,
                "recommendation": (
                    f"unify compression.threshold across agents ({detail}); "
                    "lax agents (0.3+) let sessions reach ~300k tokens before "
                    "compacting — align toward 0.1-0.2"
                ),
                "fix_ref": "config-drift: unify thresholds",
                "recheck_metric": "config_threshold_uniformity",
            })

        # 6b. 过松：单 scope threshold 过高或触发线超过默认触发线
        for scope, p in per_scope.items():
            thr = p.get("compression_threshold")
            if thr is None:
                continue
            ctx = p.get("context_length") or DEFAULT_CONTEXT_LENGTH
            line = float(thr) * float(ctx)
            if float(thr) > CONFIG_LAX_THRESHOLD or int(line) > DEFAULT_TRIGGER_LINE_TOKENS:
                findings.append({
                    "severity": "medium",
                    "title": (
                        f"lax compression threshold: {scope} "
                        f"(threshold {thr} → trigger line {int(line):,} tokens)"
                    ),
                    "evidence_refs": [
                        e.get("event_id")
                        for e in snapshots
                        if (e.get("payload", {}) or {}).get("scope") == scope
                        and e.get("event_id")
                    ],
                    "extra_tokens_in": 0,
                    "waste_ratio": 0.0,
                    "est_wasted_cost": 0.0,
                    "config_detail": f"threshold={thr}, context_length={int(ctx)}, trigger_line={int(line):,}",
                    "recommendation": (
                        f"lower {scope} compression.threshold from {thr} to "
                        f"<= {CONFIG_LAX_THRESHOLD} so sessions compact before "
                        f"reaching {int(line):,} tokens"
                    ),
                    "fix_ref": f"config-drift: lower {scope} threshold",
                    "recheck_metric": "config_threshold_laxness",
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
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

    def _trigger_line_for(profile: str) -> int:
        """按 profile 取压缩触发线（threshold×context_length）。

        2026-09-16 修复：之前全局取 min（所有 profile 都用 creative 的 100K），
        researcher/main 真实触发线 200K 被压到 100K，proximity/距离判断失真
        （researcher 185K 显示 186% 超线，实际离 200K 线还差 8%）。
        profile 为 gateway（gw-N）或无快照时回退到全局最严 min（保守）。
        """
        # 主 profile 的 event_id 前缀是 ag-main，但 config snapshot 的 scope 是 default
        scope = "default" if profile == "main" else profile
        if scope in per_scope:
            p = per_scope[scope]
            thr = p.get("compression_threshold")
            ctx = p.get("context_length") or DEFAULT_CONTEXT_LENGTH
            if thr is not None:
                return int(float(thr) * float(ctx))
        return trigger_line_tokens

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
    # 排序 key：先按 profile（event_id 前缀）再按时间。2026-09-16 修复：
    # 之前只按时间戳全局排序，多 profile 并发时不同 profile 的 model_call
    # 交错插入同一会话（实证：creative-evt-1603 → researcher-evt-1446 →
    # creative-evt-1605），_sid 变化强制切段把同一会话切碎，压缩事件被甩出
    # 段窗口 → 假「peak>100K 且 comp=0 漏触发」。按 profile 分组后同会话
    # 的调用连续排列，切段/压缩归因回到 profile 内部语义。
    def _profile_key(e):
        eid = e.get("event_id") or ""
        parts = eid.split("-")
        if len(parts) >= 2 and parts[0] in ("ag", "gw"):
            return parts[1]
        return "zzz-other"

    all_model_calls = sorted(
        [e for e in tool_and_model if e.get("type") == "model_call"],
        key=lambda e: (_profile_key(e), e.get("timestamp") or ""),
    )

    # 压缩事件（started/done），按时间戳排序，用于会话段归因。
    # 只统计 started（done 是同一事件的确认，不重复计——2026-09-16 修复：
    # 之前 started+done 都计入导致一次压缩算 2 次，段内出现 comp=5/10 虚高）。
    compressions = sorted(
        [e for e in sorted_events
         if e.get("type") == "context_compression"
         and (e.get("payload", {}) or {}).get("stage") == "started"],
        key=lambda e: e.get("timestamp") or "",
    )

    if all_model_calls:
        # Group model calls into sessions by detecting context resets
        # 会话级切段（2026-09-16 修复）：除 tokens 掉 50% 外，session_id 变化
        # 也强制切段——多 profile 日志拼接后并发会话交替时，A 结束 B 开始
        # tokens 未必掉 50%（B 可能已进行到 80K），旧逻辑把不同 session 混进
        # 同一段（实证：段3 含 3 个 session），baseline/peak/压缩归因全失真。
        # 压缩（Hermes）会创建新 session_id，session 变化恰对应 context reset。
        def _sid(e):
            sid = e.get("session_id") or (e.get("payload", {}) or {}).get("session_id")
            if sid:
                return sid
            # 兜底：无 session_id 的事件（converter 未从日志行提取到）用
            # event_id 的 profile 前缀作伪 sid（ag-main / ag-creative / gw-1），
            # 保证不同 profile 的事件即使缺 sid 也会强制切段，不跨 profile 混段。
            eid = e.get("event_id") or ""
            parts = eid.split("-")
            if len(parts) >= 2 and parts[0] in ("ag", "gw"):
                return f"pfx:{parts[0]}-{parts[1]}"
            return None

        sessions = []
        current = [all_model_calls[0]]
        for i in range(1, len(all_model_calls)):
            prev_tokens = (
                all_model_calls[i - 1].get("payload", {}).get("tokens_in", 0) or 0
            )
            curr_tokens = (
                all_model_calls[i].get("payload", {}).get("tokens_in", 0) or 0
            )
            prev_sid = _sid(all_model_calls[i - 1])
            curr_sid = _sid(all_model_calls[i])
            if prev_tokens > 0 and curr_tokens < prev_tokens * 0.5:
                sessions.append(current)
                current = [all_model_calls[i]]
            elif prev_sid and curr_sid and prev_sid != curr_sid:
                sessions.append(current)
                current = [all_model_calls[i]]
            else:
                current.append(all_model_calls[i])
        if current:
            sessions.append(current)

        # 段边界时间窗口（2026-09-16 压缩归因修复）：压缩事件（started）几乎
        # 总是发生在段尾之后、下一段首之前——因为「tokens 掉 50% 切段」依赖的
        # 就是压缩 done 之后 tokens 骤降。所以段 i 的压缩归属窗口应为
        # [段 i 首 call, 段 i+1 首 call)，而不是 [段 i 首, 段 i 尾]——
        # 后者会把所有压缩事件都甩到段间间隙里（实证：researcher 会话 3 次
        # 压缩全落在间隙，旧逻辑 comp=0 全丢）。
        seg_windows = []  # (start_ts, end_ts_exclusive)，最后一段的 end 为 None
        for i, sess in enumerate(sessions):
            seg_windows.append((
                sess[0].get("timestamp") or "",
                sessions[i + 1][0].get("timestamp") or "" if i + 1 < len(sessions) else None,
            ))

        for idx, sess in enumerate(sessions):
            if len(sess) < 3:
                continue
            baseline = sess[0].get("payload", {}).get("tokens_in", 0) or 0
            if baseline <= 0:
                continue

            # 会话峰值 + 段内压缩次数（bloat / 临界分支共用）。
            # 会话级归因（2026-09-16 修复）：压缩事件带 session_id（converter
            # 从日志行 [session] 提取），按「段内会话 session_id ∩ 压缩事件
            # session_id」匹配，而不是纯时间窗口——多会话并发时时间窗口会
            # 跨会话误归因（comp 虚高）。段内可能混多个 session（并发/交替），
            # 压缩事件只要属于段内任一 session 且时间戳落在段归属窗口内即计入。
            peak_tokens = max((mc.get("payload", {}).get("tokens_in", 0) or 0) for mc in sess)
            s_ts0, s_ts1 = seg_windows[idx]
            # 段所属 profile → 按该 profile 的真实压缩触发线（2026-09-16 修复：
            # 之前全局取 min，researcher/main 真实 200K 被压到 creative 的 100K）。
            # gw-N / 无前缀事件没有 profile 快照，回退全局最严 min（保守）。
            seg_trigger = _trigger_line_for(_profile_key(sess[0]))
            # 段内涉及的 session_id 集合（converter 顶层字段 / payload 双来源）
            seg_sessions = set()
            for mc in sess:
                sid = mc.get("session_id") or (mc.get("payload", {}) or {}).get("session_id")
                if sid:
                    seg_sessions.add(sid)
            n_comp = 0
            if compressions and s_ts0:
                for c in compressions:
                    c_ts = c.get("timestamp") or ""
                    if not c_ts:
                        continue
                    # 归属窗口：[段首, 下一段首)。最后一段无上界。
                    if c_ts < s_ts0 or (s_ts1 and c_ts >= s_ts1):
                        continue
                    if seg_sessions:
                        c_sid = c.get("session_id") or (c.get("payload", {}) or {}).get("session_id")
                        if c_sid and c_sid in seg_sessions:
                            n_comp += 1
                        # 无 session_id 的压缩事件（旧事件流）：仍按时间窗口计，
                        # 但只有段无 session 信息时才宽松计（避免跨会话误归因）
                        elif not c_sid:
                            n_comp += 1
                    else:
                        n_comp += 1

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
                    "trigger_line_tokens": seg_trigger,
                    "distance_to_trigger": seg_trigger - peak_tokens,
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
                if seg_trigger - peak_tokens < 0.2 * seg_trigger:
                    findings.append({
                        "severity": "info",
                        "title": "session peaked within 20% of compression trigger line",
                        "evidence_refs": [
                            sess[0].get("event_id"),
                            sess[-1].get("event_id"),
                        ],
                        "call_count": len(sess),
                        "peak_tokens_in": peak_tokens,
                        "trigger_line_tokens": seg_trigger,
                        "distance_to_trigger": seg_trigger - peak_tokens,
                        "extra_tokens_in": 0,
                        "waste_ratio": 0.0,
                        "est_wasted_cost": 0.0,
                        "recommendation": (
                            f"session peak {peak_tokens:,} is within 20% of the "
                            f"compression trigger line ({seg_trigger:,}) — "
                            "compaction barely fired; consider lowering "
                            "compression.threshold for earlier, cheaper compaction"
                        ),
                        "fix_ref": "context-compaction: lower threshold",
                        "recheck_metric": "distance_to_trigger",
                    })

            # 未达 bloat 阈值但接近触发线且未压缩 → 临界风险预警
            elif n_comp == 0 and NEAR_LINE_RATIO * seg_trigger <= peak_tokens < seg_trigger:
                findings.append({
                    "severity": "info",
                    "title": "session approaching compression threshold (no compaction)",
                    "evidence_refs": [
                        sess[0].get("event_id"),
                        sess[-1].get("event_id"),
                    ],
                    "call_count": len(sess),
                    "peak_tokens_in": peak_tokens,
                    "trigger_line_tokens": seg_trigger,
                    "distance_to_trigger": seg_trigger - peak_tokens,
                    "extra_tokens_in": 0,
                    "waste_ratio": 0.0,
                    "est_wasted_cost": 0.0,
                    "recommendation": (
                        f"session peak {peak_tokens:,} is within "
                        f"{int((1 - NEAR_LINE_RATIO) * 100)}% of the compression "
                        f"trigger line ({seg_trigger:,}) but never compacted — "
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
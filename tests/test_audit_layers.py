"""Integration tests for all six audit layers using example data."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentlens_cli.parser import parse_jsonl
from agentlens_cli.graph import build_graph
from agentlens_cli.decision import audit_decisions
from agentlens_cli.evidence import verify_evidence
from agentlens_cli.attribution import attribute_costs
from agentlens_cli.governance import detect_waste
from agentlens_cli.shadow import detect_shadow_agents
from agentlens_cli.compliance import audit_compliance
from agentlens_cli.config import CostModel, DEFAULT_KNOWN_AGENTS, DEFAULT_DANGEROUS_TOOLS


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _load(path):
    return list(parse_jsonl(str(path)))


# ── Approval Bypass ────────────────────────────────────────────────


class TestApprovalBypass:
    """approval_bypass.json: decision.approval_bypass_detected must be True."""

    def test_approval_bypass_detected(self):
        events = _load(EXAMPLES_DIR / "approval_bypass.json")
        # This file is .json not .jsonl, so parse_jsonl won't read it well.
        # Load via the _load_events logic in __main__.
        with open(EXAMPLES_DIR / "approval_bypass.json", "r", encoding="utf-8") as fh:
            data = json.load(fh)
        events = data["events"]
        result = audit_decisions(events)
        assert result["approval_bypass_detected"] is True, (
            f"expected bypass_detected=True, got {result['approval_bypass_detected']}"
        )

    def test_approval_bypass_finding_title(self):
        with open(EXAMPLES_DIR / "approval_bypass.json", "r", encoding="utf-8") as fh:
            data = json.load(fh)
        events = data["events"]
        result = audit_decisions(events)
        titles = [f["title"] for f in result["findings"]]
        assert "APPROVAL_BYPASS_CONFIRMED" in titles, (
            f"APPROVAL_BYPASS_CONFIRMED not found in findings: {titles}"
        )

    def test_approval_bypass_high_severity(self):
        with open(EXAMPLES_DIR / "approval_bypass.json", "r", encoding="utf-8") as fh:
            data = json.load(fh)
        events = data["events"]
        result = audit_decisions(events)
        bypass_findings = [
            f for f in result["findings"] if f["title"] == "APPROVAL_BYPASS_CONFIRMED"
        ]
        assert len(bypass_findings) >= 1
        for bf in bypass_findings:
            assert bf["severity"] == "high", (
                f"expected severity=high, got {bf['severity']}"
            )


# ── Closure Rate = 1.0 ─────────────────────────────────────────────


class TestClosureRate:
    """multi_agent_task_events_v2.jsonl: graph.metrics.closure_rate must be 1.0."""

    def test_closure_rate_v2(self):
        events = _load(EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl")
        graph = build_graph(events)
        assert graph["metrics"]["closure_rate"] == 1.0, (
            f"expected closure_rate=1.0, got {graph['metrics']['closure_rate']}"
        )

    def test_closure_rate_v2_closed_equals_dispatched(self):
        events = _load(EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl")
        graph = build_graph(events)
        m = graph["metrics"]
        assert m["closed_count"] == m["total_dispatched"], (
            f"closed_count={m['closed_count']} != total_dispatched={m['total_dispatched']}"
        )

    def test_closure_rate_v2_no_unclosed(self):
        events = _load(EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl")
        graph = build_graph(events)
        assert graph["metrics"]["unclosed_tasks"] == [], (
            f"expected no unclosed tasks, got {graph['metrics']['unclosed_tasks']}"
        )

    def test_closure_rate_v2_no_absent_workers(self):
        events = _load(EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl")
        graph = build_graph(events)
        assert graph["metrics"]["absent_workers"] == [], (
            f"expected no absent workers, got {graph['metrics']['absent_workers']}"
        )

    def test_gaps_scenario_closure_less_than_one(self):
        """multi_agent_task_events.jsonl (5 events with gaps) should have closure < 1.0."""
        events = _load(EXAMPLES_DIR / "multi_agent_task_events.jsonl")
        graph = build_graph(events)
        assert graph["metrics"]["closure_rate"] < 1.0, (
            f"expected closure_rate < 1.0 for gaps file, got {graph['metrics']['closure_rate']}"
        )

    def test_gaps_scenario_has_absent_workers(self):
        events = _load(EXAMPLES_DIR / "multi_agent_task_events.jsonl")
        graph = build_graph(events)
        absent = graph["metrics"]["absent_workers"]
        assert len(absent) > 0, f"expected absent workers, got {absent}"
        assert "graph-builder" in absent
        assert "decision-auditor" in absent


# ── Shadow Agent Detection ─────────────────────────────────────────


class TestShadowDetection:
    """shadow_agent_events.jsonl: must detect all three shadow finding types."""

    def test_shadow_finding_types(self):
        events = _load(EXAMPLES_DIR / "shadow_agent_events.jsonl")
        findings = detect_shadow_agents(events, DEFAULT_KNOWN_AGENTS, DEFAULT_DANGEROUS_TOOLS)
        titles = [f["title"] for f in findings]
        assert "SHADOW_AGENT_DETECTED" in titles, (
            f"SHADOW_AGENT_DETECTED missing, got: {titles}"
        )
        assert "UNAUTHORIZED_TOOL_CALL" in titles, (
            f"UNAUTHORIZED_TOOL_CALL missing, got: {titles}"
        )
        assert "PRIVILEGE_BOUNDARY_VIOLATION" in titles, (
            f"PRIVILEGE_BOUNDARY_VIOLATION missing, got: {titles}"
        )

    def test_shadow_phantom_worker_detected(self):
        events = _load(EXAMPLES_DIR / "shadow_agent_events.jsonl")
        findings = detect_shadow_agents(events, DEFAULT_KNOWN_AGENTS, DEFAULT_DANGEROUS_TOOLS)
        shadow_findings = [
            f for f in findings if f["title"] == "SHADOW_AGENT_DETECTED"
        ]
        agents = [f.get("agent") for f in shadow_findings]
        assert "phantom-worker" in agents, (
            f"phantom-worker not detected as shadow, agents: {agents}"
        )

    def test_shadow_unauthorized_tool_call(self):
        events = _load(EXAMPLES_DIR / "shadow_agent_events.jsonl")
        findings = detect_shadow_agents(events, DEFAULT_KNOWN_AGENTS, DEFAULT_DANGEROUS_TOOLS)
        unauthorized = [
            f for f in findings if f["title"] == "UNAUTHORIZED_TOOL_CALL"
        ]
        assert len(unauthorized) >= 1, f"expected at least 1 UNAUTHORIZED_TOOL_CALL"
        tools = [f.get("tool") for f in unauthorized]
        assert "shell" in tools, f"shell not in unauthorized tools: {tools}"

    def test_shadow_privilege_violation(self):
        events = _load(EXAMPLES_DIR / "shadow_agent_events.jsonl")
        findings = detect_shadow_agents(events, DEFAULT_KNOWN_AGENTS, DEFAULT_DANGEROUS_TOOLS)
        priv = [
            f for f in findings if f["title"] == "PRIVILEGE_BOUNDARY_VIOLATION"
        ]
        assert len(priv) >= 1, f"expected at least 1 PRIVILEGE_BOUNDARY_VIOLATION"
        agents = [f.get("agent") for f in priv]
        assert "collector" in agents, f"collector not in privilege violations: {agents}"

    def test_user_unknown_whitelisted_not_shadow(self):
        """2026-09-09 自治理：user:* 前缀（外部网关用户）不再误报为影子智能体。
        由 EXTERNAL_USER_PREFIXES 前缀规则豁免，不依赖白名单硬编码。"""
        events = _load(EXAMPLES_DIR / "hermes_gateway_events.jsonl")
        findings = detect_shadow_agents(events, DEFAULT_KNOWN_AGENTS, DEFAULT_DANGEROUS_TOOLS)
        shadow_agents = [
            f.get("agent") for f in findings if f["title"] == "SHADOW_AGENT_DETECTED"
        ]
        # user:* 前缀应被豁免（含 user:unknown 与真实飞书 open_id user:ou_xxx）
        assert not any(a.startswith("user:") for a in shadow_agents), (
            f"user:* 前缀应被 EXTERNAL_USER_PREFIXES 豁免，仍在 shadow 发现中: {shadow_agents}"
        )
        # hermes:gateway:log（事件流 source）在白名单中
        assert "hermes:gateway:log" in DEFAULT_KNOWN_AGENTS, (
            "hermes:gateway:log 应存在于 DEFAULT_KNOWN_AGENTS 白名单"
        )


# ── Compliance Detection ───────────────────────────────────────────


class TestCompliance:
    """compliance_violations.jsonl: must detect all four compliance finding types."""

    def test_compliance_finding_types(self):
        events = _load(EXAMPLES_DIR / "compliance_violations.jsonl")
        result = audit_compliance(events)
        titles = [f["title"] for f in result["findings"]]
        assert "USER_ONLY_VIOLATION" in titles, (
            f"USER_ONLY_VIOLATION missing, got: {titles}"
        )
        assert "HIGH_RISK_AUTONOMOUS_DECISION" in titles, (
            f"HIGH_RISK_AUTONOMOUS_DECISION missing, got: {titles}"
        )
        assert "MISSING_USER_AUTHORIZATION" in titles, (
            f"MISSING_USER_AUTHORIZATION missing, got: {titles}"
        )
        assert "MISSING_INFORMED_CONSENT" in titles, (
            f"MISSING_INFORMED_CONSENT missing, got: {titles}"
        )

    def test_compliance_user_only_high_severity(self):
        events = _load(EXAMPLES_DIR / "compliance_violations.jsonl")
        result = audit_compliance(events)
        user_only = [
            f for f in result["findings"] if f["title"] == "USER_ONLY_VIOLATION"
        ]
        assert len(user_only) >= 1
        for f in user_only:
            assert f["severity"] == "high"

    def test_compliance_high_risk_autonomous(self):
        events = _load(EXAMPLES_DIR / "compliance_violations.jsonl")
        result = audit_compliance(events)
        high_risk = [
            f for f in result["findings"]
            if f["title"] == "HIGH_RISK_AUTONOMOUS_DECISION"
        ]
        assert len(high_risk) >= 1
        for f in high_risk:
            assert f["severity"] == "high"

    def test_compliance_missing_auth_medium(self):
        events = _load(EXAMPLES_DIR / "compliance_violations.jsonl")
        result = audit_compliance(events)
        missing_auth = [
            f for f in result["findings"]
            if f["title"] == "MISSING_USER_AUTHORIZATION"
        ]
        assert len(missing_auth) >= 1
        for f in missing_auth:
            assert f["severity"] == "medium"

    def test_compliance_missing_consent_info(self):
        events = _load(EXAMPLES_DIR / "compliance_violations.jsonl")
        result = audit_compliance(events)
        missing_consent = [
            f for f in result["findings"]
            if f["title"] == "MISSING_INFORMED_CONSENT"
        ]
        assert len(missing_consent) >= 1
        for f in missing_consent:
            assert f["severity"] == "info"


# ── Hermes Gateway Events ──────────────────────────────────────────


class TestHermesGateway:
    """hermes_gateway_events.jsonl: all seven layers, shadow not exploding, cost ratio > 0.5."""

    def test_hermes_all_layers_produce_output(self):
        """All seven layers (graph, decision, evidence, cost, shadow, compliance) produce
        a result dict without exceptions."""
        events = _load(EXAMPLES_DIR / "hermes_gateway_events.jsonl")
        cm = CostModel()

        graph = build_graph(events)
        assert "nodes" in graph
        assert "edges" in graph
        assert "metrics" in graph

        decision = audit_decisions(events)
        assert "findings" in decision
        assert "approval_bypass_detected" in decision

        all_findings = graph.get("findings", []) + decision.get("findings", [])
        evidence = verify_evidence(events, all_findings)
        assert "completeness" in evidence

        cost = attribute_costs(events, cm)
        assert "total_cost" in cost

        waste = detect_waste(events, cm)
        assert "total_est_wasted_cost" in waste

        shadow = detect_shadow_agents(events)
        assert isinstance(shadow, list)

        compliance = audit_compliance(events)
        assert "findings" in compliance
        assert "summary" in compliance

    def test_hermes_shadow_not_exploding(self):
        """Shadow findings count should be < 10 (no approval stream → downgrade)."""
        events = _load(EXAMPLES_DIR / "hermes_gateway_events.jsonl")
        findings = detect_shadow_agents(events)
        assert len(findings) < 10, (
            f"expected shadow findings < 10 (no approval stream for hermes), got {len(findings)}"
        )

    def test_hermes_cost_avoidable_ratio(self):
        """cost.avoidable_cost_ratio should be > 0.5 for hermes data."""
        events = _load(EXAMPLES_DIR / "hermes_gateway_events.jsonl")
        cm = CostModel()
        cost = attribute_costs(events, cm)
        waste = detect_waste(events, cm)
        total_cost = cost["total_cost"]
        total_wasted = waste["total_est_wasted_cost"]
        ratio = round(total_wasted / total_cost, 4) if total_cost > 0 else 0.0
        assert ratio > 0.5, (
            f"expected avoidable_cost_ratio > 0.5, got {ratio}"
        )

    def test_hermes_events_loaded_matches(self):
        events = _load(EXAMPLES_DIR / "hermes_gateway_events.jsonl")
        assert len(events) == 11268


# ── Cost Model ─────────────────────────────────────────────────────


class TestCostModel:
    def test_cost_model_creation(self):
        cm = CostModel(input_price=3.0, output_price=9.0)
        assert cm.input_price == 3.0
        assert cm.output_price == 9.0

    def test_cost_model_input_cost(self):
        cm = CostModel(input_price=3.0, output_price=9.0)
        assert cm.input_cost(1_000_000) == 3.0
        assert cm.input_cost(500_000) == 1.5

    def test_cost_model_output_cost(self):
        cm = CostModel(input_price=3.0, output_price=9.0)
        assert cm.output_cost(1_000_000) == 9.0

    def test_cost_model_total_cost(self):
        cm = CostModel(input_price=3.0, output_price=9.0)
        assert cm.total_cost(1_000_000, 500_000) == 3.0 + 4.5

    def test_cost_model_to_dict(self):
        cm = CostModel()
        d = cm.to_dict()
        assert d["input_price_per_1m"] == 3.0
        assert d["output_price_per_1m"] == 9.0
        assert d["cache_read_price_per_1m"] == 0.10
        assert d["currency"] == "CNY"

    def test_cost_model_cache_discount(self):
        """Cache-hit tokens are billed at cache_read_price, not full input price."""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        # 1M tokens fully cache-hit → 0.10 CNY, not 3.0
        assert cm.input_cost(1_000_000, cache_hit=1_000_000) == 0.10
        # 1M tokens: 400K cached, 600K uncached → 0.6*3.0 + 0.4*0.1 = 1.84
        assert abs(cm.input_cost(1_000_000, cache_hit=400_000) - 1.84) < 1e-9
        # No cache_hit → unchanged legacy behavior
        assert cm.input_cost(1_000_000) == 3.0
        # cache_hit clamped to tokens (defensive)
        assert cm.input_cost(500_000, cache_hit=999_999) == 0.05
        # total_cost with cache
        assert abs(cm.total_cost(1_000_000, 500_000, cache_hit=1_000_000) - (0.10 + 4.5)) < 1e-9

    def test_attribute_costs_uses_cache_field(self):
        """attribution should bill cache-hit tokens at discount when payload carries cache_hit."""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = [
            {
                "type": "model_call",
                "payload": {
                    "agent": "test",
                    "tokens_in": 1_000_000,
                    "tokens_out": 0,
                    "cache_hit": 1_000_000,
                },
            }
        ]
        cost = attribute_costs(events, cm)
        assert abs(cost["total_cost"] - 0.10) < 1e-9

    def test_bloat_finding_uses_cache_discount(self):
        """session-level bloat wasted cost should reflect cache discount on excess tokens."""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        # Session of 4 calls: baseline 100K, each later call 300K input with 100% cache hit.
        events = []
        for i in range(4):
            events.append(
                {
                    "type": "model_call",
                    "payload": {
                        "agent": "test",
                        "tokens_in": 100_000 if i == 0 else 300_000,
                        "tokens_out": 0,
                        "cache_hit": 100_000 if i == 0 else 300_000,
                    },
                    "event_id": f"evt-{i}",
                    "evidence_ref": f"test:{i}",
                }
            )
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        assert len(bloat) == 1
        # excess = 3 * 200K = 600K tokens, all cache-hit → 600K * 0.10/M = 0.06 CNY
        # (vs 600K * 3.0/M = 1.8 CNY without cache discount)
        assert abs(bloat[0]["est_wasted_cost"] - 0.06) < 1e-6

    # ── Compaction-aware bloat 归因（2026-09-15） ──────────────────────

    def _bloat_session_events(self):
        """4 个 model_call 的 bloat 会话（baseline 100K → 300K×3），带时间戳。"""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = []
        for i, ts in enumerate(
            ["2026-09-15T10:00:00+00:00", "2026-09-15T10:10:00+00:00",
             "2026-09-15T10:20:00+00:00", "2026-09-15T10:30:00+00:00"]
        ):
            events.append(
                {
                    "type": "model_call",
                    "payload": {
                        "agent": "test",
                        "tokens_in": 100_000 if i == 0 else 300_000,
                        "tokens_out": 0,
                        "cache_hit": 100_000 if i == 0 else 300_000,
                    },
                    "event_id": f"evt-{i}",
                    "evidence_ref": f"test:{i}",
                    "timestamp": ts,
                }
            )
        return events, cm

    def test_bloat_finding_no_compaction_count_zero(self):
        """无压缩事件 → compaction_count == 0，建议保持「主动压缩」。"""
        events, cm = self._bloat_session_events()
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        assert len(bloat) == 1
        assert bloat[0]["compaction_count"] == 0
        assert "compacted" not in bloat[0]["recommendation"]

    def test_bloat_finding_compaction_count_matches(self):
        """段内 2 次压缩（2×started）仍 bloat → compaction_count == 2，建议调低 threshold。

        一次压缩只计 started（done 是同一事件的确认，不重复计——2026-09-16 修复）。
        """
        events, cm = self._bloat_session_events()
        events.append(
            {
                "type": "context_compression",
                "payload": {"stage": "started", "session": "s1", "messages": "200", "tokens": 250_000},
                "event_id": "evt-c1",
                "evidence_ref": "test:c1",
                "timestamp": "2026-09-15T10:25:00+00:00",
            }
        )
        events.append(
            {
                "type": "context_compression",
                "payload": {"stage": "started", "session": "s1", "messages": "180", "tokens": 230_000},
                "event_id": "evt-c2",
                "evidence_ref": "test:c2",
                "timestamp": "2026-09-15T10:28:00+00:00",
            }
        )
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        assert len(bloat) == 1
        assert bloat[0]["compaction_count"] == 2
        assert "compacted 2" in bloat[0]["recommendation"]
        assert "threshold" in bloat[0]["recommendation"]

    def test_bloat_finding_compression_done_not_counted(self):
        """done 事件是 started 的确认，不重复计（一次压缩 = 1 次 started）。"""
        events, cm = self._bloat_session_events()
        events.append(
            {
                "type": "context_compression",
                "payload": {"stage": "started", "session": "s1", "messages": "200", "tokens": 250_000},
                "event_id": "evt-c1",
                "evidence_ref": "test:c1",
                "timestamp": "2026-09-15T10:25:00+00:00",
            }
        )
        events.append(
            {
                "type": "context_compression",
                "payload": {"stage": "done", "session": "s1", "messages": "200->7", "tokens": 5_000},
                "event_id": "evt-c2",
                "evidence_ref": "test:c2",
                "timestamp": "2026-09-15T10:28:00+00:00",
            }
        )
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        assert len(bloat) == 1
        assert bloat[0]["compaction_count"] == 1
        assert "compacted 1" in bloat[0]["recommendation"]

    def test_bloat_finding_compression_outside_segment_ignored(self):
        """压缩事件时间戳在会话段外 → 不计入该段。

        归属窗口为 [段首, 下一段首)；10:00 之前的压缩事件落在第一段窗口外 → 忽略。
        """
        events, cm = self._bloat_session_events()
        events.append(
            {
                "type": "context_compression",
                "payload": {"stage": "started", "session": "other", "messages": "50", "tokens": 40_000},
                "event_id": "evt-c1",
                "evidence_ref": "test:c1",
                "timestamp": "2026-09-15T09:00:00+00:00",  # 段之前
            }
        )
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        assert len(bloat) == 1
        assert bloat[0]["compaction_count"] == 0

    def test_bloat_finding_compression_in_segment_gap_counted(self):
        """压缩事件落在段尾与下一段首之间的间隙 → 计入前一段。

        回归 2026-09-16 实证：压缩 started 几乎总发生在「压缩 done 后 tokens 掉
        50% 切段」的间隙里（researcher 会话 3 次压缩全落在间隙，旧逻辑 [段首,段尾]
        窗口 comp=0 全丢）。归属窗口应为 [段首, 下一段首)。
        """
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = []
        # 段 A: 10:00~10:10~10:12（基线 50K → 300K → 290K），压缩 started 在 10:15（段间隙）
        for i, ts in enumerate(
            ["2026-09-15T10:00:00+00:00", "2026-09-15T10:10:00+00:00",
             "2026-09-15T10:12:00+00:00"]
        ):
            events.append(
                {
                    "type": "model_call",
                    "payload": {
                        "agent": "test",
                        "tokens_in": 50_000 if i == 0 else (300_000 if i == 1 else 290_000),
                        "tokens_out": 0,
                        "cache_hit": 50_000 if i == 0 else (300_000 if i == 1 else 290_000),
                        "session_id": "s1",
                    },
                    "event_id": f"evt-a{i}",
                    "evidence_ref": f"test:a{i}",
                    "timestamp": ts,
                }
            )
        # 段 B: 10:20 起（压缩后 tokens 掉到 8K 触发切段）
        events.append(
            {
                "type": "model_call",
                "payload": {
                    "agent": "test",
                    "tokens_in": 8_000,
                    "tokens_out": 0,
                    "cache_hit": 8_000,
                    "session_id": "s1",
                },
                "event_id": "evt-b0",
                "evidence_ref": "test:b0",
                "timestamp": "2026-09-15T10:20:00+00:00",
            }
        )
        # 压缩 started 落在段 A 尾与段 B 首之间的间隙（10:15）
        events.append(
            {
                "type": "context_compression",
                "payload": {"stage": "started", "session": "s1", "messages": "100", "tokens": 300_000},
                "event_id": "evt-c1",
                "evidence_ref": "test:c1",
                "timestamp": "2026-09-15T10:15:00+00:00",
            }
        )
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        # 段 B 只有 1 个 call（len<3 跳过）→ 仅段 A 产生 bloat finding
        assert len(bloat) == 1
        # 段 A（peak 300K）的压缩计数应包含间隙里的这次 started
        assert bloat[0]["call_count"] == 3
        assert bloat[0]["compaction_count"] == 1
        assert "compacted 1" in bloat[0]["recommendation"]


# ── 优化1: 配置漂移审计（2026-09-15） ─────────────────────────────


def _snap_events(snapshots: list) -> list:
    """Build config_snapshot events (as injected by converter --config-snapshot)."""
    return [
        {
            "type": "config_snapshot",
            "payload": p,
            "event_id": f"snap-{i}",
            "timestamp": "2026-09-15T10:00:00+00:00",
            "source": "hermes:agent:config",
            "evidence_ref": "<config-snapshot>",
        }
        for i, p in enumerate(snapshots, 1)
    ]


class TestConfigDrift:
    """Detection 6: config drift — inconsistent / lax compression thresholds."""

    def test_inconsistent_thresholds_high(self):
        """2 scopes 阈值不一致（creative 0.1 / researcher 0.5）→ high finding。"""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = _snap_events([
            {"scope": "creative", "compression_threshold": 0.1, "context_length": 1_000_000},
            {"scope": "researcher", "compression_threshold": 0.5, "context_length": 1_000_000},
        ])
        waste = detect_waste(events, cm)
        drift = [f for f in waste["findings"] if "inconsistent compression thresholds" in f["title"]]
        assert len(drift) == 1
        assert drift[0]["severity"] == "high"
        assert "creative=0.1" in drift[0]["config_detail"]
        assert "researcher=0.5" in drift[0]["config_detail"]

    def test_lax_threshold_medium(self):
        """单 scope threshold 0.5 → medium（过松）。"""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = _snap_events([
            {"scope": "ops", "compression_threshold": 0.5, "context_length": 1_000_000},
        ])
        waste = detect_waste(events, cm)
        lax = [f for f in waste["findings"] if "lax compression threshold" in f["title"]]
        assert len(lax) == 1
        assert lax[0]["severity"] == "medium"
        assert "ops" in lax[0]["title"]
        assert "500,000" in lax[0]["title"]  # 触发线 0.5M tokens

    def test_consistent_thresholds_no_drift(self):
        """2 scopes 都 0.1 → 无 drift / lax finding。"""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = _snap_events([
            {"scope": "creative", "compression_threshold": 0.1, "context_length": 1_000_000},
            {"scope": "researcher", "compression_threshold": 0.1, "context_length": 1_000_000},
        ])
        waste = detect_waste(events, cm)
        drift = [f for f in waste["findings"] if "config drift" in f["title"] or "lax compression" in f["title"]]
        assert drift == []

    def test_no_snapshot_no_drift_finding(self):
        """无 config_snapshot 事件 → 不产生 drift finding（旧行为不变）。"""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = [
            {"type": "model_call", "payload": {"agent": "test", "tokens_in": 100_000, "tokens_out": 0},
             "event_id": "evt-1", "timestamp": "2026-09-15T10:00:00+00:00"},
        ]
        waste = detect_waste(events, cm)
        drift = [f for f in waste["findings"] if "config drift" in f["title"] or "lax compression" in f["title"]]
        assert drift == []


# ── 优化2: proximity 临界风险（2026-09-15） ────────────────────────


class TestProximity:
    """bloat finding 带距触发线距离；临界会话（差一点没触发）提前预警。"""

    def _bloat_events(self):
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = []
        for i, ts in enumerate(
            ["2026-09-15T10:00:00+00:00", "2026-09-15T10:10:00+00:00",
             "2026-09-15T10:20:00+00:00", "2026-09-15T10:30:00+00:00"]
        ):
            events.append({
                "type": "model_call",
                "payload": {
                    "agent": "test",
                    "tokens_in": 100_000 if i == 0 else 300_000,
                    "tokens_out": 0,
                    "cache_hit": 100_000 if i == 0 else 300_000,
                },
                "event_id": f"evt-{i}",
                "evidence_ref": f"test:{i}",
                "timestamp": ts,
            })
        return events, cm

    def test_bloat_finding_has_proximity_fields(self):
        """bloat finding 带 peak/trigger_line/distance；默认触发线 300k。"""
        events, cm = self._bloat_events()
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        assert len(bloat) == 1
        assert bloat[0]["peak_tokens_in"] == 300_000
        assert bloat[0]["trigger_line_tokens"] == 300_000
        assert bloat[0]["distance_to_trigger"] == 0

    def test_proximity_uses_snapshot_trigger_line(self):
        """注入 config_snapshot（threshold 0.2×1M=200k）→ 触发线 200k，distance 为负。"""
        events, cm = self._bloat_events()
        events += _snap_events([
            {"scope": "test", "compression_threshold": 0.2, "context_length": 1_000_000},
        ])
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        assert len(bloat) == 1
        assert bloat[0]["trigger_line_tokens"] == 200_000
        assert bloat[0]["distance_to_trigger"] == -100_000  # 已超线 100k

    def test_session_approaching_threshold_info(self):
        """未 bloat（excess 70k < 100k）但峰值 290k ≥ 80% 触发线 → info 预警。"""
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = [
            {"type": "model_call",
             "payload": {"agent": "test", "tokens_in": 250_000, "tokens_out": 0, "cache_hit": 250_000},
             "event_id": "evt-0", "timestamp": "2026-09-15T10:00:00+00:00"},
            {"type": "model_call",
             "payload": {"agent": "test", "tokens_in": 280_000, "tokens_out": 0, "cache_hit": 280_000},
             "event_id": "evt-1", "timestamp": "2026-09-15T10:10:00+00:00"},
            {"type": "model_call",
             "payload": {"agent": "test", "tokens_in": 290_000, "tokens_out": 0, "cache_hit": 290_000},
             "event_id": "evt-2", "timestamp": "2026-09-15T10:20:00+00:00"},
        ]
        waste = detect_waste(events, cm)
        bloat = [f for f in waste["findings"] if "context bloat" in f["title"]]
        assert bloat == []  # excess 70k < 100k，不 bloat
        near = [f for f in waste["findings"] if "approaching compression threshold" in f["title"]]
        assert len(near) == 1
        assert near[0]["severity"] == "info"
        assert near[0]["peak_tokens_in"] == 290_000
        assert near[0]["trigger_line_tokens"] == 300_000
        assert near[0]["distance_to_trigger"] == 10_000

    def test_compacted_session_not_flagged_near_line(self):
        """已压缩过的会话即使接近触发线也不报 approaching（压缩是正常信号）。

        压缩用 started 表达（2026-09-16 起只计 started，done 不重复计）；
        压缩 started 落在段尾间隙（10:15，下一段首 10:20 之前）→ 归入前一段。
        """
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        events = [
            {"type": "model_call",
             "payload": {"agent": "test", "tokens_in": 250_000, "tokens_out": 0},
             "event_id": "evt-0", "timestamp": "2026-09-15T10:00:00+00:00"},
            {"type": "model_call",
             "payload": {"agent": "test", "tokens_in": 290_000, "tokens_out": 0},
             "event_id": "evt-1", "timestamp": "2026-09-15T10:10:00+00:00"},
            {"type": "context_compression",
             "payload": {"stage": "started", "session": "s1", "messages": "50", "tokens": 3_000},
             "event_id": "evt-c1", "timestamp": "2026-09-15T10:15:00+00:00"},
            {"type": "model_call",
             "payload": {"agent": "test", "tokens_in": 250_000, "tokens_out": 0},
             "event_id": "evt-2", "timestamp": "2026-09-15T10:20:00+00:00"},
        ]
        waste = detect_waste(events, cm)
        near = [f for f in waste["findings"] if "approaching compression threshold" in f["title"]]
        assert near == []


# ── 优化3: 价格版本 + 外置配置（2026-09-15） ───────────────────────


class TestCostModelExt:
    """CostModel 价格版本字段与环境变量外置。"""

    def test_to_dict_has_price_version(self):
        cm = CostModel(input_price=3.0, output_price=9.0, cache_read_price=0.10)
        d = cm.to_dict()
        assert d["price_version"] == "2026-09-15"
        assert d["cache_read_price_per_1m"] == 0.10

    def test_from_env_defaults(self, monkeypatch):
        for k in ("AGENTLENS_PRICE_INPUT", "AGENTLENS_PRICE_OUTPUT",
                  "AGENTLENS_PRICE_CACHE", "AGENTLENS_PRICE_VERSION"):
            monkeypatch.delenv(k, raising=False)
        cm = CostModel.from_env()
        assert cm.input_price == 3.0
        assert cm.output_price == 9.0
        assert cm.cache_read_price == 0.10
        assert cm.price_version == "2026-09-15"

    def test_from_env_overrides(self, monkeypatch):
        for k in ("AGENTLENS_PRICE_INPUT", "AGENTLENS_PRICE_OUTPUT",
                  "AGENTLENS_PRICE_CACHE", "AGENTLENS_PRICE_VERSION"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("AGENTLENS_PRICE_INPUT", "2.4")
        monkeypatch.setenv("AGENTLENS_PRICE_CACHE", "0")
        monkeypatch.setenv("AGENTLENS_PRICE_VERSION", "2026-08-21")
        cm = CostModel.from_env()
        assert cm.input_price == 2.4
        assert cm.cache_read_price == 0.0  # 显式 0 必须生效（免费 cache）
        assert cm.price_version == "2026-08-21"
        assert cm.output_price == 9.0  # 未设置 → 默认

    def test_from_env_ignores_invalid(self, monkeypatch):
        monkeypatch.delenv("AGENTLENS_PRICE_INPUT", raising=False)
        monkeypatch.setenv("AGENTLENS_PRICE_INPUT", "abc")
        cm = CostModel.from_env()
        assert cm.input_price == 3.0  # 非法值回退默认
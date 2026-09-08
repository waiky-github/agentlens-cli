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
        cm = CostModel(input_price=2.4, output_price=8.0)
        assert cm.input_price == 2.4
        assert cm.output_price == 8.0

    def test_cost_model_input_cost(self):
        cm = CostModel(input_price=2.4, output_price=8.0)
        assert cm.input_cost(1_000_000) == 2.4
        assert cm.input_cost(500_000) == 1.2

    def test_cost_model_output_cost(self):
        cm = CostModel(input_price=2.4, output_price=8.0)
        assert cm.output_cost(1_000_000) == 8.0

    def test_cost_model_total_cost(self):
        cm = CostModel(input_price=2.4, output_price=8.0)
        assert cm.total_cost(1_000_000, 500_000) == 2.4 + 4.0

    def test_cost_model_to_dict(self):
        cm = CostModel()
        d = cm.to_dict()
        assert d["input_price_per_1m"] == 2.4
        assert d["output_price_per_1m"] == 8.0
        assert d["currency"] == "CNY"
"""Tests for remediation suggestion mapping (remediation.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentlens_cli.remediation import (
    map_finding,
    map_all_layers,
    list_remediations,
    REMEDIATIONS,
    DYNAMIC_REMEDIATIONS,
    _lookup_remediations,
    _DEFAULT_REMEDIATION,
)
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


# ── Exact match ───────────────────────────────────────────────────────


class TestExactMatch:
    """Test that exact finding titles map to correct remediation actions."""

    def test_shadow_agent_remediation(self):
        """SHADOW_AGENT_DETECTED must have high-priority remediation."""
        rems = map_finding({"title": "SHADOW_AGENT_DETECTED"})["remediation"]
        assert len(rems) >= 1
        assert any("high" == r["priority"] for r in rems)
        assert any("白名单" in r["action"] for r in rems)

    def test_unauthorized_tool_call_remediation(self):
        """UNAUTHORIZED_TOOL_CALL must suggest approval flow."""
        rems = map_finding({"title": "UNAUTHORIZED_TOOL_CALL"})["remediation"]
        assert any("审批" in r["action"] for r in rems)

    def test_approval_bypass_remediation(self):
        """APPROVAL_BYPASS_CONFIRMED must have remediation."""
        rems = map_finding({"title": "APPROVAL_BYPASS_CONFIRMED"})["remediation"]
        assert len(rems) >= 2
        assert any("high" == r["priority"] for r in rems)

    def test_missing_evidence_ref_remediation(self):
        """events missing evidence_ref must have remediation."""
        rems = map_finding({"title": "events missing evidence_ref"})["remediation"]
        assert len(rems) >= 1

    def test_unclosed_tasks_remediation(self):
        """unclosed tasks detected must have remediation."""
        rems = map_finding({"title": "unclosed tasks detected"})["remediation"]
        assert len(rems) >= 1
        assert any("关闭" in r["action"] for r in rems)

    def test_task_dispatch_missing_rationale_remediation(self):
        """task_dispatch missing rationale must have remediation."""
        rems = map_finding({"title": "task_dispatch missing rationale"})["remediation"]
        assert len(rems) >= 1
        assert any("rationale" in r["action"] for r in rems)

    def test_large_output_tool_injection_remediation(self):
        """large-output tool injection ungoverned must have remediation."""
        rems = map_finding({"title": "large-output tool injection ungoverned"})["remediation"]
        assert len(rems) >= 1
        assert any("截断" in r["action"] or "截断" in r["detail"] for r in rems)

    def test_no_per_agent_token_caps_remediation(self):
        """no per-agent token caps observed must have remediation."""
        rems = map_finding({"title": "no per-agent token caps observed"})["remediation"]
        assert len(rems) >= 1
        assert any("上限" in r["action"] for r in rems)

    def test_cost_model_gaps_remediation(self):
        """cost-model gaps must have remediation."""
        rems = map_finding({"title": "cost-model gaps"})["remediation"]
        assert len(rems) >= 1

    def test_user_only_violation_remediation(self):
        """USER_ONLY_VIOLATION must have high-priority remediation."""
        rems = map_finding({"title": "USER_ONLY_VIOLATION"})["remediation"]
        assert any("high" == r["priority"] for r in rems)

    def test_missing_informed_consent_remediation(self):
        """MISSING_INFORMED_CONSENT must have remediation."""
        rems = map_finding({"title": "MISSING_INFORMED_CONSENT"})["remediation"]
        assert len(rems) >= 1

    def test_absent_workers_remediation(self):
        """absent workers must have remediation."""
        rems = map_finding({"title": "absent workers"})["remediation"]
        assert len(rems) >= 1

    def test_data_gaps_remediation(self):
        """data gaps in collaboration graph must have remediation."""
        rems = map_finding({"title": "data gaps in collaboration graph"})["remediation"]
        assert len(rems) >= 1

    def test_finding_evidence_refs_not_resolvable_remediation(self):
        """finding evidence_refs not resolvable must have remediation."""
        rems = map_finding({"title": "finding evidence_refs not resolvable"})["remediation"]
        assert len(rems) >= 1

    def test_audit_gap_no_approval_stream_remediation(self):
        """AUDIT_GAP_NO_APPROVAL_STREAM must have remediation."""
        rems = map_finding({"title": "AUDIT_GAP_NO_APPROVAL_STREAM"})["remediation"]
        assert len(rems) >= 1

    def test_privilege_boundary_violation_remediation(self):
        """PRIVILEGE_BOUNDARY_VIOLATION must have remediation."""
        rems = map_finding({"title": "PRIVILEGE_BOUNDARY_VIOLATION"})["remediation"]
        assert len(rems) >= 1

    def test_each_remediation_has_required_fields(self):
        """Every remediation entry must have action, detail, priority."""
        for title, rems in REMEDIATIONS.items():
            for rem in rems:
                assert "action" in rem, f"missing action in {title}"
                assert "detail" in rem, f"missing detail in {title}"
                assert "priority" in rem, f"missing priority in {title}"
                assert rem["priority"] in ("high", "medium", "low"), f"invalid priority in {title}: {rem['priority']}"


# ── Dynamic pattern matching ─────────────────────────────────────────


class TestDynamicRemediations:
    """Test that dynamic (prefix-based) patterns match correctly."""

    def test_repeated_calls_pattern_matches(self):
        """repeated calls to same high-output tool: xxx should match."""
        rems = map_finding({"title": "repeated calls to same high-output tool: search"})["remediation"]
        assert len(rems) >= 1
        assert any("频率" in r["action"] for r in rems)

    def test_inefficient_loop_pattern_matches(self):
        """inefficient loop: rapid repeated calls to xxx should match."""
        rems = map_finding({"title": "inefficient loop: rapid repeated calls to grep"})["remediation"]
        assert len(rems) >= 1


# ── Fallback ──────────────────────────────────────────────────────────


class TestFallback:
    """Test that unknown findings get the default fallback remediation."""

    def test_unknown_finding_gets_default(self):
        """Unknown finding title should get the default remediation."""
        rems = _lookup_remediations("completely unknown finding type")
        assert rems == _DEFAULT_REMEDIATION
        assert rems[0]["action"] == "人工复核"

    def test_map_finding_unknown_gets_default(self):
        """map_finding on unknown title should add default remediation."""
        f = map_finding({"title": "nonexistent finding"})
        assert "remediation" in f
        assert f["remediation"] == _DEFAULT_REMEDIATION


# ── map_all_layers integration ───────────────────────────────────────


class TestMapAllLayersRemediation:
    """Integration test: run full audit and verify all findings have remediation."""

    def test_map_all_layers_adds_remediation_to_all_findings(self):
        """After map_all_layers, every finding across all layers must have remediation."""
        events = _load(EXAMPLES_DIR / "compliance_violations.jsonl")
        cm = CostModel()

        graph_data = build_graph(events)
        decision_data = audit_decisions(events)
        all_findings = graph_data.get("findings", []) + decision_data.get("findings", [])
        evidence_data = verify_evidence(events, all_findings)
        cost_attribution = attribute_costs(events, cm)
        governance_data = detect_waste(events, cm)
        shadow_findings = detect_shadow_agents(events, DEFAULT_KNOWN_AGENTS, DEFAULT_DANGEROUS_TOOLS)
        compliance_data = audit_compliance(events)

        total_cost = cost_attribution["total_cost"]
        total_wasted = governance_data["total_est_wasted_cost"]
        avoidable_ratio = round(total_wasted / total_cost, 4) if total_cost > 0 else 0.0

        result = {
            "events_loaded": len(events),
            "graph": {
                "nodes": graph_data["nodes"],
                "edges": graph_data["edges"],
                "metrics": graph_data["metrics"],
                "findings": graph_data["findings"],
            },
            "decision": {
                "decision_chain": decision_data["decision_chain"],
                "findings": decision_data["findings"],
                "summary": decision_data["summary"],
            },
            "evidence": {
                "claims_checked": evidence_data["claims_checked"],
                "verified": evidence_data["verified"],
                "completeness": evidence_data["completeness"],
                "findings": evidence_data["findings"],
            },
            "cost": {
                "total_cost": total_cost,
                "total_tokens_in": cost_attribution["total_tokens_in"],
                "total_tokens_out": cost_attribution["total_tokens_out"],
                "findings": governance_data["findings"],
                "total_est_wasted_cost": total_wasted,
                "avoidable_cost_ratio": avoidable_ratio,
            },
            "shadow": {
                "findings": shadow_findings,
            },
            "compliance": {
                "findings": compliance_data["findings"],
            },
        }

        map_all_layers(result)

        # Check all findings have remediation
        layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
        total_findings = 0
        for key in layer_keys:
            layer = result.get(key, {})
            for f in layer.get("findings", []):
                total_findings += 1
                assert "remediation" in f, (
                    f"finding '{f.get('title')}' in layer '{key}' missing remediation"
                )
                assert isinstance(f["remediation"], list)
                assert len(f["remediation"]) > 0, (
                    f"finding '{f.get('title')}' has empty remediation"
                )

        assert total_findings > 0, "expected at least 1 finding across all layers"

    def test_map_all_layers_does_not_modify_other_keys(self):
        """map_all_layers should not add remediation to non-layer keys."""
        result = {
            "events_loaded": 10,
            "graph": {"findings": []},
            "decision": {"findings": [{"title": "SHADOW_AGENT_DETECTED", "severity": "high"}]},
        }
        map_all_layers(result)
        assert "remediation" not in result

    def test_map_all_layers_handles_missing_layers(self):
        """map_all_layers should handle layers that are not dicts."""
        result = {"graph": None, "decision": "not a dict"}
        # Should not raise
        map_all_layers(result)


# ── list_remediations ─────────────────────────────────────────────────


class TestListRemediations:
    """Test the list_remediations function."""

    def test_list_all_returns_entries(self):
        """list_remediations() should return all entries."""
        entries = list_remediations()
        assert len(entries) > 0, "expected at least one remediation mapping"

    def test_list_filtered_by_title(self):
        """list_remediations with title filter should return matching entries."""
        entries = list_remediations("SHADOW")
        assert len(entries) >= 1
        assert any("SHADOW" in e["title"] for e in entries)

    def test_list_filter_no_match(self):
        """list_remediations with no-match filter should return empty."""
        entries = list_remediations("zzz_nonexistent_zzz")
        assert len(entries) == 0

    def test_list_entries_have_correct_structure(self):
        """Each entry from list_remediations should have title and remediations keys."""
        entries = list_remediations()
        for entry in entries:
            assert "title" in entry
            assert "remediations" in entry
            assert isinstance(entry["remediations"], list)
            for rem in entry["remediations"]:
                assert "action" in rem
                assert "detail" in rem
                assert "priority" in rem
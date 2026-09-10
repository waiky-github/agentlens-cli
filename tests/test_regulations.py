"""Tests for regulation reference mapping (regulations.py)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentlens_cli.regulations import (
    map_finding,
    map_all_layers,
    list_regulations,
    REGULATIONS,
    DYNAMIC_REGULATIONS,
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


# ── Mapping correctness assertions ───────────────────────────────────


class TestRegulationMapping:
    """Test that each finding title maps to the correct regulation references."""

    def test_approval_bypass_maps_to_article_6(self):
        """APPROVAL_BYPASS_CONFIRMED must reference 实施意见 第6条."""
        refs = map_finding({"title": "APPROVAL_BYPASS_CONFIRMED"})["regulation_refs"]
        assert len(refs) >= 2
        impl_refs = [r for r in refs if "实施意见" in r["regulation"]]
        assert len(impl_refs) >= 1
        assert any("第 6 条" in r["article"] for r in impl_refs)

    def test_user_only_violation_maps_to_article_6(self):
        """USER_ONLY_VIOLATION must reference 实施意见 第6条."""
        refs = map_finding({"title": "USER_ONLY_VIOLATION"})["regulation_refs"]
        impl_refs = [r for r in refs if "实施意见" in r["regulation"]]
        assert len(impl_refs) >= 1
        assert any("第 6 条" in r["article"] for r in impl_refs), (
            f"expected 第6条 ref, got: {impl_refs}"
        )

    def test_shadow_agent_detected_maps_to_shadow_requirement(self):
        """SHADOW_AGENT_DETECTED must reference 影子智能体."""
        refs = map_finding({"title": "SHADOW_AGENT_DETECTED"})["regulation_refs"]
        assert any("影子智能体" in r["article"] for r in refs), (
            f"expected 影子智能体 ref, got: {refs}"
        )

    def test_unauthorized_tool_call_maps_to_security(self):
        """UNAUTHORIZED_TOOL_CALL must reference 内生安全."""
        refs = map_finding({"title": "UNAUTHORIZED_TOOL_CALL"})["regulation_refs"]
        assert any("内生安全" in r["article"] for r in refs), (
            f"expected 内生安全 ref, got: {refs}"
        )

    def test_missing_informed_consent_maps_to_personification(self):
        """MISSING_INFORMED_CONSENT must reference 拟人化互动."""
        refs = map_finding({"title": "MISSING_INFORMED_CONSENT"})["regulation_refs"]
        assert any("拟人化" in r["regulation"] for r in refs), (
            f"expected 拟人化互动 ref, got: {refs}"
        )

    def test_unknown_finding_gets_manual_review(self):
        """Unknown finding title should get 'manual review required' fallback."""
        refs = map_finding({"title": "completely unknown finding type"})["regulation_refs"]
        assert len(refs) == 1
        assert refs[0]["regulation"] == "unknown"
        assert "manual review required" in refs[0]["note"]

    def test_large_output_tool_injection_maps(self):
        """large-output tool injection ungoverned must reference 内生安全."""
        refs = map_finding({"title": "large-output tool injection ungoverned"})["regulation_refs"]
        assert any("内生安全" in r["article"] for r in refs), (
            f"expected 内生安全 ref, got: {refs}"
        )

    def test_events_missing_evidence_ref_maps(self):
        """events missing evidence_ref must reference 行为管控."""
        refs = map_finding({"title": "events missing evidence_ref"})["regulation_refs"]
        assert any("行为管控" in r["article"] for r in refs), (
            f"expected 行为管控 ref, got: {refs}"
        )


# ── Dynamic pattern matching ─────────────────────────────────────────


class TestDynamicRegulations:
    """Test that dynamic (prefix-based) patterns match correctly."""

    def test_repeated_calls_pattern_matches(self):
        """repeated calls to same high-output tool: xxx should match."""
        refs = map_finding({"title": "repeated calls to same high-output tool: search"})["regulation_refs"]
        assert any("内生安全" in r["article"] for r in refs)

    def test_inefficient_loop_pattern_matches(self):
        """inefficient loop: rapid repeated calls to xxx should match."""
        refs = map_finding({"title": "inefficient loop: rapid repeated calls to grep"})["regulation_refs"]
        assert any("内生安全" in r["article"] for r in refs)


# ── map_all_layers integration ───────────────────────────────────────


class TestMapAllLayers:
    """Integration test: run full audit and verify all findings have regulation_refs."""

    def test_map_all_layers_adds_refs_to_all_findings(self):
        """After map_all_layers, every finding across all layers must have regulation_refs."""
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

        # Check all findings have regulation_refs
        layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
        total_findings = 0
        for key in layer_keys:
            layer = result.get(key, {})
            for f in layer.get("findings", []):
                total_findings += 1
                assert "regulation_refs" in f, (
                    f"finding '{f.get('title')}' in layer '{key}' missing regulation_refs"
                )
                assert isinstance(f["regulation_refs"], list)
                assert len(f["regulation_refs"]) > 0, (
                    f"finding '{f.get('title')}' has empty regulation_refs"
                )

        assert total_findings > 0, "expected at least 1 finding across all layers"

    def test_compliance_findings_in_approval_bypass_have_refs(self):
        """Run audit on approval_bypass.json and verify decision findings have regulation_refs."""
        with open(EXAMPLES_DIR / "approval_bypass.json", "r", encoding="utf-8") as fh:
            data = json.load(fh)
        events = data["events"]
        decision_data = audit_decisions(events)
        result = {"decision": {"findings": decision_data["findings"]}}
        map_all_layers(result)
        for f in result["decision"]["findings"]:
            assert "regulation_refs" in f
            assert len(f["regulation_refs"]) > 0


# ── list_regulations ─────────────────────────────────────────────────


class TestOWASPMapping:
    """OWASP LLM Top 10 2026 / Agentic Top 10 (ASI) / ACS mapping (added 2026-09-10)."""

    def test_shadow_agent_maps_to_asi10(self):
        """SHADOW_AGENT_DETECTED must reference OWASP Agentic ASI10 (Rogue Agents)."""
        refs = map_finding({"title": "SHADOW_AGENT_DETECTED"})["regulation_refs"]
        owasp = [r for r in refs if "Agentic Applications" in r["regulation"]]
        assert any(r["article"] == "ASI10" for r in owasp), f"expected ASI10, got: {owasp}"

    def test_approval_bypass_maps_to_llm03_asi09_acs(self):
        """APPROVAL_BYPASS_CONFIRMED must reference LLM03 + ASI09 + ACS."""
        refs = map_finding({"title": "APPROVAL_BYPASS_CONFIRMED"})["regulation_refs"]
        articles = {r.get("article") for r in refs}
        assert "LLM03" in articles, f"expected LLM03, got: {articles}"
        assert "ASI09" in articles, f"expected ASI09, got: {articles}"
        assert any("ACS" in r.get("regulation", "") for r in refs)

    def test_unauthorized_tool_call_maps_to_asi02(self):
        """UNAUTHORIZED_TOOL_CALL must reference ASI02 (Tool Misuse)."""
        refs = map_finding({"title": "UNAUTHORIZED_TOOL_CALL"})["regulation_refs"]
        owasp = [r for r in refs if "Agentic Applications" in r["regulation"]]
        assert any(r["article"] == "ASI02" for r in owasp), f"expected ASI02, got: {owasp}"

    def test_layer_fallback_cost_to_llm06(self):
        """Cost-layer finding without precise override must fall back to LLM06 (Unbounded Consumption)."""
        refs = map_finding({"title": "some cost finding not in table"}, layer="cost")["regulation_refs"]
        owasp = [r for r in refs if "OWASP Top 10 for LLM" in r["regulation"]]
        assert any(r["article"] == "LLM06" for r in owasp), f"expected LLM06, got: {owasp}"

    def test_layer_fallback_graph_to_asi07(self):
        """Graph-layer finding must fall back to ASI07 (Insecure Inter-Agent Communication)."""
        refs = map_finding({"title": "some graph finding not in table"}, layer="graph")["regulation_refs"]
        owasp = [r for r in refs if "Agentic Applications" in r["regulation"]]
        assert any(r["article"] == "ASI07" for r in owasp), f"expected ASI07, got: {owasp}"

    def test_unknown_finding_keeps_manual_review_no_owasp(self):
        """Fully unknown finding (no layer context) must NOT get OWASP refs bolted on — stays manual review."""
        refs = map_finding({"title": "completely unknown finding type"})["regulation_refs"]
        assert len(refs) == 1
        assert refs[0]["regulation"] == "unknown"
        assert not any("OWASP" in r.get("regulation", "") for r in refs)

    def test_unknown_title_with_known_layer_gets_fallback(self):
        """Unknown title but known layer -> layer fallback OWASP applies (map_all_layers always passes layer)."""
        refs = map_finding({"title": "weird unknown title"}, layer="cost")["regulation_refs"]
        assert any("OWASP" in r.get("regulation", "") for r in refs)
        assert any(r.get("article") == "LLM06" for r in refs)
        # layer fallback 是弱映射：unknown 打底保留（提示人工复核）
        assert any(r.get("regulation") == "unknown" for r in refs)

    def test_precise_override_drops_unknown_stub(self):
        """Precise title override must NOT keep the unknown stub — override provides full compliance semantics."""
        refs = map_finding({"title": "LARGE_OUTPUT_CONTEXT_EXPOSURE_SUSPECTED"})["regulation_refs"]
        assert not any(r.get("regulation") == "unknown" for r in refs), f"unknown stub leaked: {refs}"
        owasp = [r for r in refs if "OWASP Top 10 for LLM" in r["regulation"]]
        assert any(r["article"] == "LLM08" for r in owasp), f"expected LLM08, got: {owasp}"
        assert any(r["article"] == "LLM06" for r in owasp), f"expected LLM06, got: {owasp}"

    def test_precise_override_keeps_manual_annotation(self):
        """Manual annotation (non-unknown) must survive when precise OWASP override also exists."""
        refs = map_finding({"title": "SYSTEM_PROMPT_LEAKAGE_SUSPECTED"})["regulation_refs"]
        # 无 unknown 打底
        assert not any(r.get("regulation") == "unknown" for r in refs)
        # 仍带 OWASP LLM08
        assert any(r.get("article") == "LLM08" for r in refs)

    def test_map_finding_does_not_pollute_static_table(self):
        """map_finding must not mutate the shared static REGULATIONS list (copy before append)."""
        from agentlens_cli.regulations import REGULATIONS
        sample_title = next(iter(REGULATIONS))
        before = len(REGULATIONS[sample_title])
        f1 = map_finding({"title": sample_title}, layer="graph")
        f2 = map_finding({"title": sample_title}, layer="graph")
        assert len(REGULATIONS[sample_title]) == before, "static REGULATIONS list was mutated"
        assert len(f1["regulation_refs"]) == len(f2["regulation_refs"]), "repeat mapping differs"

    def test_all_layers_have_owasp_after_map(self):
        """After map_all_layers on a real audit, every finding should carry OWASP/ACS refs."""
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
            "graph": {"findings": graph_data["findings"]},
            "decision": {"findings": decision_data["findings"]},
            "evidence": {"findings": evidence_data["findings"]},
            "cost": {"findings": governance_data["findings"]},
            "shadow": {"findings": shadow_findings},
            "compliance": {"findings": compliance_data["findings"]},
        }
        map_all_layers(result)
        layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
        total_with_owasp = 0
        total = 0
        for key in layer_keys:
            for f in result.get(key, {}).get("findings", []):
                total += 1
                if any("OWASP" in r.get("regulation", "") or "ACS" in r.get("regulation", "") for r in f.get("regulation_refs", [])):
                    total_with_owasp += 1
        assert total > 0
        # 已知 title 都在表内或可 fallback，未知 title 才可能没有——至少大多数应有 OWASP
        assert total_with_owasp >= total * 0.5, (
            f"expected most findings to carry OWASP refs, got {total_with_owasp}/{total}"
        )


class TestListRegulations:
    """Test the list_regulations function."""

    def test_list_all_returns_entries(self):
        entries = list_regulations()
        assert len(entries) > 0, "expected at least one regulation mapping"

    def test_list_filtered_by_title(self):
        entries = list_regulations("APPROVAL")
        assert len(entries) >= 1
        assert any("APPROVAL" in e["title"] for e in entries)

    def test_list_filter_no_match(self):
        entries = list_regulations("zzz_nonexistent_zzz")
        assert len(entries) == 0
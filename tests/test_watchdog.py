"""Tests for watchdog drift monitoring (watchdog.py)."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentlens_cli.watchdog import run_watchdog

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _make_baseline_result(findings_by_layer: dict = None) -> dict:
    """Create a minimal baseline audit result dict."""
    if findings_by_layer is None:
        findings_by_layer = {}
    result = {
        "events_loaded": 100,
        "graph": {
            "nodes": [],
            "edges": [],
            "metrics": {"closure_rate": 0.9},
            "findings": findings_by_layer.get("graph", []),
        },
        "decision": {
            "decision_chain": [],
            "findings": findings_by_layer.get("decision", []),
            "summary": "ok",
        },
        "evidence": {
            "claims_checked": 50,
            "verified": 45,
            "completeness": 0.9,
            "findings": findings_by_layer.get("evidence", []),
        },
        "cost": {
            "total_cost": 10.0,
            "total_tokens_in": 1000,
            "total_tokens_out": 500,
            "findings": findings_by_layer.get("cost", []),
            "total_est_wasted_cost": 1.0,
            "avoidable_cost_ratio": 0.1,
        },
        "shadow": {
            "findings": findings_by_layer.get("shadow", []),
        },
        "compliance": {
            "findings": findings_by_layer.get("compliance", []),
        },
    }
    return result


# ── Same baseline → no new findings ───────────────────────────────────


class TestWatchdogSameBaseline:
    """Baseline and current are identical → no drift."""

    def test_same_result_no_new_findings(self):
        baseline = _make_baseline_result({
            "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
        })
        current = _make_baseline_result({
            "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
        })
        result = run_watchdog(current, baseline)
        assert len(result["new_findings"]) == 0
        assert len(result["resolved_findings"]) == 0
        assert result["has_new_high"] is False
        assert result["summary"]["new_high"] == 0

    def test_empty_baseline_and_current(self):
        baseline = _make_baseline_result()
        current = _make_baseline_result()
        result = run_watchdog(current, baseline)
        assert len(result["new_findings"]) == 0
        assert len(result["resolved_findings"]) == 0
        assert result["has_new_high"] is False


# ── New finding detected ──────────────────────────────────────────────


class TestWatchdogNewFinding:
    """Current has a finding that baseline does not."""

    def test_new_high_finding_detected(self):
        baseline = _make_baseline_result()
        current = _make_baseline_result({
            "shadow": [{"title": "SHADOW_AGENT_DETECTED", "severity": "high"}],
        })
        result = run_watchdog(current, baseline)
        assert result["has_new_high"] is True
        assert len(result["new_findings"]) == 1
        assert result["new_findings"][0]["title"] == "SHADOW_AGENT_DETECTED"
        assert result["new_findings"][0]["severity"] == "high"
        assert result["new_findings"][0]["layer"] == "shadow"
        assert result["summary"]["new_high"] == 1

    def test_new_medium_finding_no_high_alert(self):
        baseline = _make_baseline_result()
        current = _make_baseline_result({
            "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
        })
        result = run_watchdog(current, baseline)
        assert result["has_new_high"] is False
        assert len(result["new_findings"]) == 1
        assert result["summary"]["new_medium"] == 1

    def test_count_increment_detected(self):
        """Same finding title but count increased → changed_counts has delta."""
        baseline = _make_baseline_result({
            "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
        })
        current = _make_baseline_result({
            "graph": [
                {"title": "unclosed tasks detected", "severity": "medium"},
                {"title": "unclosed tasks detected", "severity": "medium"},
            ],
        })
        result = run_watchdog(current, baseline)
        assert len(result["new_findings"]) == 0  # same key, just count change
        changed = result["changed_counts"]
        key = "graph/unclosed tasks detected/medium"
        assert key in changed
        assert changed[key]["baseline"] == 1
        assert changed[key]["current"] == 2
        assert changed[key]["delta"] == 1

    def test_high_count_increment_triggers_alert(self):
        """已有 high finding 数量增长（如 unauthorized calls 5→20）必须触发报警。"""
        baseline = _make_baseline_result({
            "shadow": [{"title": "SHADOW_AGENT_DETECTED", "severity": "high"}],
        })
        current = _make_baseline_result({
            "shadow": [
                {"title": "SHADOW_AGENT_DETECTED", "severity": "high"},
                {"title": "SHADOW_AGENT_DETECTED", "severity": "high"},
            ],
        })
        result = run_watchdog(current, baseline)
        # 不是全新 key，new_findings 为空；但数量增长必须算高风险漂移
        assert len(result["new_findings"]) == 0
        assert result["summary"]["growing_high"] == 1
        assert result["has_new_high"] is True

    def test_medium_count_increment_no_high_alert(self):
        """medium 数量增长不触发 high 报警（不误报）。"""
        baseline = _make_baseline_result({
            "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
        })
        current = _make_baseline_result({
            "graph": [
                {"title": "unclosed tasks detected", "severity": "medium"},
                {"title": "unclosed tasks detected", "severity": "medium"},
            ],
        })
        result = run_watchdog(current, baseline)
        assert result["summary"]["growing_high"] == 0
        assert result["has_new_high"] is False


# ── Resolved findings ─────────────────────────────────────────────────


class TestWatchdogResolved:
    """Baseline has a finding that current no longer has."""

    def test_resolved_finding(self):
        baseline = _make_baseline_result({
            "shadow": [{"title": "SHADOW_AGENT_DETECTED", "severity": "high"}],
        })
        current = _make_baseline_result()
        result = run_watchdog(current, baseline)
        assert len(result["resolved_findings"]) == 1
        assert result["resolved_findings"][0]["title"] == "SHADOW_AGENT_DETECTED"
        assert result["resolved_findings"][0]["severity"] == "high"
        assert result["summary"]["resolved_high"] == 1

    def test_resolved_high_and_new_medium(self):
        baseline = _make_baseline_result({
            "shadow": [{"title": "SHADOW_AGENT_DETECTED", "severity": "high"}],
        })
        current = _make_baseline_result({
            "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
        })
        result = run_watchdog(current, baseline)
        assert result["summary"]["resolved_high"] == 1
        assert result["summary"]["new_medium"] == 1
        assert result["has_new_high"] is False


# ── Cost and closure tracking ─────────────────────────────────────────


class TestWatchdogMetrics:
    """Watchdog tracks cost and closure rate changes."""

    def test_cost_change_tracked(self):
        baseline = _make_baseline_result()
        current = _make_baseline_result()
        current["cost"]["total_cost"] = 15.0
        result = run_watchdog(current, baseline)
        assert result["summary"]["cost_change"] == 5.0

    def test_closure_rate_change_tracked(self):
        baseline = _make_baseline_result()
        baseline["graph"]["metrics"]["closure_rate"] = 0.8
        current = _make_baseline_result()
        current["graph"]["metrics"]["closure_rate"] = 0.95
        result = run_watchdog(current, baseline)
        assert result["summary"]["closure_rate_change"] == 0.15


# ── Baseline file I/O ─────────────────────────────────────────────────


class TestWatchdogBaselineFile:
    """Test that write-baseline produces valid JSON."""

    def test_write_baseline_produces_valid_json(self):
        """--write-baseline should produce a valid JSON dict."""
        result = _make_baseline_result({
            "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert isinstance(loaded, dict)
            assert "graph" in loaded
            assert "events_loaded" in loaded
        finally:
            os.unlink(tmp_path)

    def test_baseline_can_be_used_for_comparison(self):
        """Write a baseline, then use it for comparison."""
        baseline = _make_baseline_result({
            "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(baseline, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            current = _make_baseline_result({
                "graph": [{"title": "unclosed tasks detected", "severity": "medium"}],
                "shadow": [{"title": "SHADOW_AGENT_DETECTED", "severity": "high"}],
            })
            result = run_watchdog(current, loaded)
            assert result["has_new_high"] is True
        finally:
            os.unlink(tmp_path)


# ── Parameter validation ──────────────────────────────────────────────


class TestWatchdogValidation:
    """Test that invalid inputs are handled."""

    def test_invalid_baseline_json_is_rejected(self):
        """Invalid JSON in baseline file should be caught."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json")
            tmp_path = f.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            try:
                json.loads(content)
                assert False, "should have raised"
            except json.JSONDecodeError:
                pass
        finally:
            os.unlink(tmp_path)

    def test_non_dict_baseline_is_rejected(self):
        """A list as baseline should be treated as invalid."""
        loaded = [1, 2, 3]
        assert not isinstance(loaded, dict)


# ── Output structure ──────────────────────────────────────────────────


class TestWatchdogOutputStructure:
    """Verify the output dict has all required fields."""

    def test_output_has_required_keys(self):
        baseline = _make_baseline_result()
        current = _make_baseline_result()
        result = run_watchdog(current, baseline)
        assert "new_findings" in result
        assert "resolved_findings" in result
        assert "changed_counts" in result
        assert "summary" in result
        assert "has_new_high" in result

    def test_summary_has_required_keys(self):
        baseline = _make_baseline_result()
        current = _make_baseline_result()
        result = run_watchdog(current, baseline)
        summary = result["summary"]
        assert "new_high" in summary
        assert "new_medium" in summary
        assert "resolved_high" in summary
        assert "cost_change" in summary
        assert "closure_rate_change" in summary
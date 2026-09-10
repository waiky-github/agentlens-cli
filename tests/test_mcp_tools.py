"""Tests for MCP tools (watchdog_status / remediation_lookup / fix_tracking_status)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentlens_cli.mcp_server import (  # noqa: E402
    fix_tracking_status,
    remediation_lookup,
    watchdog_status,
)


class TestWatchdogStatus:
    def test_returns_valid_json(self):
        out = json.loads(watchdog_status())
        assert "baseline_found" in out
        assert "reports_total" in out
        assert isinstance(out["reports_total"], int)

    def test_isolated_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENTLENS_REPORT_DIR", str(tmp_path))
        out = json.loads(watchdog_status())
        assert out["baseline_found"] is False
        assert out["reports_total"] == 0


class TestRemediationLookup:
    def test_exact_match_returns_items(self):
        out = json.loads(remediation_lookup("APPROVAL_BYPASS_CONFIRMED"))
        assert out["title"] == "APPROVAL_BYPASS_CONFIRMED"
        assert isinstance(out["remediations"], list)
        assert out["remediations"]

    def test_unknown_title_returns_fallback(self):
        out = json.loads(remediation_lookup("SOME_UNKNOWN_TITLE_XYZ"))
        # 精确/动态都没有 → 通用兜底（list 非空）
        assert isinstance(out["remediations"], list)
        assert out["remediations"]

    def test_owasp_linked_title(self):
        out = json.loads(remediation_lookup("SYSTEM_PROMPT_LEAKAGE_SUSPECTED"))
        assert isinstance(out["remediations"], list)
        assert out["remediations"]


class TestFixTrackingStatus:
    def test_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENTLENS_REPORT_DIR", str(tmp_path))
        out = json.loads(fix_tracking_status())
        assert out["found"] is False

    def test_with_file_summary(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENTLENS_REPORT_DIR", str(tmp_path))
        (tmp_path / "fixed-findings.json").write_text(
            json.dumps([
                {"key": "graph|A", "status": "closed", "verify_status": "verified", "marked_at": "t1"},
                {"key": "cost|B", "status": "marked_fixed", "verify_status": "verifying", "marked_at": "t2"},
                {"key": "shadow|C", "status": "reopened", "verify_status": "regressed", "marked_at": "t3"},
            ]),
            encoding="utf-8",
        )
        out = json.loads(fix_tracking_status())
        assert out["found"] is True
        assert out["total"] == 3
        assert out["by_status"] == {"closed": 1, "marked_fixed": 1, "reopened": 1}
        assert out["by_verify"] == {"verified": 1, "verifying": 1, "regressed": 1}
        assert len(out["entries"]) == 3
        # entry 不含 note 字段
        assert "note" not in out["entries"][0]

    def test_bad_json(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENTLENS_REPORT_DIR", str(tmp_path))
        (tmp_path / "fixed-findings.json").write_text("{broken", encoding="utf-8")
        out = json.loads(fix_tracking_status())
        assert out["found"] is False
        assert "error" in out

"""Tests for fix-regression verification (task 3, 2026-09-10).

连续缺席 N 次审计才确认修复（verified），期间再次出现即回归（regressed）。
用 monkeypatch 隔离到临时目录，不污染真实 fixed-findings.json。
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 与 test_web.py 保持一致：import web 前设置 REPORT_DIR env（pytest 按字母序收集，
# 本文件可能先于 test_web 导入 web 模块，必须用相同的 env 避免模块级 REPORT_DIR 分叉）
os.environ["AGENTLENS_REPORT_DIR"] = str(
    Path("/home/agentuser/.hermes/agentlens-reports")
)

fastapi = pytest.importorskip("fastapi")
from agentlens_cli import web  # noqa: E402


def _mk_report_html(finding_keys: list[tuple[str, str]]) -> str:
    """Build a report HTML containing the embedded findings-data JSON."""
    findings = [{"layer": layer, "title": title} for layer, title in finding_keys]
    data = json.dumps(findings, ensure_ascii=False).replace("</", "<\\/")
    return (
        f'<html><body><script id="findings-data" type="application/json">{data}</script></body></html>'
    )


def _mk_fixed(key: str, status: str = "marked_fixed", absent_streak: int = 0):
    entry = {"key": key, "status": status, "marked_time": "2026-09-01 00:00 UTC"}
    if absent_streak:
        entry["absent_streak"] = absent_streak
    return entry


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point web module's report/fixed-file paths at an isolated temp dir."""
    monkeypatch.setattr(web, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(web, "_FIXED_FILE", tmp_path / "fixed-findings.json")
    return tmp_path


class TestRegressionVerification:
    def test_present_marks_regressed(self, isolated):
        """marked_fixed finding that reappears -> reopened + regressed."""
        web._save_fixed_findings([_mk_fixed("graph|FINDING_A")])
        report = isolated / "r.html"
        report.write_text(_mk_report_html([("graph", "FINDING_A")]), encoding="utf-8")
        res = web._recheck_fixed_findings(str(report))
        assert res is not None
        assert res["reopened"] == 1
        assert res["regressed"] == 1
        data = web._load_fixed_findings()[0]
        assert data["status"] == "reopened"
        assert data["verify_status"] == "regressed"
        assert data["absent_streak"] == 0

    def test_first_absent_keeps_verifying(self, isolated):
        """First absence -> still marked_fixed, verify_status=verifying, streak=1."""
        web._save_fixed_findings([_mk_fixed("graph|FINDING_A")])
        report = isolated / "r.html"
        report.write_text(_mk_report_html([]), encoding="utf-8")
        res = web._recheck_fixed_findings(str(report))
        assert res["reopened"] == 0
        assert res["closed"] == 0  # 未到连续次数，不关闭
        data = web._load_fixed_findings()[0]
        assert data["status"] == "marked_fixed"
        assert data["verify_status"] == "verifying"
        assert data["absent_streak"] == 1

    def test_streak_reaches_required_verified(self, isolated):
        """Third consecutive absence -> closed + verified."""
        web._save_fixed_findings([_mk_fixed("graph|FINDING_A", absent_streak=2)])
        report = isolated / "r.html"
        report.write_text(_mk_report_html([]), encoding="utf-8")
        res = web._recheck_fixed_findings(str(report))
        assert res["closed"] == 1
        assert res["verified"] == 1
        data = web._load_fixed_findings()[0]
        assert data["status"] == "closed"
        assert data["verify_status"] == "verified"
        assert data["absent_streak"] == 3

    def test_closed_present_marks_regressed(self, isolated):
        """Closed finding that reappears -> reopened + regressed (防复发)."""
        web._save_fixed_findings([_mk_fixed("graph|FINDING_A", status="closed", absent_streak=3)])
        report = isolated / "r.html"
        report.write_text(_mk_report_html([("graph", "FINDING_A")]), encoding="utf-8")
        res = web._recheck_fixed_findings(str(report))
        assert res["reopened"] == 1
        assert res["regressed"] == 1
        data = web._load_fixed_findings()[0]
        assert data["status"] == "reopened"
        assert data["verify_status"] == "regressed"

    def test_closed_still_absent_stays_verified(self, isolated):
        """Closed finding that stays absent -> remains closed + verified."""
        web._save_fixed_findings([_mk_fixed("graph|FINDING_A", status="closed", absent_streak=3)])
        report = isolated / "r.html"
        report.write_text(_mk_report_html([]), encoding="utf-8")
        res = web._recheck_fixed_findings(str(report))
        assert res["reopened"] == 0
        assert res["closed"] == 0
        data = web._load_fixed_findings()[0]
        assert data["status"] == "closed"
        assert data["verify_status"] == "verified"

    def test_no_marked_returns_none(self, isolated):
        """No marked/closed entries -> None (no recheck needed)."""
        web._save_fixed_findings([])
        report = isolated / "r.html"
        report.write_text(_mk_report_html([]), encoding="utf-8")
        assert web._recheck_fixed_findings(str(report)) is None

    def test_verification_api_summary(self, isolated):
        """/api/findings/verification returns correct summary + entries."""
        from fastapi.testclient import TestClient
        client = TestClient(web.app)
        web._save_fixed_findings([
            _mk_fixed("graph|A", status="closed", absent_streak=3),  # verified (closed entry 但 verify_status 未设)
            _mk_fixed("graph|B", status="marked_fixed"),
            _mk_fixed("graph|C", status="reopened"),
        ])
        # 手动设置 verify_status（模拟复检后的状态）
        data = web._load_fixed_findings()
        data[0]["verify_status"] = "verified"
        data[1]["verify_status"] = "verifying"
        data[2]["verify_status"] = "regressed"
        web._save_fixed_findings(data)

        resp = client.get("/api/findings/verification")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"] == {"verified": 1, "verifying": 1, "regressed": 1}
        assert body["streak_required"] == web.VERIFY_STREAK_REQUIRED
        assert len(body["entries"]) == 3

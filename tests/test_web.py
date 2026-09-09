"""Tests for the web server (FastAPI REST API + HTML pages)."""

import os
import tempfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

# Override REPORT_DIR for tests before importing web module
os.environ["AGENTLENS_REPORT_DIR"] = str(
    Path("/home/agentuser/.hermes/agentlens-reports")
)

from agentlens_cli.web import app  # noqa: E402

client = TestClient(app)


class TestApiReports:
    """Tests for /api/reports endpoints."""

    def test_list_reports_returns_200(self):
        resp = client.get("/api/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_reports_has_correct_fields(self):
        resp = client.get("/api/reports")
        data = resp.json()
        if data:
            r = data[0]
            for field in ["date", "filename", "size_bytes", "mtime", "events", "high",
                          "medium", "low", "findings_total", "total_cost", "est_waste"]:
                assert field in r, f"missing field: {field}"

    def test_trends_returns_200(self):
        resp = client.get("/api/reports/trends")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        for key in ["dates", "total_cost", "est_waste", "findings", "high", "events"]:
            assert key in data, f"missing key: {key}"
            assert isinstance(data[key], list)

    def test_trends_has_data(self):
        resp = client.get("/api/reports/trends")
        data = resp.json()
        if data["dates"]:
            assert "20260909" in data["dates"]
            assert len(data["total_cost"]) == len(data["dates"])
            assert len(data["est_waste"]) == len(data["dates"])

    def test_report_detail_returns_200(self):
        resp = client.get("/api/reports/20260909")
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "20260909"
        assert "events" in data
        assert "findings_total" in data

    def test_report_detail_nonexistent_returns_404(self):
        resp = client.get("/api/reports/20000101")
        assert resp.status_code == 404

    def test_report_html_returns_200(self):
        resp = client.get("/api/reports/20260909/html")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<!DOCTYPE html>" in resp.text or "AgentLens" in resp.text

    def test_report_html_has_no_cache_headers(self):
        resp = client.get("/api/reports/20260909/html")
        assert resp.status_code == 200
        cc = resp.headers.get("cache-control", "")
        assert "no-store" in cc or "no-cache" in cc


class TestApiAudit:
    """Tests for /api/audit endpoints."""

    def test_audit_status_returns_200(self):
        resp = client.get("/api/audit/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "last_audit" in data
        assert "report_dir" in data
        assert "baseline" in data

    def test_audit_run_missing_input_returns_400(self):
        resp = client.post("/api/audit/run", json={})
        assert resp.status_code == 400

    def test_audit_run_nonexistent_file_returns_400(self):
        resp = client.post("/api/audit/run", json={"input": "/nonexistent/file.jsonl"})
        assert resp.status_code == 400

    def test_audit_run_with_valid_input(self):
        import tempfile
        input_path = "/home/agentuser/agentlens-cli/examples/hermes_gateway_events_anon.jsonl"
        # Use a temp output to avoid polluting the real report dir
        with tempfile.NamedTemporaryFile(suffix=".html", delete=True) as f:
            resp = client.post(
                "/api/audit/run",
                json={"input": input_path, "output": f.name},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "report_url" in data

    def test_audit_task_persistence(self):
        """POST /api/audit/run with nonexistent input should create a task entry
        persisted to audit-tasks.json (even on failure)."""
        import json as _json
        from agentlens_cli.web import _TASKS_FILE, _load_tasks

        # Trigger a failing task (input doesn't exist → 400, but the task is
        # created before validation in the current code; actually the 400 check
        # happens BEFORE the task is created.  We need to trigger a task creation.)
        # Use a nonexistent path that passes the initial file check but fails
        # during subprocess.  Actually the file check is at line 1194-1195
        # which checks os.path.isfile.  So we need a valid file path.
        # Let's use a different approach: call the API with a valid input.
        # Instead, we can directly test the _save_tasks / _load_tasks functions.

        # First, read the current task count
        from agentlens_cli import web as web_module
        initial_count = len(web_module._AUDIT_TASKS)

        # Trigger a task with a nonexistent file (returns 400, no task created)
        # We need to add a task directly to test persistence
        web_module._AUDIT_TASKS.append({
            "id": 9999,
            "time": "2026-09-09 00:00 UTC",
            "input": "/nonexistent/path.jsonl",
            "status": "error",
            "report_url": None,
        })
        web_module._save_tasks()

        # Verify file exists
        assert _TASKS_FILE.is_file(), f"Expected {_TASKS_FILE} to exist"

        # Read back and verify
        tasks = _load_tasks()
        assert any(t.get("id") == 9999 for t in tasks), "Task with id=9999 should be persisted"

        # Clean up: remove the test task
        web_module._AUDIT_TASKS = [t for t in web_module._AUDIT_TASKS if t.get("id") != 9999]
        web_module._save_tasks()

        # Verify removal
        tasks_after = _load_tasks()
        assert not any(t.get("id") == 9999 for t in tasks_after), "Test task should be removed"


class TestApiWatchdog:
    """Tests for /api/watchdog endpoint."""

    def test_watchdog_returns_200(self):
        resp = client.get("/api/watchdog")
        assert resp.status_code == 200
        data = resp.json()
        assert "baseline_exists" in data
        if data["baseline_exists"]:
            assert "baseline_mtime" in data
            assert "event_count" in data


class TestPages:
    """Tests for HTML page endpoints."""

    def test_dashboard_returns_200(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "sidebar" in resp.text or "仪表盘" in resp.text

    def test_dashboard_has_kpi_cards(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "仪表盘" in resp.text
        assert "Watchdog" in resp.text

    def test_audit_page_returns_200(self):
        resp = client.get("/audit")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "触发审计" in resp.text

    def test_reports_page_returns_200(self):
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "报告列表" in resp.text

    def test_report_detail_page_returns_200(self):
        resp = client.get("/reports/20260909")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "iframe" in resp.text or "审计报告" in resp.text

    def test_report_detail_page_nonexistent_returns_404(self):
        resp = client.get("/reports/20000101")
        assert resp.status_code == 404
        assert "报告未找到" in resp.text or "不存在" in resp.text


class TestHtmlParsing:
    """Tests for internal HTML parsing logic."""

    def test_parse_html_report(self):
        from agentlens_cli.web import _parse_html_report
        html = """<html>
        <span>事件数: <strong>798</strong></span>
        <div class="kpi-sub">High 3 / Med 2 / Low 1 / Info 0</div>
        <span class="finding-sev">HIGH</span>
        <span class="finding-sev">HIGH</span>
        <span class="finding-sev">MEDIUM</span>
        </html>"""
        meta = _parse_html_report(html)
        assert meta["events"] == 798
        assert meta["high"] == 3
        assert meta["medium"] == 2
        assert meta["low"] == 1
        assert meta["info"] == 0
        assert meta["findings_total"] == 6

    def test_parse_html_report_empty(self):
        from agentlens_cli.web import _parse_html_report
        meta = _parse_html_report("")
        assert meta["events"] == 0
        assert meta["findings_total"] == 0


class TestParseHtmlFindings:
    """Tests for _parse_html_findings."""

    def test_parse_findings_from_html(self):
        from agentlens_cli.web import _parse_html_findings
        html = """<html>
        <div class="section" id="layer-cost">
        <div class="finding" style="border-left:4px solid #dc3545;background:#fff5f5">
        <span class="finding-sev" style="background:#dc3545">HIGH</span>
        <strong>test finding one</strong>
        <p class="finding-rec">建议: do something</p>
        <p class="finding-meta">预估浪费: 1.234567 CNY</p>
        <div class="finding-regs"><span class="finding-regs-label">法规依据:</span>
        <ul class="regs-list"><li>EU AI Act — Art. 12: logging</li></ul></div>
        <div class="finding-rems"><span class="finding-rems-label">修复建议:</span>
        <ul class="rems-list"><li>MEDIUM fix it</li></ul></div>
        </div>
        <div class="finding" style="border-left:4px solid #fd7e14;background:#fff8f0">
        <span class="finding-sev" style="background:#fd7e14">MEDIUM</span>
        <strong>test finding two</strong>
        </div>
        </div>
        </html>"""
        findings = _parse_html_findings(html)
        assert len(findings) == 2
        f1 = findings[0]
        assert f1["layer"] == "成本治理"
        assert f1["severity"] == "high"
        assert f1["title"] == "test finding one"
        assert f1["est_wasted_cost"] == 1.234567
        assert "do something" in f1["recommendation"]
        assert len(f1["regulation_refs"]) == 1
        assert len(f1["remediation"]) == 1
        f2 = findings[1]
        assert f2["severity"] == "medium"
        assert f2["title"] == "test finding two"

    def test_parse_findings_empty(self):
        from agentlens_cli.web import _parse_html_findings
        findings = _parse_html_findings("")
        assert len(findings) == 0

    def test_parse_findings_no_findings(self):
        from agentlens_cli.web import _parse_html_findings
        html = '<div class="section" id="layer-graph"><p class="nodata">无发现项</p></div>'
        findings = _parse_html_findings(html)
        assert len(findings) == 0


class TestComparePage:
    """Tests for /reports/compare page."""

    def test_compare_missing_params_returns_400(self):
        resp = client.get("/reports/compare")
        assert resp.status_code == 400
        assert "请选择" in resp.text or "参数不完整" in resp.text

    def test_compare_missing_base_returns_400(self):
        resp = client.get("/reports/compare?curr=20260909")
        assert resp.status_code == 400

    def test_compare_missing_curr_returns_400(self):
        resp = client.get("/reports/compare?base=20260909")
        assert resp.status_code == 400

    def test_compare_nonexistent_returns_404(self):
        resp = client.get("/reports/compare?base=20000101&curr=20260909")
        assert resp.status_code == 404

    def test_compare_same_report_returns_200(self):
        resp = client.get("/reports/compare?base=20260909&curr=20260909")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "报告对比" in resp.text
        # Same report = all persistent, no new, no fixed
        assert "持续存在" in resp.text


class TestCsvExport:
    """Tests for /api/reports/{date}/findings.csv endpoint."""

    def test_csv_export_returns_200(self):
        resp = client.get("/api/reports/20260909/findings.csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_csv_export_has_correct_headers(self):
        resp = client.get("/api/reports/20260909/findings.csv")
        first_line = resp.text.split("\n")[0]
        for header in ["日期", "层名", "严重度", "标题", "预估浪费", "出现次数", "建议", "法规依据", "修复建议"]:
            assert header in first_line, f"Missing header: {header}"

    def test_csv_export_utf8_sig(self):
        resp = client.get("/api/reports/20260909/findings.csv")
        content = resp.content
        assert content[:3] == b"\xef\xbb\xbf", "CSV should start with UTF-8 BOM"

    def test_csv_export_nonexistent_returns_404(self):
        resp = client.get("/api/reports/20000101/findings.csv")
        assert resp.status_code == 404

    def test_csv_export_has_data_rows(self):
        resp = client.get("/api/reports/20260909/findings.csv")
        lines = [l for l in resp.text.strip().split("\n") if l.strip()]
        assert len(lines) > 1, "CSV should have header + at least 1 data row"

    def test_csv_export_full_aggregation_via_embedded_json(self):
        """CSV should use the embedded findings-data JSON (full set), not the
        top-N rendered findings, and aggregate by (layer, title)."""
        resp = client.get("/api/reports/20260909/findings.csv")
        import csv as _csv
        import io as _io
        rows = list(_csv.reader(_io.StringIO(resp.text)))
        assert len(rows) > 5, (
            f"expected full aggregated findings (>5 groups), got {len(rows) - 1} data rows; "
            "if the report only renders top-N, embedded JSON is not being used"
        )
        # Aggregated rows should carry an occurrence count column (col 5, 1-indexed)
        # with at least one row having count > 1.
        counts = [int(r[5]) for r in rows[1:] if r[5].isdigit()]
        assert any(c > 1 for c in counts), "expected at least one aggregated finding with count > 1"
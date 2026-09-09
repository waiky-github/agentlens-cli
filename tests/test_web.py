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
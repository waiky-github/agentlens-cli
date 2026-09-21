"""Tests for weekly_report.py — offline, no network.

Uses fixture drift-history.json and fake audit HTML reports to verify
the trend report generation logic.
"""

import json
import os
import sys
from datetime import datetime, timedelta

# Ensure scripts directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import weekly_report  # noqa: E402


def _make_fake_html(findings_list, out_path):
    """Write a minimal audit HTML with embedded findings JSON."""
    data_json = json.dumps(findings_list, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html><head><title>Test</title></head><body>
<script id="findings-data" type="application/json">{data_json}</script>
</body></html>"""
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


class TestParseFindingsFromHtml:
    def test_extracts_findings(self, tmp_path):
        findings = [
            {"severity": "high", "title": "test-high", "est_wasted_cost": 5.0},
            {"severity": "medium", "title": "test-med", "est_wasted_cost": 2.0},
            {"severity": "low", "title": "test-low", "est_wasted_cost": 0.5},
        ]
        path = str(tmp_path / "audit-20260910.html")
        _make_fake_html(findings, path)

        result, err = weekly_report._parse_findings_from_html(path)
        assert err is None
        assert len(result) == 3
        assert result[0]["title"] == "test-high"

    def test_missing_file(self):
        result, err = weekly_report._parse_findings_from_html("/nonexistent/path.html")
        assert result is None
        assert err is not None

    def test_no_findings_data_tag(self, tmp_path):
        path = str(tmp_path / "empty.html")
        with open(path, "w") as f:
            f.write("<html><body>no data here</body></html>")
        result, err = weekly_report._parse_findings_from_html(path)
        assert result is None
        assert "未找到 findings-data" in err

    def test_malformed_json(self, tmp_path):
        path = str(tmp_path / "bad.html")
        with open(path, "w") as f:
            f.write('<script id="findings-data" type="application/json">{bad</script>')
        result, err = weekly_report._parse_findings_from_html(path)
        assert result is None
        assert "JSON 解析失败" in err


class TestFindingsStats:
    def test_counts_and_wasted(self):
        findings = [
            {"severity": "high", "est_wasted_cost": 10.0},
            {"severity": "high", "est_wasted_cost": 20.0},
            {"severity": "medium", "est_wasted_cost": 5.0},
            {"severity": "info", "est_wasted_cost": 1.0},
            {"severity": "info", "est_wasted_cost": None},  # None → 0
        ]
        stats = weekly_report._findings_stats(findings)
        assert stats["total"] == 5
        assert stats["high"] == 2
        assert stats["medium"] == 1
        assert stats["est_wasted_cost"] == 36.0

    def test_empty_findings(self):
        stats = weekly_report._findings_stats([])
        assert stats["total"] == 0
        assert stats["high"] == 0
        assert stats["medium"] == 0
        assert stats["est_wasted_cost"] == 0


class TestTopNWasted:
    def test_top_3(self):
        findings = [
            {"title": "a", "est_wasted_cost": 1.0},
            {"title": "b", "est_wasted_cost": 100.0},
            {"title": "c", "est_wasted_cost": 50.0},
            {"title": "d", "est_wasted_cost": 75.0},
            {"title": "e", "est_wasted_cost": None},
        ]
        top = weekly_report._top_n_wasted(findings, 3)
        assert len(top) == 3
        assert top[0][0]["title"] == "b"
        assert top[0][1] == 100.0
        assert top[1][0]["title"] == "d"
        assert top[2][0]["title"] == "c"

    def test_fewer_than_n(self):
        findings = [{"title": "only", "est_wasted_cost": 5.0}]
        top = weekly_report._top_n_wasted(findings, 3)
        assert len(top) == 1


class TestLoadDriftHistory:
    def test_loads_and_sorts(self, tmp_path):
        path = str(tmp_path / "reports" / "drift-history.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        records = [
            {"date": "2026-09-13", "high_total": 5},
            {"date": "2026-09-11", "high_total": 3},
            {"date": "2026-09-12", "high_total": 4},
        ]
        with open(path, "w") as f:
            json.dump(records, f)

        with patch_report_dir(tmp_path):
            history = weekly_report._load_drift_history()
            dates = [r["date"] for r in history]
            assert dates == ["2026-09-11", "2026-09-12", "2026-09-13"]

    def test_missing_file_returns_empty(self, tmp_path):
        with patch_report_dir(tmp_path):
            history = weekly_report._load_drift_history()
            assert history == []


class TestWeeklyReportFormat:
    def test_full_report_with_data(self, tmp_path):
        """Build a complete weekly report with drift history and audit HTMLs."""
        reports_dir = str(tmp_path / "reports")
        os.makedirs(reports_dir, exist_ok=True)

        # Create drift history for 3 days
        drift_path = os.path.join(reports_dir, "drift-history.json")
        drift_records = [
            {"date": "2026-09-11", "new_high": 0, "high_total": 3, "has_new_high": False},
            {"date": "2026-09-12", "new_high": 2, "high_total": 5, "has_new_high": True},
            {"date": "2026-09-13", "new_high": 0, "high_total": 5, "has_new_high": False},
        ]
        with open(drift_path, "w") as f:
            json.dump(drift_records, f)

        # Create 3 audit HTMLs
        _make_fake_html(
            [{"severity": "high", "title": "h1", "est_wasted_cost": 10.0},
             {"severity": "medium", "title": "m1", "est_wasted_cost": 5.0}],
            os.path.join(reports_dir, "audit-20260911.html"),
        )
        _make_fake_html(
            [{"severity": "high", "title": "h1", "est_wasted_cost": 10.0},
             {"severity": "high", "title": "h2", "est_wasted_cost": 50.0},
             {"severity": "medium", "title": "m1", "est_wasted_cost": 5.0}],
            os.path.join(reports_dir, "audit-20260912.html"),
        )
        _make_fake_html(
            [{"severity": "high", "title": "h1", "est_wasted_cost": 10.0},
             {"severity": "high", "title": "h2", "est_wasted_cost": 50.0},
             {"severity": "info", "title": "info1", "est_wasted_cost": None}],
            os.path.join(reports_dir, "audit-20260913.html"),
        )

        # We need a fixed date range to match our fixtures
        start = datetime(2026, 9, 11)
        end = datetime(2026, 9, 13)
        dates = weekly_report._gen_date_list(start, end)

        daily_audit = {}
        for date_str in dates:
            date_compact = date_str.replace("-", "")
            html_path = os.path.join(reports_dir, f"audit-{date_compact}.html")
            if os.path.isfile(html_path):
                findings, err = weekly_report._parse_findings_from_html(html_path)
                if findings is not None:
                    stats = weekly_report._findings_stats(findings)
                    stats["top_findings"] = weekly_report._top_n_wasted(findings, 3)
                    daily_audit[date_str] = stats
                else:
                    daily_audit[date_str] = None
            else:
                daily_audit[date_str] = None

        with patch_report_dir_string(reports_dir):
            drift_history = weekly_report._load_drift_history()

        text = weekly_report._format_report(dates, daily_audit, drift_history, start, end)

        assert "agentlens 审计趋势周报" in text
        assert "2026-09-11 ~ 2026-09-13" in text
        assert "每日审计 Findings 趋势" in text
        assert "2026-09-11" in text
        assert "漂移趋势" in text
        assert "最贵浪费发现" in text
        assert "一周小结" in text
        assert "日均" in text  # findings: 2/3/2 → 日均 2.3（不再用首尾端点对比）

    def test_report_with_missing_dates(self, tmp_path):
        """Report gracefully handles missing audit HTML files."""
        reports_dir = str(tmp_path / "reports")
        os.makedirs(reports_dir, exist_ok=True)

        drift_path = os.path.join(reports_dir, "drift-history.json")
        with open(drift_path, "w") as f:
            json.dump([{"date": "2026-09-12", "new_high": 1, "high_total": 3}], f)

        # Only one day has data
        _make_fake_html(
            [{"severity": "high", "title": "h1", "est_wasted_cost": 10.0}],
            os.path.join(reports_dir, "audit-20260912.html"),
        )

        start = datetime(2026, 9, 11)
        end = datetime(2026, 9, 13)
        dates = weekly_report._gen_date_list(start, end)

        daily_audit = {}
        for date_str in dates:
            date_compact = date_str.replace("-", "")
            html_path = os.path.join(reports_dir, f"audit-{date_compact}.html")
            if os.path.isfile(html_path):
                findings, err = weekly_report._parse_findings_from_html(html_path)
                if findings is not None:
                    stats = weekly_report._findings_stats(findings)
                    stats["top_findings"] = weekly_report._top_n_wasted(findings, 3)
                    daily_audit[date_str] = stats
                else:
                    daily_audit[date_str] = None
            else:
                daily_audit[date_str] = None

        with patch_report_dir_string(reports_dir):
            drift_history = weekly_report._load_drift_history()

        text = weekly_report._format_report(dates, daily_audit, drift_history, start, end)

        assert "无报告" in text  # 09-11 and 09-13
        assert "无数据" in text  # drift history missing for 09-11


def patch_report_dir(tmp_path):
    """Temporarily override REPORT_DIR to use tmp_path."""
    import weekly_report as wr
    return _patch_attr(wr, "REPORT_DIR", str(tmp_path / "reports"))


def patch_report_dir_string(reports_dir_str):
    """Temporarily override REPORT_DIR to a string path."""
    import weekly_report as wr
    return _patch_attr(wr, "REPORT_DIR", reports_dir_str)


def _patch_attr(module, attr, value):
    """Context manager to temporarily set a module attribute."""
    import contextlib
    original = getattr(module, attr)
    setattr(module, attr, value)

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        finally:
            setattr(module, attr, original)

    return _ctx()


class TestWeeklyDateRange:
    def test_returns_seven_days(self):
        start, end = weekly_report._weekly_date_range(7)
        delta = (end - start).days
        assert delta == 6  # 7 days inclusive: start, start+1, ..., end


class TestGenDateList:
    def test_inclusive_range(self):
        start = datetime(2026, 9, 10)
        end = datetime(2026, 9, 13)
        dates = weekly_report._gen_date_list(start, end)
        assert dates == ["2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13"]

    def test_single_day(self):
        d = datetime(2026, 9, 14)
        dates = weekly_report._gen_date_list(d, d)
        assert dates == ["2026-09-14"]
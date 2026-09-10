"""Tests for watchdog drift history (2026-09-10, O2 漂移趋势历史)."""

import json

from agentlens_cli.watchdog import (
    append_drift_history,
    build_drift_record,
    load_drift_history,
    run_watchdog,
)


def _sample_result(high=2, medium=1, cost=1.5, closure=0.8, events=100):
    return {
        "events_loaded": events,
        "graph": {
            "nodes": [],
            "edges": [],
            "metrics": {"closure_rate": closure},
            "findings": [{"title": "g1", "severity": "high"}] * high,
        },
        "decision": {"findings": [{"title": "d1", "severity": "medium"}] * medium},
        "evidence": {"findings": []},
        "cost": {
            "total_cost": cost,
            "findings": [{"title": "c1", "severity": "low"}],
        },
        "shadow": {"findings": []},
        "compliance": {"findings": []},
    }


class TestBuildDriftRecord:
    def test_record_fields_from_audit(self):
        result = _sample_result(high=2, medium=1, cost=1.5, closure=0.8, events=100)
        wd = run_watchdog(result, _sample_result(high=1, medium=0))
        record = build_drift_record("2026-09-10", result, wd, events_loaded=100)
        assert record["date"] == "2026-09-10"
        assert record["events_loaded"] == 100
        # graph 2 high + decision 1 medium + cost 1 low = 4
        assert record["findings_total"] == 4
        assert record["high_total"] == 2
        assert record["cost_total"] == 1.5
        assert record["closure_rate"] == 0.8

    def test_record_new_high_from_watchdog(self):
        baseline = _sample_result(high=0, medium=0)
        current = _sample_result(high=3, medium=2)
        wd = run_watchdog(current, baseline)
        record = build_drift_record("2026-09-10", current, wd)
        assert record["new_high"] == 1  # (graph,g1,high) 整 key 新增
        assert record["growing_high"] == 0
        assert record["has_new_high"] is True

    def test_record_growing_high(self):
        # 同一 key 从 1 涨到 5 —— growing_high 捕获数量增长
        baseline = _sample_result(high=1, medium=0)
        current = _sample_result(high=5, medium=0)
        wd = run_watchdog(current, baseline)
        record = build_drift_record("2026-09-10", current, wd)
        assert record["growing_high"] == 1
        assert record["has_new_high"] is True


class TestDriftHistoryIO:
    def test_append_and_load(self, tmp_path):
        path = tmp_path / "drift-history.json"
        r1 = {"date": "2026-09-09", "high_total": 3, "has_new_high": False}
        r2 = {"date": "2026-09-10", "high_total": 4, "has_new_high": True}
        append_drift_history(path, r1)
        append_drift_history(path, r2)
        history = load_drift_history(path)
        assert [h["date"] for h in history] == ["2026-09-09", "2026-09-10"]
        assert path.exists()

    def test_same_date_overwrites(self, tmp_path):
        path = tmp_path / "drift-history.json"
        append_drift_history(path, {"date": "2026-09-10", "high_total": 2})
        append_drift_history(path, {"date": "2026-09-10", "high_total": 5})
        history = load_drift_history(path)
        assert len(history) == 1
        assert history[0]["high_total"] == 5

    def test_sort_oldest_first(self, tmp_path):
        path = tmp_path / "drift-history.json"
        append_drift_history(path, {"date": "2026-09-11", "high_total": 1})
        append_drift_history(path, {"date": "2026-09-09", "high_total": 2})
        history = load_drift_history(path)
        assert [h["date"] for h in history] == ["2026-09-09", "2026-09-11"]

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_drift_history(tmp_path / "nope.json") == []

    def test_load_corrupt_returns_empty(self, tmp_path):
        path = tmp_path / "drift-history.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_drift_history(path) == []

    def test_roundtrip_via_build_record(self, tmp_path):
        path = tmp_path / "drift-history.json"
        current = _sample_result(high=2)
        wd = run_watchdog(current, _sample_result(high=1))
        record = build_drift_record("2026-09-10", current, wd, events_loaded=99)
        append_drift_history(path, record)
        loaded = load_drift_history(path)
        assert loaded[0]["date"] == "2026-09-10"
        assert loaded[0]["events_loaded"] == 99

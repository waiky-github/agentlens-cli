"""Tests for cost budget alerting (budget.py, task 4 2026-09-10)."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentlens_cli.budget import (  # noqa: E402
    append_budget_alert,
    check_budget,
    format_budget_alert_body,
    load_budget_alerts,
    load_budget_config,
)


def _result(total_cost=50.0, est_waste=10.0, events=100):
    return {
        "events_loaded": events,
        "cost": {
            "total_cost": total_cost,
            "total_est_wasted_cost": est_waste,
            "avoidable_cost_ratio": est_waste / total_cost if total_cost else 0.0,
        },
    }


def _cfg(total_cost_limit=None, est_waste_limit=None, enabled=True):
    out = {"enabled": enabled}
    if total_cost_limit is not None:
        out["total_cost_limit"] = total_cost_limit
    if est_waste_limit is not None:
        out["est_waste_limit"] = est_waste_limit
    return out


class TestCheckBudget:
    def test_no_budget_cfg_no_alert(self):
        res = check_budget(_result(), budget_cfg={})
        assert res == {"triggered": False, "alerts": []}

    def test_disabled_no_alert(self):
        res = check_budget(_result(total_cost=999), budget_cfg=_cfg(enabled=False))
        assert res["triggered"] is False

    def test_total_cost_over_limit(self):
        res = check_budget(_result(total_cost=150), budget_cfg=_cfg(total_cost_limit=100))
        assert res["triggered"] is True
        assert len(res["alerts"]) == 1
        assert res["alerts"][0]["kind"] == "total_cost"
        assert res["alerts"][0]["actual"] == 150.0

    def test_est_waste_over_limit(self):
        res = check_budget(_result(est_waste=60), budget_cfg=_cfg(est_waste_limit=50))
        assert res["triggered"] is True
        assert res["alerts"][0]["kind"] == "est_waste"

    def test_both_over_limit_two_alerts(self):
        res = check_budget(
            _result(total_cost=200, est_waste=100),
            budget_cfg=_cfg(total_cost_limit=100, est_waste_limit=50),
        )
        assert res["triggered"] is True
        assert len(res["alerts"]) == 2

    def test_under_limit_no_alert(self):
        res = check_budget(
            _result(total_cost=80, est_waste=30),
            budget_cfg=_cfg(total_cost_limit=100, est_waste_limit=50),
        )
        assert res["triggered"] is False

    def test_zero_limits_ignored(self):
        # 阈值 0 / 负数视为未配置
        res = check_budget(_result(total_cost=999), budget_cfg=_cfg(total_cost_limit=0))
        assert res["triggered"] is False


class TestBudgetConfig:
    def test_load_from_notify_config(self, tmp_path):
        """budget field in notify-config.json is honored."""
        (tmp_path / "notify-config.json").write_text(
            json.dumps({
                "enabled": True,
                "channels": [],
                "budget": {"enabled": True, "total_cost_limit": 88.5},
            }),
            encoding="utf-8",
        )
        cfg = load_budget_config(tmp_path)
        assert cfg["enabled"] is True
        assert cfg["total_cost_limit"] == 88.5

    def test_missing_budget_returns_empty(self, tmp_path):
        (tmp_path / "notify-config.json").write_text(
            json.dumps({"enabled": True, "channels": []}),
            encoding="utf-8",
        )
        assert load_budget_config(tmp_path) == {}

    def test_no_file_returns_empty(self, tmp_path):
        assert load_budget_config(tmp_path) == {}

    def test_budget_disabled_returns_empty(self, tmp_path):
        (tmp_path / "notify-config.json").write_text(
            json.dumps({"budget": {"enabled": False, "total_cost_limit": 100}}),
            encoding="utf-8",
        )
        assert load_budget_config(tmp_path) == {}


class TestFormatBody:
    def test_body_contains_cost_and_alert(self):
        body = format_budget_alert_body(
            _result(total_cost=200, est_waste=100, events=500),
            [
                {"kind": "total_cost", "limit": 100.0, "actual": 200.0,
                 "message": "本次审计总成本 200.00 元 超过预算 100.00 元"},
            ],
        )
        assert "200.00" in body
        assert "500" in body
        assert "超过预算" in body


class TestBudgetAlertHistory:
    def test_append_and_load(self, tmp_path):
        result = _result(total_cost=200, est_waste=80, events=300)
        alerts = [{"kind": "total_cost", "limit": 100.0, "actual": 200.0, "message": "超 budget"}]
        history = append_budget_alert(result, alerts, tmp_path)
        assert len(history) == 1
        assert history[0]["total_cost"] == 200.0
        assert history[0]["events_loaded"] == 300

        loaded = load_budget_alerts(tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["alerts"][0]["kind"] == "total_cost"

    def test_multiple_appends_accumulate(self, tmp_path):
        r1 = _result(total_cost=120)
        r2 = _result(total_cost=180)
        append_budget_alert(r1, [{"kind": "total_cost", "limit": 100, "actual": 120, "message": ""}], tmp_path)
        append_budget_alert(r2, [{"kind": "total_cost", "limit": 100, "actual": 180, "message": ""}], tmp_path)
        loaded = load_budget_alerts(tmp_path, limit=10)
        assert len(loaded) == 2
        # newest first
        assert loaded[0]["total_cost"] == 180.0
        assert loaded[1]["total_cost"] == 120.0

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_budget_alerts(tmp_path) == []

    def test_load_corrupt_returns_empty(self, tmp_path):
        path = tmp_path / "budget-alerts.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_budget_alerts(tmp_path) == []

    def test_limit_caps_results(self, tmp_path):
        for i in range(5):
            append_budget_alert(_result(total_cost=100 + i), [{"kind": "x", "limit": 0, "actual": 0, "message": ""}], tmp_path)
        assert len(load_budget_alerts(tmp_path, limit=2)) == 2

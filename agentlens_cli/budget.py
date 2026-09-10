"""Cost budget alerting for AgentLens audit runs.

任务4（2026-09-10）：审计 run 后检查成本/浪费是否超过预算阈值，超限则触发通知。

阈值配置在 notify-config.json 的 `budget` 字段（与通知通道同文件）:
{
  "enabled": true,
  "channels": [...],
  "budget": {
    "enabled": true,
    "total_cost_limit": 100.0,   # 单次审计总成本阈值（元），> 触发告警
    "est_waste_limit": 50.0      # 单次预估浪费阈值（元），> 触发告警
  }
}

不配置 budget 或 budget.enabled=false → 不告警（零侵入）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def _default_report_dir() -> Path:
    return Path(
        os.environ.get(
            "AGENTLENS_REPORT_DIR",
            os.path.expanduser("~/.hermes/agentlens-reports"),
        )
    )


def load_budget_config(report_dir: Optional[Path] = None) -> dict:
    """Load the budget alert config from notify-config.json's `budget` field.

    Returns {} if absent/disabled — callers treat empty as "no alerting".
    """
    if report_dir is None:
        report_dir = _default_report_dir()
    try:
        data = json.loads((report_dir / "notify-config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    budget = data.get("budget") if isinstance(data, dict) else None
    if not isinstance(budget, dict) or not budget.get("enabled", False):
        return {}
    out: dict = {"enabled": True}
    for key in ("total_cost_limit", "est_waste_limit"):
        val = budget.get(key)
        if isinstance(val, (int, float)) and val > 0:
            out[key] = float(val)
    return out


def check_budget(result: dict, budget_cfg: Optional[dict] = None) -> dict:
    """Check an audit result against budget thresholds.

    Returns {"triggered": bool, "alerts": [ {kind, limit, actual, message} ]}.
    budget_cfg=None → loads from notify-config.json budget field.
    """
    if budget_cfg is None:
        budget_cfg = load_budget_config()
    if not budget_cfg.get("enabled"):
        return {"triggered": False, "alerts": []}

    cost = result.get("cost", {}) or {}
    total_cost = cost.get("total_cost", 0.0) or 0.0
    est_waste = cost.get("total_est_wasted_cost", 0.0) or 0.0

    alerts = []
    limit = budget_cfg.get("total_cost_limit")
    if limit and total_cost > limit:
        alerts.append({
            "kind": "total_cost",
            "limit": limit,
            "actual": total_cost,
            "message": f"本次审计总成本 {total_cost:.2f} 元 超过预算 {limit:.2f} 元",
        })
    limit = budget_cfg.get("est_waste_limit")
    if limit and est_waste > limit:
        alerts.append({
            "kind": "est_waste",
            "limit": limit,
            "actual": est_waste,
            "message": f"本次审计预估浪费 {est_waste:.2f} 元 超过预算 {limit:.2f} 元",
        })

    return {"triggered": bool(alerts), "alerts": alerts}


def format_budget_alert_body(result: dict, alerts: list[dict]) -> str:
    """Build a human-readable notification body for budget alerts."""
    cost = result.get("cost", {}) or {}
    lines = [
        "🚨 AgentLens 成本预算告警",
        "",
        f"- 事件数: {result.get('events_loaded', 0)}",
        f"- 总成本: {cost.get('total_cost', 0.0):.2f} 元",
        f"- 预估浪费: {cost.get('total_est_wasted_cost', 0.0):.2f} 元",
        f"- 可避免占比: {cost.get('avoidable_cost_ratio', 0.0):.1%}",
        "",
        "超限项:",
    ]
    for a in alerts:
        lines.append(f"- {a['message']}")
    return "\n".join(lines)

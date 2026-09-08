"""持续审计 / 漂移监控（watchdog）：对比当前审计结果与基线，发现新问题漂移。

企业需要定期复检，而不是一次性审计。本模块基于现有 diff 能力做持续化包装。
"""

from collections import defaultdict


def run_watchdog(current_result: dict, baseline: dict) -> dict:
    """对比当前审计结果与基线，输出变更摘要。

    Args:
        current_result: 当前审计结果 dict（含各层 findings）
        baseline: 基线审计结果 dict（含各层 findings）

    Returns:
        dict: {
            new_findings: list[dict] — baseline 无而 current 新增的 finding 明细
            resolved_findings: list[dict] — baseline 有而 current 消失的 finding 明细
            changed_counts: dict — 各层各 title 计数变化
            summary: dict — 新增 high/medium 数、High 数量增长数、解决 high 数、成本变化、closure_rate 变化
            has_new_high: bool — 存在新增 high severity finding，或已有 high finding 数量增长
        }
    """
    layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]

    def _collect_findings(result: dict) -> list[dict]:
        """收集所有层级的所有 finding。"""
        findings = []
        for key in layer_keys:
            layer = result.get(key, {})
            if isinstance(layer, dict):
                for f in layer.get("findings", []):
                    findings.append({
                        "layer": key,
                        "title": f.get("title", ""),
                        "severity": f.get("severity", "info"),
                    })
        return findings

    def _count_keyed(findings: list[dict]) -> dict:
        """按 (layer, title, severity) 三元组聚合计数。"""
        counts = defaultdict(int)
        for f in findings:
            key = (f["layer"], f["title"], f["severity"])
            counts[key] += 1
        return dict(counts)

    baseline_findings = _collect_findings(baseline)
    current_findings = _collect_findings(current_result)

    baseline_counts = _count_keyed(baseline_findings)
    current_counts = _count_keyed(current_findings)

    # 构建按 key 的明细集合
    baseline_keys = set(baseline_counts.keys())
    current_keys = set(current_counts.keys())

    # 新增的 key
    new_keys = current_keys - baseline_keys
    # 消失的 key
    resolved_keys = baseline_keys - current_keys

    new_findings = []
    for key in sorted(new_keys):
        count = current_counts[key]
        new_findings.append({
            "layer": key[0],
            "title": key[1],
            "severity": key[2],
            "count_delta": count,
        })

    resolved_findings = []
    for key in sorted(resolved_keys):
        count = baseline_counts[key]
        resolved_findings.append({
            "layer": key[0],
            "title": key[1],
            "severity": key[2],
            "count_delta": -count,
        })

    # 计数变化（含同一 key 的数量变化）
    changed_counts = {}
    all_keys = baseline_keys | current_keys
    for key in sorted(all_keys):
        b_count = baseline_counts.get(key, 0)
        c_count = current_counts.get(key, 0)
        delta = c_count - b_count
        if delta != 0:
            changed_counts[f"{key[0]}/{key[1]}/{key[2]}"] = {
                "baseline": b_count,
                "current": c_count,
                "delta": delta,
            }

    # 汇总
    new_high = sum(1 for f in new_findings if f["severity"] == "high")
    new_medium = sum(1 for f in new_findings if f["severity"] == "medium")
    resolved_high = sum(1 for f in resolved_findings if f["severity"] == "high")

    # 数量增长的 high：已有 (layer,title,severity) 的计数变大 —— 同样是高风险漂移，
    # 漏掉会让「unauthorized tool calls 从 5 涨到 20」这类最常见漂移不报警。
    growing_high = sum(
        1 for key, cc in changed_counts.items()
        if key.endswith("/high") and cc["delta"] > 0
    )

    b_cost = baseline.get("cost", {}).get("total_cost", 0)
    c_cost = current_result.get("cost", {}).get("total_cost", 0)
    cost_change = round(c_cost - b_cost, 6)

    b_closure = baseline.get("graph", {}).get("metrics", {}).get("closure_rate", 0)
    c_closure = current_result.get("graph", {}).get("metrics", {}).get("closure_rate", 0)
    closure_change = round(c_closure - b_closure, 4)

    summary = {
        "new_high": new_high,
        "growing_high": growing_high,
        "new_medium": new_medium,
        "resolved_high": resolved_high,
        "cost_change": cost_change,
        "closure_rate_change": closure_change,
    }

    return {
        "new_findings": new_findings,
        "resolved_findings": resolved_findings,
        "changed_counts": changed_counts,
        "summary": summary,
        "has_new_high": (new_high + growing_high) > 0,
    }
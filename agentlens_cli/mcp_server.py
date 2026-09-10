"""MCP Server for AgentLens Audit —— 把七层审计能力暴露为标准 MCP 工具。

工具:
  - audit(events_path)          : 完整七层审计，返回 JSON（含 integrity 块）
  - cost_analysis(events_path)  : 成本分析（总成本/可避免成本/比例）
  - verify_report(report_path)  : 验报告完整性（防篡改哈希链）
  - list_regulations(title_filter) : 法规映射查询
  - watchdog_status()           : watchdog 漂移监控状态（基线/最近报告）（2026-09-10）
  - remediation_lookup(title)   : 查询 finding 的修复建议（2026-09-10）
  - fix_tracking_status()       : 修复跟踪 + 回归验证状态（2026-09-10）

传输方式:
  stdio（默认）: 标准 MCP 客户端进程内接入
      python -m agentlens_cli.mcp_server
  http（可选） : streamable-http 远程接入
      python -m agentlens_cli.mcp_server --transport http --port 8765 --host 127.0.0.1
      客户端连接 http://127.0.0.1:8765/mcp
"""

import argparse
import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .__main__ import _load_events, _run_audit_for_diff
from .attribution import attribute_costs
from .config import CostModel
from .governance import detect_waste
from .integrity import build_integrity_block, verify_report as _verify_report
from .regulations import list_regulations as _list_regulations
from .remediation import _lookup_remediations

mcp = MCPServer("agentlens-audit")


@mcp.tool()
def audit(events_path: str) -> str:
    """对事件流文件执行完整七层审计（协作图谱、决策审计、证据链、成本治理、影子智能体、决策权限合规、法规映射）。

    参数:
        events_path: 事件流文件路径（JSONL / JSON / gateway.log）

    返回:
        JSON 字符串，包含七层审计结果 + integrity 防篡改哈希块。
        格式: {"events_loaded": N, "graph": {...}, "decision": {...}, "evidence": {...},
               "cost": {...}, "shadow": {...}, "compliance": {...}, "integrity": {...}}
    """
    try:
        if not os.path.isfile(events_path):
            return json.dumps({"error": f"文件不存在: {events_path}"}, ensure_ascii=False)

        events = _load_events(events_path)
        if not events:
            return json.dumps({"error": f"未能从文件解析到事件: {events_path}"}, ensure_ascii=False)

        result = _run_audit_for_diff(events)
        result["integrity"] = build_integrity_block(result)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"审计失败: {exc}"}, ensure_ascii=False)


@mcp.tool()
def cost_analysis(events_path: str) -> str:
    """对事件流执行成本分析：总成本、可避免成本、可避免比例。

    参数:
        events_path: 事件流文件路径（JSONL / JSON / gateway.log）

    返回:
        JSON 字符串，包含 total_cost / total_est_wasted_cost / avoidable_cost_ratio / cost_by_agent / findings 等。
    """
    try:
        if not os.path.isfile(events_path):
            return json.dumps({"error": f"文件不存在: {events_path}"}, ensure_ascii=False)

        events = _load_events(events_path)
        if not events:
            return json.dumps({"error": f"未能从文件解析到事件: {events_path}"}, ensure_ascii=False)

        cost_model = CostModel()
        cost_data = attribute_costs(events, cost_model)
        governance_data = detect_waste(events, cost_model)

        total_cost = cost_data["total_cost"]
        total_wasted = governance_data["total_est_wasted_cost"]
        avoidable_ratio = round(total_wasted / total_cost, 4) if total_cost > 0 else 0.0

        return json.dumps({
            "total_tokens_in": cost_data["total_tokens_in"],
            "total_tokens_out": cost_data["total_tokens_out"],
            "total_cost": total_cost,
            "total_est_wasted_cost": total_wasted,
            "avoidable_cost_ratio": avoidable_ratio,
            "cost_by_agent": cost_data["cost_by_agent"],
            "cost_model": cost_data["cost_model"],
            "findings": governance_data["findings"],
            "events_loaded": len(events),
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"成本分析失败: {exc}"}, ensure_ascii=False)


@mcp.tool()
def verify_report(report_path: str) -> str:
    """验证 HTML 审计报告的完整性（防篡改哈希链校验）。

    参数:
        report_path: HTML 审计报告文件路径

    返回:
        JSON 字符串，包含 verified(bool) / reason(str) / expected(str) / actual(str) / document_hash / content_hash。
    """
    try:
        if not os.path.isfile(report_path):
            return json.dumps({"error": f"文件不存在: {report_path}"}, ensure_ascii=False)

        with open(report_path, "r", encoding="utf-8") as fh:
            html = fh.read()

        res = _verify_report(html)
        return json.dumps(res, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"报告验证失败: {exc}"}, ensure_ascii=False)


@mcp.tool()
def list_regulations(title_filter: str | None = None) -> str:
    """查询法规映射。可选按 finding 标题过滤。

    参数:
        title_filter: 可选，按标题子串筛选（如 "shadow" 查询影子智能体相关法规）

    返回:
        JSON 字符串，每项含 title(str) + refs(list[dict])，每个 ref 含 regulation/article/clause/note 字段。
    """
    try:
        entries = _list_regulations(title_filter)
        return json.dumps(entries, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"法规查询失败: {exc}"}, ensure_ascii=False)


@mcp.tool()
def watchdog_status() -> str:
    """查询 watchdog 漂移监控状态：基线文件是否存在、最近审计报告、基线成本/事件摘要。

    无参数。返回 JSON：baseline_found / baseline（written_at, events, total_cost, findings 数）/
    latest_report（date, size_bytes）/ reports_total。
    """
    report_dir = Path(
        os.environ.get(
            "AGENTLENS_REPORT_DIR",
            os.path.expanduser("~/.hermes/agentlens-reports"),
        )
    )
    info: dict = {}
    baseline_path = report_dir / "baseline.json"
    info["baseline_found"] = baseline_path.is_file()
    if baseline_path.is_file():
        try:
            bl = json.loads(baseline_path.read_text(encoding="utf-8"))
            cost = bl.get("cost", {}) or {}
            info["baseline"] = {
                "events": bl.get("events_loaded", 0),
                "total_cost": cost.get("total_cost", 0.0),
                "est_waste": cost.get("total_est_wasted_cost", 0.0),
                "findings": sum(
                    len(bl.get(layer, {}).get("findings", []))
                    for layer in ("graph", "decision", "evidence", "cost", "shadow", "compliance")
                ),
            }
        except Exception as e:
            info["baseline_error"] = str(e)
    reports = sorted(report_dir.glob("audit-*.html"))
    if reports:
        latest = reports[-1]
        info["latest_report"] = {
            "date": latest.stem.replace("audit-", ""),
            "size_bytes": latest.stat().st_size,
        }
    info["reports_total"] = len(reports)
    return json.dumps(info, ensure_ascii=False)


@mcp.tool()
def remediation_lookup(finding_title: str) -> str:
    """查询指定 finding 标题的修复建议（精确匹配 → 动态前缀 → 通用兜底）。

    参数:
        finding_title: finding 的标题（如 "APPROVAL_BYPASS_CONFIRMED"）
    返回 JSON：title / remediations（action, detail, priority 列表）。
    """
    try:
        items = _lookup_remediations(finding_title)
        return json.dumps({"title": finding_title, "remediations": items}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"修复建议查询失败: {exc}"}, ensure_ascii=False)


@mcp.tool()
def fix_tracking_status() -> str:
    """查询修复跟踪与回归验证状态（fixed-findings.json）。

    无参数。返回 JSON：found / total / by_status / by_verify / entries 摘要
    （entry 含 key, status, verify_status, marked_at；不含 note 全文，避免无关噪声）。
    """
    report_dir = Path(
        os.environ.get(
            "AGENTLENS_REPORT_DIR",
            os.path.expanduser("~/.hermes/agentlens-reports"),
        )
    )
    fixed_path = report_dir / "fixed-findings.json"
    if not fixed_path.is_file():
        return json.dumps({"found": False, "message": "无修复跟踪记录（fixed-findings.json 不存在）"}, ensure_ascii=False)
    try:
        data = json.loads(fixed_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return json.dumps({"found": False, "error": f"读取失败: {exc}"}, ensure_ascii=False)
    summary: dict = {"found": True, "total": len(data), "by_status": {}, "by_verify": {}}
    entries = []
    for e in data:
        st = e.get("status", "unknown")
        vs = e.get("verify_status", "")
        summary["by_status"][st] = summary["by_status"].get(st, 0) + 1
        if vs:
            summary["by_verify"][vs] = summary["by_verify"].get(vs, 0) + 1
        entries.append({
            "key": e.get("key", ""),
            "status": st,
            "verify_status": vs,
            "marked_at": e.get("marked_at", ""),
        })
    summary["entries"] = entries
    return json.dumps(summary, ensure_ascii=False)


def main():
    """MCP server 入口。默认 stdio 传输，支持 --transport http (streamable-http)。"""
    parser = argparse.ArgumentParser(description="AgentLens Audit MCP server")
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="传输方式: stdio(默认, MCP 客户端标准) / http(streamable-http 远程)",
    )
    parser.add_argument("--port", type=int, default=8765, help="HTTP 端口 (transport=http 时)")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 监听地址 (transport=http 时)")
    args = parser.parse_args()

    if args.transport == "http":
        print(f"AgentLens Audit MCP over HTTP: http://{args.host}:{args.port}/mcp", flush=True)
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
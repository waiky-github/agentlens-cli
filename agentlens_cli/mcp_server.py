"""MCP Server for AgentLens Audit —— 把七层审计能力暴露为标准 MCP 工具。

工具:
  - audit(events_path)          : 完整七层审计，返回 JSON（含 integrity 块）
  - cost_analysis(events_path)  : 成本分析（总成本/可避免成本/比例）
  - verify_report(report_path)  : 验报告完整性（防篡改哈希链）
  - list_regulations(title_filter) : 法规映射查询

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

from mcp.server.mcpserver import MCPServer

from .__main__ import _load_events, _run_audit_for_diff
from .attribution import attribute_costs
from .config import CostModel
from .governance import detect_waste
from .integrity import build_integrity_block, verify_report as _verify_report
from .regulations import list_regulations as _list_regulations

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
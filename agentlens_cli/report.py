"""HTML report renderer for AgentLens four-layer audit results.

Renders a self-contained HTML report (no external CDN/resources) from the
audit result dict produced by `cmd_audit`. Pure stdlib: html.escape, json.
"""

import html
import json
import math
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def render_html(result: dict, input_path: str = "") -> str:
    """Render a self-contained HTML audit report from the four-layer result dict.

    Args:
        result: The audit result dict (as returned by cmd_audit).
        input_path: Original input file path for display in the header.

    Returns:
        Complete HTML document as a string.
    """
    return _HtmlBuilder(result, input_path).build()


# ──────────────────────────────────────────────────────────────────────
# Internal HTML builder
# ──────────────────────────────────────────────────────────────────────

class _HtmlBuilder:
    def __init__(self, result: dict, input_path: str):
        self._r = result
        self._input = input_path
        self._now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── helpers ──────────────────────────────────────────────────

    def _esc(self, text) -> str:
        return html.escape(str(text))

    def _pct(self, val: float) -> str:
        return f"{val * 100:.1f}%"

    def _severity_color(self, severity: str) -> str:
        return {
            "high": "#dc3545",
            "medium": "#fd7e14",
            "low": "#ffc107",
            "info": "#0d6efd",
        }.get(severity, "#6c757d")

    def _severity_bg(self, severity: str) -> str:
        return {
            "high": "#fff5f5",
            "medium": "#fff8f0",
            "low": "#fffef0",
            "info": "#f0f6ff",
        }.get(severity, "#f8f9fa")

    def _cost_row(self, agent: str, data: dict) -> str:
        return (
            f"<tr><td>{self._esc(agent)}</td>"
            f"<td class='num'>{data.get('tokens_in', 0):,}</td>"
            f"<td class='num'>{data.get('tokens_out', 0):,}</td>"
            f"<td class='num'>{data.get('model_calls', 0)}</td>"
            f"<td class='num'>{data.get('tool_calls', 0)}</td>"
            f"<td class='num'>{data.get('cost', 0):.6f}</td></tr>"
        )

    # ── SVG graph ────────────────────────────────────────────────

    def _render_graph_viz(self, graph: dict) -> str:
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not nodes:
            return "<p class='nodata'>无协作图谱数据</p>"

        # Fallback to table if too many nodes (SVG gets messy)
        if len(nodes) > 30:
            return self._render_graph_table(nodes, edges)

        return self._render_graph_svg(nodes, edges)

    def _render_graph_svg(self, nodes: list, edges: list) -> str:
        w, h = 800, 520
        cx, cy = w / 2, h / 2
        r = min(cx, cy) - 60
        n = len(nodes)

        # Compute node positions on a circle
        positions = {}
        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / n - math.pi / 2
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle)
            positions[node["id"]] = (x, y)

        # Edge type → color
        edge_colors = {
            "task_dispatch": "#6c757d",
            "task_completion": "#198754",
            "approval": "#0d6efd",
            "info_flow": "#6f42c1",
        }

        # Build SVG edges
        svg_edges = []
        for edge in edges:
            src = edge.get("from", "")
            dst = edge.get("to", "")
            if src not in positions or dst not in positions:
                continue
            x1, y1 = positions[src]
            x2, y2 = positions[dst]
            color = edge_colors.get(edge.get("type", ""), "#adb5bd")
            etype = self._esc(edge.get("type", ""))
            tid = self._esc(str(edge.get("task_id", ""))[:30])
            svg_edges.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{color}" stroke-width="1.5" opacity="0.7">'
                f'<title>{etype}: {tid}</title></line>'
            )
            # Arrowhead
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length > 0:
                ux, uy = dx / length, dy / length
                # Shorten to node boundary (~28px radius)
                x2s = x2 - ux * 28
                y2s = y2 - uy * 28
                # Arrow
                arrow_size = 8
                ax1 = x2s - ux * arrow_size + uy * arrow_size * 0.5
                ay1 = y2s - uy * arrow_size - ux * arrow_size * 0.5
                ax2 = x2s - ux * arrow_size - uy * arrow_size * 0.5
                ay2 = y2s - uy * arrow_size + ux * arrow_size * 0.5
                svg_edges.append(
                    f'<polygon points="{x2s:.1f},{y2s:.1f} {ax1:.1f},{ay1:.1f} {ax2:.1f},{ay2:.1f}" '
                    f'fill="{color}" opacity="0.7"/>'
                )

        # Build SVG nodes
        role_colors = {
            "leader": "#dc3545",
            "collector": "#0d6efd",
            "builder": "#198754",
            "auditor": "#fd7e14",
            "analyst": "#6f42c1",
            "verifier": "#20c997",
            "worker": "#6c757d",
        }
        svg_nodes = []
        for node in nodes:
            nid = node["id"]
            x, y = positions[nid]
            color = role_colors.get(node.get("role", "worker"), "#6c757d")
            role = node.get("role", "worker")
            svg_nodes.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="24" fill="{color}" '
                f'stroke="#fff" stroke-width="2" opacity="0.9">'
                f'<title>{self._esc(nid)} ({role})</title></circle>'
            )
            # Label
            label = nid[:12] if len(nid) > 12 else nid
            svg_nodes.append(
                f'<text x="{x:.1f}" y="{y + 40:.1f}" text-anchor="middle" '
                f'font-size="10" fill="#333">{self._esc(label)}</text>'
            )

        # Legend
        legend = "".join(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{c}"></span>{t}'
            f'</span>'
            for t, c in edge_colors.items()
        )

        return (
            f'<div class="graph-svg-wrap">'
            f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">'
            f'{"".join(svg_edges)}'
            f'{"".join(svg_nodes)}'
            f'</svg>'
            f'<div class="graph-legend">{legend}</div>'
            f'</div>'
        )

    def _render_graph_table(self, nodes: list, edges: list) -> str:
        """Fallback: render nodes/edges as tables."""
        node_rows = "".join(
            f"<tr><td>{self._esc(n['id'])}</td>"
            f"<td>{self._esc(n.get('type', ''))}</td>"
            f"<td>{self._esc(n.get('role', ''))}</td></tr>"
            for n in nodes
        )
        edge_rows = "".join(
            f"<tr><td>{self._esc(e.get('from', ''))}</td>"
            f"<td>{self._esc(e.get('to', ''))}</td>"
            f"<td>{self._esc(e.get('type', ''))}</td>"
            f"<td>{self._esc(str(e.get('task_id', ''))[:40])}</td></tr>"
            for e in edges
        )
        return (
            f"<h4>节点 ({len(nodes)})</h4>"
            f"<table><thead><tr><th>ID</th><th>类型</th><th>角色</th></tr></thead>"
            f"<tbody>{node_rows}</tbody></table>"
            f"<h4>边 ({len(edges)})</h4>"
            f"<table><thead><tr><th>From</th><th>To</th><th>类型</th><th>任务</th></tr></thead>"
            f"<tbody>{edge_rows}</tbody></table>"
        )

    # ── findings list ────────────────────────────────────────────

    def _render_findings(self, findings: list) -> str:
        if not findings:
            return "<p class='nodata'>无发现项</p>"
        severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        sorted_f = sorted(
            findings,
            key=lambda x: (severity_order.get(x.get("severity", "info"), 99), x.get("title", "")),
        )
        rows = []
        for f in sorted_f:
            sev = f.get("severity", "info")
            color = self._severity_color(sev)
            bg = self._severity_bg(sev)
            rows.append(
                f'<div class="finding" style="border-left:4px solid {color};background:{bg}">'
                f'<span class="finding-sev" style="background:{color}">{sev.upper()}</span>'
                f'<strong>{self._esc(f.get("title", ""))}</strong>'
            )
            detail = f.get("detail", "")
            if detail:
                rows.append(f'<p class="finding-detail">{self._esc(str(detail))}</p>')
            rec = f.get("recommendation", "")
            if rec:
                rows.append(
                    f'<p class="finding-rec">建议: {self._esc(rec)}</p>'
                )
            tool = f.get("tool", "")
            if tool:
                rows.append(f'<p class="finding-meta">工具: {self._esc(tool)}</p>')
            waste = f.get("est_wasted_cost")
            if waste is not None and waste > 0:
                rows.append(
                    f'<p class="finding-meta">预估浪费: {waste:.6f} CNY</p>'
                )
            rows.append("</div>")
        return "\n".join(rows)

    # ── sections ─────────────────────────────────────────────────

    def _section_header(self, result: dict) -> str:
        graph = result.get("graph", {})
        decision = result.get("decision", {})
        evidence = result.get("evidence", {})
        cost = result.get("cost", {})
        shadow = result.get("shadow", {})

        audit_id = graph.get("graph_id", decision.get("audit_id", "N/A"))
        events_loaded = result.get("events_loaded", 0)
        closure_rate = self._pct(graph.get("metrics", {}).get("closure_rate", 0))
        completeness = self._pct(evidence.get("completeness", 0))
        bypass = decision.get("approval_bypass_detected", False)
        bypass_text = "检测到审批绕过" if bypass else "未检测到审批绕过"
        avoidable = self._pct(cost.get("avoidable_cost_ratio", 0))
        shadow_count = len(shadow.get("findings", []))
        shadow_text = f"影子智能体发现: {shadow_count}" if shadow_count else "无影子智能体"

        return (
            f'<div class="header">'
            f'<h1>AgentLens 审计报告</h1>'
            f'<div class="header-meta">'
            f'<span>审计ID: <strong>{self._esc(audit_id)}</strong></span>'
            f'<span>输入文件: <strong>{self._esc(self._input or "N/A")}</strong></span>'
            f'<span>生成时间: <strong>{self._esc(self._now)}</strong></span>'
            f'<span>事件数: <strong>{events_loaded}</strong></span>'
            f'</div>'
            f'<div class="summary-cards">'
            f'<div class="card"><div class="card-label">决策判定</div>'
            f'<div class="card-value">{self._esc(decision.get("summary", "N/A"))}</div>'
            f'<div class="card-sub">{bypass_text}</div></div>'
            f'<div class="card"><div class="card-label">闭环率</div>'
            f'<div class="card-value">{closure_rate}</div></div>'
            f'<div class="card"><div class="card-label">证据完整性</div>'
            f'<div class="card-value">{completeness}</div></div>'
            f'<div class="card"><div class="card-label">可避免成本占比</div>'
            f'<div class="card-value">{avoidable}</div></div>'
            f'<div class="card"><div class="card-label">影子智能体</div>'
            f'<div class="card-value">{shadow_text}</div></div>'
            f'</div></div>'
        )

    def _section_graph(self, graph: dict) -> str:
        metrics = graph.get("metrics", {})
        return (
            f'<div class="section" id="layer-graph">'
            f'<h2>1. 协作图谱</h2>'
            f'<div class="metrics-bar">'
            f'<span>节点: <strong>{len(graph.get("nodes", []))}</strong></span>'
            f'<span>边: <strong>{len(graph.get("edges", []))}</strong></span>'
            f'<span>派发任务: <strong>{metrics.get("total_dispatched", 0)}</strong></span>'
            f'<span>已完成: <strong>{metrics.get("closed_count", 0)}</strong></span>'
            f'<span>闭环率: <strong>{self._pct(metrics.get("closure_rate", 0))}</strong></span>'
            f'</div>'
            f'{self._render_graph_viz(graph)}'
            f'<h3>图谱发现</h3>'
            f'{self._render_findings(graph.get("findings", []))}'
            f'</div>'
        )

    def _section_decision(self, decision: dict) -> str:
        bypass = decision.get("approval_bypass_detected", False)
        bypass_banner = ""
        if bypass:
            bypass_banner = (
                '<div class="bypass-banner">*** 检测到审批绕过 (APPROVAL_BYPASS) ***</div>'
            )
        return (
            f'<div class="section" id="layer-decision">'
            f'<h2>2. 决策审计</h2>'
            f'{bypass_banner}'
            f'<div class="metrics-bar">'
            f'<span>决策链步骤: <strong>{len(decision.get("decision_chain", []))}</strong></span>'
            f'<span>摘要: <strong>{self._esc(decision.get("summary", ""))}</strong></span>'
            f'</div>'
            f'<h3>决策发现</h3>'
            f'{self._render_findings(decision.get("findings", []))}'
            f'</div>'
        )

    def _section_evidence(self, evidence: dict) -> str:
        missing = evidence.get("missing_evidence", [])
        missing_rows = ""
        if missing:
            rows = "".join(
                f"<tr><td>{self._esc(m.get('event_id', ''))}</td>"
                f"<td>{self._esc(m.get('claim', ''))}</td>"
                f"<td>{self._esc(m.get('reason', ''))}</td></tr>"
                for m in missing
            )
            missing_rows = (
                f"<h4>缺失证据 ({len(missing)})</h4>"
                f"<table><thead><tr><th>事件ID</th><th>声明</th><th>原因</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )
        return (
            f'<div class="section" id="layer-evidence">'
            f'<h2>3. 证据链</h2>'
            f'<div class="metrics-bar">'
            f'<span>声明检查: <strong>{evidence.get("claims_checked", 0)}</strong></span>'
            f'<span>已验证: <strong>{evidence.get("verified", 0)}</strong></span>'
            f'<span>完整度: <strong>{self._pct(evidence.get("completeness", 0))}</strong></span>'
            f'</div>'
            f'{missing_rows}'
            f'<h3>证据发现</h3>'
            f'{self._render_findings(evidence.get("findings", []))}'
            f'</div>'
        )

    def _section_cost(self, cost: dict) -> str:
        cost_by_agent = cost.get("cost_by_agent", {})
        agent_rows = "".join(
            self._cost_row(agent, data)
            for agent, data in sorted(cost_by_agent.items())
        )
        avoidable = cost.get("avoidable_cost_ratio", 0)
        avoidable_class = "highlight" if avoidable > 0.1 else ""

        # Top findings by est_wasted_cost
        findings = cost.get("findings", [])
        top_findings = sorted(
            findings,
            key=lambda f: f.get("est_wasted_cost", 0),
            reverse=True,
        )[:10]

        return (
            f'<div class="section" id="layer-cost">'
            f'<h2>4. 成本治理</h2>'
            f'<div class="metrics-bar">'
            f'<span>总输入 Token: <strong>{cost.get("total_tokens_in", 0):,}</strong></span>'
            f'<span>总输出 Token: <strong>{cost.get("total_tokens_out", 0):,}</strong></span>'
            f'<span>总成本: <strong>{cost.get("total_cost", 0):.6f} CNY</strong></span>'
            f'<span>浪费发现: <strong>{len(findings)}</strong></span>'
            f'<span>预估浪费: <strong>{cost.get("total_est_wasted_cost", 0):.6f} CNY</strong></span>'
            f'<span class="{avoidable_class}">可避免占比: <strong>{self._pct(avoidable)}</strong></span>'
            f'</div>'
            f'<h3>各 Agent 成本</h3>'
            f'<table><thead><tr>'
            f'<th>Agent</th><th>输入 Token</th><th>输出 Token</th>'
            f'<th>模型调用</th><th>工具调用</th><th>成本 (CNY)</th>'
            f'</tr></thead><tbody>{agent_rows}</tbody></table>'
            f'<h3>Top 浪费发现</h3>'
            f'{self._render_findings(top_findings)}'
            f'</div>'
        )

    def _section_shadow(self, shadow: dict) -> str:
        findings = shadow.get("findings", [])
        shadow_count = len(findings)
        shadow_banner = ""
        if shadow_count > 0:
            shadow_banner = (
                '<div class="bypass-banner" style="background:#fd7e14">'
                f'*** 检测到 {shadow_count} 个影子智能体相关发现 ***</div>'
            )
        return (
            f'<div class="section" id="layer-shadow">'
            f'<h2>5. 影子智能体检测</h2>'
            f'{shadow_banner}'
            f'<div class="metrics-bar">'
            f'<span>摘要: <strong>{self._esc(shadow.get("summary", "no findings"))}</strong></span>'
            f'<span>发现数: <strong>{shadow_count}</strong></span>'
            f'</div>'
            f'<h3>影子智能体发现</h3>'
            f'{self._render_findings(findings)}'
            f'</div>'
        )

    def _section_footer(self) -> str:
        return (
            f'<div class="footer">'
            f'<p>本报告由 agentlens-cli 自动生成 — {self._esc(self._now)}</p>'
            f'<p class="disclaimer">免责声明：本报告基于输入事件流自动分析生成，'
            f'仅供审计参考，不构成法律或合规建议。所有成本数据均为估算值。</p>'
            f'</div>'
        )

    # ── CSS ──────────────────────────────────────────────────────

    _CSS = """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  background:#f5f6fa;color:#2d3436;line-height:1.6;padding:20px}
.container{max-width:1100px;margin:0 auto}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:30px;
  border-radius:12px;margin-bottom:24px}
.header h1{font-size:24px;margin-bottom:16px}
.header-meta{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;opacity:0.85;margin-bottom:20px}
.header-meta span{white-space:nowrap}
.summary-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.card{background:rgba(255,255,255,0.12);padding:16px;border-radius:8px;text-align:center}
.card-label{font-size:12px;opacity:0.7;margin-bottom:4px}
.card-value{font-size:20px;font-weight:700}
.card-sub{font-size:12px;margin-top:4px;opacity:0.8}
.section{background:#fff;border-radius:10px;padding:24px;margin-bottom:20px;
  box-shadow:0 1px 4px rgba(0,0,0,0.06)}
.section h2{font-size:18px;border-bottom:2px solid #eee;padding-bottom:10px;margin-bottom:16px}
.section h3{font-size:15px;margin:20px 0 10px;color:#555}
.section h4{font-size:14px;margin:16px 0 8px;color:#666}
.metrics-bar{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;margin-bottom:16px;
  padding:12px;background:#f8f9fa;border-radius:6px}
.metrics-bar span{white-space:nowrap}
.highlight{background:#ffe0e0;padding:2px 8px;border-radius:4px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0 16px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #eee}
th{background:#f8f9fa;font-weight:600;color:#555}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover{background:#f8f9fa}
.nodata{color:#999;font-style:italic;padding:10px}
.finding{border-radius:6px;padding:12px 16px;margin-bottom:8px}
.finding-sev{display:inline-block;color:#fff;font-size:10px;font-weight:700;
  padding:2px 8px;border-radius:3px;margin-right:10px;vertical-align:middle}
.finding-detail{font-size:12px;color:#555;margin:6px 0 0 0}
.finding-rec{font-size:12px;color:#198754;margin:4px 0 0 0}
.finding-meta{font-size:11px;color:#888;margin:2px 0 0 0}
.bypass-banner{background:#dc3545;color:#fff;padding:10px 16px;border-radius:6px;
  font-weight:700;margin-bottom:12px;text-align:center}
.graph-svg-wrap{text-align:center;margin:16px 0}
.graph-svg-wrap svg{max-width:100%;height:auto}
.graph-legend{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;
  margin-top:10px;font-size:11px}
.legend-item{display:flex;align-items:center;gap:4px}
.legend-swatch{display:inline-block;width:14px;height:14px;border-radius:3px}
.footer{margin-top:30px;padding:20px;text-align:center;color:#888;font-size:12px;
  border-top:1px solid #ddd}
.disclaimer{color:#aaa;font-size:11px;margin-top:6px}
"""

    # ── build ────────────────────────────────────────────────────

    def build(self) -> str:
        return (
            "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>AgentLens 审计报告</title>\n"
            f"<style>{self._CSS}</style>\n"
            "</head>\n<body>\n<div class=\"container\">\n"
            + self._section_header(self._r)
            + self._section_graph(self._r.get("graph", {}))
            + self._section_decision(self._r.get("decision", {}))
            + self._section_evidence(self._r.get("evidence", {}))
            + self._section_cost(self._r.get("cost", {}))
            + self._section_shadow(self._r.get("shadow", {}))
            + self._section_footer()
            + "</div>\n</body>\n</html>"
        )
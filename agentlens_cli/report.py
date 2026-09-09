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


def render_diff_html(diff: dict, baseline_path: str, current_path: str) -> str:
    """Render a self-contained HTML diff report comparing two audit runs.

    Args:
        diff: The diff dict with baseline, current, and deltas keys.
        baseline_path: Path to the baseline input file.
        current_path: Path to the current input file.

    Returns:
        Complete HTML document as a string.
    """
    return _DiffHtmlBuilder(diff, baseline_path, current_path).build()


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

    # ── dashboard (一页速览) ─────────────────────────────────────

    def _js(self, obj) -> str:
        """Serialize obj to a JS-safe JSON literal (escapes </script>)."""
        return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

    def _all_findings(self) -> list:
        layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
        out = []
        for key in layer_keys:
            layer = self._r.get(key, {})
            if isinstance(layer, dict):
                out.extend(layer.get("findings", []))
        return out

    def _severity_dist(self, findings: list) -> dict:
        dist = {"high": 0, "medium": 0, "low": 0, "info": 0}
        for f in findings:
            s = f.get("severity", "info")
            dist[s] = dist.get(s, 0) + 1
        return dist

    def _dashboard(self) -> str:
        findings = self._all_findings()
        dist = self._severity_dist(findings)
        total_findings = len(findings)
        high = dist["high"]

        cost = self._r.get("cost", {})
        decision = self._r.get("decision", {})
        shadow = self._r.get("shadow", {})
        graph = self._r.get("graph", {})

        est_waste = cost.get("total_est_wasted_cost", 0)
        avoidable = cost.get("avoidable_cost_ratio", 0)
        bypass = bool(decision.get("approval_bypass_detected", False))
        shadow_count = len(shadow.get("findings", []))
        total_cost = cost.get("total_cost", 0)
        closure_rate = graph.get("metrics", {}).get("closure_rate", 0)

        kpi_cards = (
            f'<div class="kpi-card {"red" if high > 0 else "green"}">'
            f'<div class="kpi-label">发现总数</div>'
            f'<div class="kpi-value">{total_findings}</div>'
            f'<div class="kpi-sub">High {high} / Med {dist["medium"]} / Low {dist["low"]} / Info {dist["info"]}</div></div>'
            f'<div class="kpi-card {"red" if est_waste > 0 else "green"}">'
            f'<div class="kpi-label">预估浪费成本</div>'
            f'<div class="kpi-value">{est_waste:.4f}</div>'
            f'<div class="kpi-sub">CNY（总成本 {total_cost:.4f}）</div></div>'
            f'<div class="kpi-card {"purple" if shadow_count > 0 else "green"}">'
            f'<div class="kpi-label">影子智能体</div>'
            f'<div class="kpi-value">{shadow_count}</div>'
            f'<div class="kpi-sub">{"需关注" if shadow_count else "未发现"}</div></div>'
            f'<div class="kpi-card {"red" if bypass else "green"}">'
            f'<div class="kpi-label">审批绕过</div>'
            f'<div class="kpi-value">{"检出" if bypass else "无"}</div>'
            f'<div class="kpi-sub">决策审计</div></div>'
            f'<div class="kpi-card orange">'
            f'<div class="kpi-label">可避免成本占比</div>'
            f'<div class="kpi-value">{self._pct(avoidable)}</div>'
            f'<div class="kpi-sub">占总支出的浪费比例</div></div>'
            f'<div class="kpi-card gray">'
            f'<div class="kpi-label">任务闭环率</div>'
            f'<div class="kpi-value">{self._pct(closure_rate)}</div>'
            f'<div class="kpi-sub">协作图谱</div></div>'
        )

        # ── Chart 1: severity donut ──
        pie_data = [
            {"name": "High", "value": dist["high"], "itemStyle": {"color": "#dc3545"}},
            {"name": "Medium", "value": dist["medium"], "itemStyle": {"color": "#fd7e14"}},
            {"name": "Low", "value": dist["low"], "itemStyle": {"color": "#ffc107"}},
            {"name": "Info", "value": dist["info"], "itemStyle": {"color": "#0d6efd"}},
        ]

        # ── Chart 2: top-10 waste bars ──
        cost_findings = sorted(
            cost.get("findings", []),
            key=lambda f: f.get("est_wasted_cost", 0),
            reverse=True,
        )[:10]
        waste_names = [
            (f.get("title", ""))[:30] + ("…" if len(f.get("title", "")) > 30 else "")
            for f in cost_findings
        ]
        waste_vals = [round(f.get("est_wasted_cost", 0), 4) for f in cost_findings]

        # ── Chart 3: cost by agent ──
        cost_by_agent = cost.get("cost_by_agent", {})
        agents = sorted(cost_by_agent.keys())
        agent_cost = [round(cost_by_agent[a].get("cost", 0), 4) for a in agents]
        agent_tokens = [
            (cost_by_agent[a].get("tokens_in", 0) + cost_by_agent[a].get("tokens_out", 0))
            for a in agents
        ]

        # ── assemble ──
        bypass_badge = (
            '<span class="dash-badge warn">检测到审批绕过</span>'
            if bypass
            else '<span class="dash-badge ok">审批链正常</span>'
        )
        shadow_badge = (
            '<span class="dash-badge warn">发现影子智能体</span>'
            if shadow_count
            else '<span class="dash-badge ok">无影子智能体</span>'
        )

        js_data = {
            "severity": pie_data,
            "waste_names": waste_names,
            "waste_vals": waste_vals,
            "agents": agents,
            "agent_cost": agent_cost,
            "agent_tokens": agent_tokens,
        }

        return (
            f'<div class="section" id="dashboard">'
            f'<h2>📊 一页速览{bypass_badge}{shadow_badge}</h2>'
            f'<div class="kpi-grid">{kpi_cards}</div>'
            f'<div class="chart-grid">'
            f'<div class="chart-box"><h4>发现严重度分布</h4>'
            f'<div id="chart-severity" class="chart-canvas"></div></div>'
            f'<div class="chart-box"><h4>Top 10 浪费发现（预估 CNY）</h4>'
            f'<div id="chart-waste" class="chart-canvas"></div></div>'
            f'<div class="chart-box wide"><h4>各 Agent 成本与 Token 量</h4>'
            f'<div id="chart-agent" class="chart-canvas"></div></div>'
            f'</div>'
            f'</div>'
            f'<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>'
            f'<script>'
            f'(function(){{'
            f"var DATA = {self._js(js_data)};"
            f"if (typeof echarts === 'undefined') {{"
            f"  var boxes = document.querySelectorAll('.chart-canvas');"
            f"  for (var i = 0; i < boxes.length; i++) {{"
            f"    boxes[i].innerHTML = '<div class=\"nodata\">图表需要联网加载 ECharts，当前环境无法访问 CDN</div>';"
            f"  }}"
            f"  return;"
            f"}}"
            f"var chartSeverity = echarts.init(document.getElementById('chart-severity'));"
            f"chartSeverity.setOption({{\n"
            f"  animation: false,"
            f"  tooltip: {{trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)'}},"
            f"  legend: {{bottom: 0}},"
            f"  series: [{{"
            f"    name: '严重度', type: 'pie', radius: ['45%', '70%'],"
            f"    center: ['50%', '45%'],"
            f"    avoidLabelOverlap: true,"
            f"    itemStyle: {{borderRadius: 6, borderColor: '#fff', borderWidth: 2}},"
            f"    label: {{show: true, formatter: '{{b}} {{c}}'}},"
            f"    data: DATA.severity"
            f"  }}]"
            f"}});"
            f"requestAnimationFrame(function() {{ chartSeverity.resize(); }});"
            f"var chartWaste = echarts.init(document.getElementById('chart-waste'));"
            f"chartWaste.setOption({{\n"
            f"  animation: false,"
            f"  tooltip: {{trigger: 'axis', axisPointer: {{type: 'shadow'}}, valueFormatter: function(v) {{ return v + ' CNY'; }}}},"
            f"  grid: {{left: 8, right: 30, top: 10, bottom: 8, containLabel: true}},"
            f"  xAxis: {{type: 'value', name: 'CNY'}},"
            f"  yAxis: {{type: 'category', data: DATA.waste_names, inverse: true}},"
            f"  series: [{{"
            f"    name: '预估浪费', type: 'bar', data: DATA.waste_vals,"
            f"    itemStyle: {{color: '#fd7e14', borderRadius: [0, 4, 4, 0]}},"
            f"    label: {{show: true, position: 'right', formatter: function(p) {{ return p.value.toFixed(4); }}}}"
            f"  }}]"
            f"}});"
            f"var chartAgent = echarts.init(document.getElementById('chart-agent'));"
            f"chartAgent.setOption({{\n"
            f"  animation: false,"
            f"  tooltip: {{trigger: 'axis'}},"
            f"  legend: {{top: 0}},"
            f"  grid: {{left: 8, right: 30, top: 30, bottom: 8, containLabel: true}},"
            f"  xAxis: {{type: 'category', data: DATA.agents, axisLabel: {{interval: 0, rotate: 20}}}},"
            f"  yAxis: ["
            f"    {{type: 'value', name: '成本 CNY', axisLabel: {{formatter: function(v) {{ return v.toFixed(4); }}}}}},"
            f"    {{type: 'value', name: 'Token', splitLine: {{show: false}}}}"
            f"  ],"
            f"  series: ["
            f"    {{name: '成本 (CNY)', type: 'bar', data: DATA.agent_cost, itemStyle: {{color: '#0d6efd', borderRadius: [4, 4, 0, 0]}}}},"
            f"    {{name: 'Token 量', type: 'line', yAxisIndex: 1, data: DATA.agent_tokens,"
            f"      itemStyle: {{color: '#6f42c1'}}, smooth: true}}"
            f"  ]"
            f"}});"
            f"function resizeAll() {{"
            f"  chartSeverity.resize(); chartWaste.resize(); chartAgent.resize();"
            f"}}"
            f"requestAnimationFrame(resizeAll);"
            f"setTimeout(resizeAll, 100);"
            f"window.addEventListener('resize', resizeAll);"
            f"window.addEventListener('load', resizeAll);"
            f"}})();"
            f"</script>"
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
            # Regulation references
            regs = f.get("regulation_refs", [])
            if regs:
                rows.append('<div class="finding-regs">')
                rows.append('<span class="finding-regs-label">法规依据:</span>')
                rows.append('<ul class="regs-list">')
                for ref in regs:
                    regulation = ref.get("regulation", "unknown")
                    article = ref.get("article", "")
                    clause = ref.get("clause", "")
                    note = ref.get("note", "")
                    if note:
                        rows.append(
                            f"<li>{self._esc(regulation)} — {self._esc(note)}</li>"
                        )
                    else:
                        rows.append(
                            f"<li>{self._esc(regulation)} — {self._esc(article)}: {self._esc(clause)}</li>"
                        )
                rows.append("</ul></div>")
            # Remediation suggestions
            rems = f.get("remediation", [])
            if rems:
                rows.append('<div class="finding-rems">')
                rows.append('<span class="finding-rems-label">修复建议:</span>')
                rows.append('<ul class="rems-list">')
                for rem in rems:
                    priority = rem.get("priority", "medium")
                    action = rem.get("action", "")
                    detail = rem.get("detail", "")
                    pri_color = self._severity_color(priority) if priority in ("high", "medium", "low") else "#6c757d"
                    rows.append(
                        f'<li>'
                        f'<span class="rems-pri" style="background:{pri_color}">{priority.upper()}</span> '
                        f'<strong>{self._esc(action)}</strong>'
                    )
                    if detail:
                        rows.append(f'<br><span class="rems-detail">{self._esc(detail)}</span>')
                    rows.append('</li>')
                rows.append("</ul></div>")
            rows.append("</div>")
        return "\n".join(rows)

    # ── sections ─────────────────────────────────────────────────

    def _section_header(self, result: dict) -> str:
        graph = result.get("graph", {})
        decision = result.get("decision", {})
        evidence = result.get("evidence", {})
        cost = result.get("cost", {})
        shadow = result.get("shadow", {})
        compliance = result.get("compliance", {})

        audit_id = graph.get("graph_id", decision.get("audit_id", "N/A"))
        events_loaded = result.get("events_loaded", 0)
        closure_rate = self._pct(graph.get("metrics", {}).get("closure_rate", 0))
        completeness = self._pct(evidence.get("completeness", 0))
        bypass = decision.get("approval_bypass_detected", False)
        bypass_text = "检测到审批绕过" if bypass else "未检测到审批绕过"
        avoidable = self._pct(cost.get("avoidable_cost_ratio", 0))
        shadow_count = len(shadow.get("findings", []))
        shadow_text = f"影子智能体发现: {shadow_count}" if shadow_count else "无影子智能体"
        compliance_count = len(compliance.get("findings", []))
        compliance_text = f"合规发现: {compliance_count}" if compliance_count else "合规无发现"

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
            f'<div class="card"><div class="card-label">决策权限合规</div>'
            f'<div class="card-value">{compliance_text}</div></div>'
            f'</div></div>'
        )

    def _section_graph(self, graph: dict) -> str:
        metrics = graph.get("metrics", {})
        return (
            f'<div class="section" id="layer-graph">'
            f'<h2><span class="layer-badge">01</span> 协作图谱<a href="#dashboard" class="back-to-top">返回概览 ↑</a></h2>'
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
            f'<h2><span class="layer-badge">02</span> 决策审计<a href="#dashboard" class="back-to-top">返回概览 ↑</a></h2>'
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
            f'<h2><span class="layer-badge">03</span> 证据链<a href="#dashboard" class="back-to-top">返回概览 ↑</a></h2>'
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
            f'<h2><span class="layer-badge">04</span> 成本治理<a href="#dashboard" class="back-to-top">返回概览 ↑</a></h2>'
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
            f'<h2><span class="layer-badge">05</span> 影子智能体检测<a href="#dashboard" class="back-to-top">返回概览 ↑</a></h2>'
            f'{shadow_banner}'
            f'<div class="metrics-bar">'
            f'<span>摘要: <strong>{self._esc(shadow.get("summary", "no findings"))}</strong></span>'
            f'<span>发现数: <strong>{shadow_count}</strong></span>'
            f'</div>'
            f'<h3>影子智能体发现</h3>'
            f'{self._render_findings(findings)}'
            f'</div>'
        )

    def _section_compliance(self, compliance: dict) -> str:
        findings = compliance.get("findings", [])
        findings_count = len(findings)
        high_count = sum(1 for f in findings if f.get("severity") == "high")
        compliance_banner = ""
        if high_count > 0:
            compliance_banner = (
                '<div class="bypass-banner" style="background:#dc3545">'
                f'*** 检测到 {high_count} 个高风险决策权限合规问题 ***</div>'
            )
        return (
            f'<div class="section" id="layer-compliance">'
            f'<h2><span class="layer-badge">06</span> 决策权限合规<a href="#dashboard" class="back-to-top">返回概览 ↑</a></h2>'
            f'{compliance_banner}'
            f'<div class="metrics-bar">'
            f'<span>摘要: <strong>{self._esc(compliance.get("summary", "no findings"))}</strong></span>'
            f'<span>发现数: <strong>{findings_count}</strong></span>'
            f'</div>'
            f'<h3>合规发现</h3>'
            f'{self._render_findings(findings)}'
            f'</div>'
        )

    def _section_compliance_mapping(self) -> str:
        """Build a compliance mapping summary section showing which regulations were referenced."""
        # Collect all unique regulation references across all findings
        layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
        seen_regs = set()
        reg_rows = []
        for key in layer_keys:
            layer = self._r.get(key, {})
            if not isinstance(layer, dict):
                continue
            for f in layer.get("findings", []):
                for ref in f.get("regulation_refs", []):
                    reg_key = (ref.get("regulation", ""), ref.get("article", ""), ref.get("clause", ""), ref.get("note", ""))
                    if reg_key not in seen_regs:
                        seen_regs.add(reg_key)
                        regulation = ref.get("regulation", "unknown")
                        article = ref.get("article", "")
                        clause = ref.get("clause", "")
                        note = ref.get("note", "")
                        if note:
                            reg_rows.append(
                                f"<tr><td>{self._esc(regulation)}</td>"
                                f"<td>—</td><td>{self._esc(note)}</td></tr>"
                            )
                        else:
                            reg_rows.append(
                                f"<tr><td>{self._esc(regulation)}</td>"
                                f"<td>{self._esc(article)}</td><td>{self._esc(clause)}</td></tr>"
                            )
        if not reg_rows:
            return ""

        return (
            f'<div class="section" id="layer-compliance-mapping">'
            f'<h2><span class="layer-badge">07</span> 合规条款映射<a href="#dashboard" class="back-to-top">返回概览 ↑</a></h2>'
            f'<div class="metrics-bar">'
            f'<span>引用的法规条款: <strong>{len(reg_rows)}</strong></span>'
            f'<span>主要法规: 网信办《实施意见》(2026-05-08) / EU AI Act (2024/1689) / 《拟人化互动办法》(2026-07-15)</span>'
            f'</div>'
            f'<p style="font-size:12px;color:#888;margin-bottom:12px">'
            f'以下为本次审计发现涉及的所有法规条款汇总。每条发现均已标注对应的法规依据。'
            f'</p>'
            f'<table><thead><tr>'
            f'<th>法规文件</th><th>条款</th><th>要求</th>'
            f'</tr></thead><tbody>{"".join(reg_rows)}</tbody></table>'
            f'</div>'
        )

    def _section_remediation_priority(self) -> str:
        """Build a remediation priority summary section (section 8)."""
        layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
        high_items = []
        medium_items = []
        low_items = []
        for key in layer_keys:
            layer = self._r.get(key, {})
            if not isinstance(layer, dict):
                continue
            for f in layer.get("findings", []):
                title = f.get("title", "")
                for rem in f.get("remediation", []):
                    priority = rem.get("priority", "medium")
                    if priority == "high":
                        high_items.append(title)
                    elif priority == "medium":
                        medium_items.append(title)
                    elif priority == "low":
                        low_items.append(title)

        # Deduplicate per priority
        high_unique = sorted(set(high_items))
        medium_unique = sorted(set(medium_items))
        low_unique = sorted(set(low_items))

        high_rows = "".join(f"<li>{self._esc(t)}</li>" for t in high_unique) if high_unique else "<li class='nodata'>无</li>"
        medium_rows = "".join(f"<li>{self._esc(t)}</li>" for t in medium_unique) if medium_unique else "<li class='nodata'>无</li>"
        low_rows = "".join(f"<li>{self._esc(t)}</li>" for t in low_unique) if low_unique else "<li class='nodata'>无</li>"

        return (
            f'<div class="section" id="layer-remediation-priority">'
            f'<h2><span class="layer-badge">08</span> 修复优先级<a href="#dashboard" class="back-to-top">返回概览 ↑</a></h2>'
            f'<div class="metrics-bar">'
            f'<span>High 优先级修复: <strong>{len(high_unique)}</strong></span>'
            f'<span>Medium 优先级修复: <strong>{len(medium_unique)}</strong></span>'
            f'<span>Low 优先级修复: <strong>{len(low_unique)}</strong></span>'
            f'</div>'
            f'<h3>High 优先级 ({len(high_unique)})</h3>'
            f'<ul class="prio-list">{high_rows}</ul>'
            f'<h3>Medium 优先级 ({len(medium_unique)})</h3>'
            f'<ul class="prio-list">{medium_rows}</ul>'
            f'<h3>Low 优先级 ({len(low_unique)})</h3>'
            f'<ul class="prio-list">{low_rows}</ul>'
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
  box-shadow:0 1px 4px rgba(0,0,0,0.06);scroll-margin-top:60px}
.section h2{font-size:18px;border-bottom:2px solid #eee;padding-bottom:10px;margin-bottom:16px}
.section h2 .layer-badge{display:inline-block;font-size:11px;font-weight:700;color:#fff;
  background:#6c757d;padding:2px 8px;border-radius:4px;margin-right:8px;vertical-align:middle;
  font-family:monospace;letter-spacing:0.5px}
.section h2 .back-to-top{float:right;font-size:11px;font-weight:400;color:#0d6efd;
  text-decoration:none;padding:2px 8px;border-radius:4px;transition:background 0.15s}
.section h2 .back-to-top:hover{background:#e8f0fe}
.section h3{font-size:15px;margin:20px 0 10px;color:#555}
.section h4{font-size:14px;margin:16px 0 8px;color:#666}
/* ── sticky nav bar ── */
.layer-nav{position:sticky;top:0;z-index:100;background:rgba(15,17,23,0.92);
  backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
  padding:10px 0;margin-bottom:24px;border-bottom:1px solid #ddd;
  overflow-x:auto;white-space:nowrap}
.layer-nav-inner{display:flex;gap:6px;max-width:1100px;margin:0 auto;padding:0 12px}
.layer-nav a{display:inline-block;padding:6px 14px;border-radius:16px;font-size:12px;
  font-weight:600;color:#555;text-decoration:none;transition:all 0.2s;
  background:transparent;border:1px solid transparent}
.layer-nav a:hover{background:#e8f0fe;color:#0d6efd}
.layer-nav a.active{background:#0d6efd;color:#fff;border-color:#0d6efd}
@media(max-width:768px){
  .layer-nav-inner{padding:0 8px;gap:4px}
  .layer-nav a{padding:5px 10px;font-size:11px}
}
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
.finding-regs{margin-top:8px;padding:8px 10px;background:#f0f4ff;border-radius:4px;
  font-size:11px;color:#334}
.finding-regs-label{font-weight:700;color:#0066cc}
.regs-list{margin:4px 0 0 16px;padding:0;list-style:disc}
.regs-list li{margin:2px 0;line-height:1.4}
.finding-rems{margin-top:8px;padding:8px 10px;background:#f0fff4;border-radius:4px;
  font-size:11px;color:#334}
.finding-rems-label{font-weight:700;color:#198754}
.rems-list{margin:4px 0 0 16px;padding:0;list-style:disc}
.rems-list li{margin:4px 0;line-height:1.4}
.rems-pri{display:inline-block;color:#fff;font-size:9px;font-weight:700;
  padding:1px 6px;border-radius:3px;margin-right:4px;vertical-align:middle}
.rems-detail{color:#555;font-size:10px}
.prio-list{margin:4px 0 12px 20px;padding:0;font-size:13px}
.prio-list li{margin:2px 0;line-height:1.4}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.kpi-card{background:#fff;border-radius:10px;padding:16px 12px;text-align:center;
  box-shadow:0 1px 4px rgba(0,0,0,0.06);border-top:3px solid #0d6efd}
.kpi-card.red{border-top-color:#dc3545}
.kpi-card.orange{border-top-color:#fd7e14}
.kpi-card.green{border-top-color:#198754}
.kpi-card.purple{border-top-color:#6f42c1}
.kpi-card.gray{border-top-color:#6c757d}
.kpi-label{font-size:12px;color:#888;margin-bottom:4px}
.kpi-value{font-size:26px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1.2}
.kpi-sub{font-size:11px;color:#aaa;margin-top:2px}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.chart-box{background:#f8f9fa;border-radius:8px;padding:12px}
.chart-box h4{font-size:13px;color:#555;margin:0 0 8px;font-weight:600}
.chart-box.wide{grid-column:1/-1}
.chart-canvas{width:100%;height:300px}
@media(max-width:768px){.chart-grid{grid-template-columns:1fr}}
.dash-badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;
  font-weight:700;margin-left:8px;vertical-align:middle}
.dash-badge.ok{background:#d1e7dd;color:#0f5132}
.dash-badge.warn{background:#f8d7da;color:#842029}
"""

    # ── build ────────────────────────────────────────────────────

    def build(self) -> str:
        nav_html = (
            '<div class="layer-nav" id="layer-nav">'
            '<div class="layer-nav-inner">'
            '<a href="#dashboard" class="active">概览</a>'
            '<a href="#layer-graph">协作图谱</a>'
            '<a href="#layer-decision">决策审计</a>'
            '<a href="#layer-evidence">证据链</a>'
            '<a href="#layer-cost">成本治理</a>'
            '<a href="#layer-shadow">影子智能体</a>'
            '<a href="#layer-compliance">合规条款</a>'
            '<a href="#layer-remediation-priority">修复优先级</a>'
            '</div></div>'
        )
        scrollspy_js = (
            '<script>'
            '(function(){'
            'var navLinks=document.querySelectorAll(".layer-nav a");'
            'var sections=[];'
            'navLinks.forEach(function(a){'
            '  var id=a.getAttribute("href");'
            '  if(!id)return;'
            '  var el=document.getElementById(id.replace("#",""));'
            '  if(el)sections.push({el:el,link:a});'
            '});'
            'function setActive(id){'
            '  navLinks.forEach(function(a){a.classList.remove("active")});'
            '  var target=document.querySelector(".layer-nav a[href=\\""+id+"\\"]");'
            '  if(target)target.classList.add("active");'
            '}'
            'navLinks.forEach(function(a){'
            '  a.addEventListener("click",function(e){'
            '    setActive(this.getAttribute("href"));'
            '  });'
            '});'
            'if(window.IntersectionObserver){'
            '  var observer=new IntersectionObserver(function(entries){'
            '    entries.forEach(function(entry){'
            '      if(entry.isIntersecting){'
            '        setActive("#"+entry.target.id);'
            '      }'
            '    });'
            '  },{rootMargin:"-50% 0px -50% 0px"});'
            '  sections.forEach(function(s){observer.observe(s.el)});'
            '}else{'
            '  var ticking=false;'
            '  window.addEventListener("scroll",function(){'
            '    if(!ticking){'
            '      requestAnimationFrame(function(){'
            '        var scrollPos=window.scrollY+window.innerHeight/2;'
            '        var activeId="";'
            '        sections.forEach(function(s){'
            '          if(s.el.offsetTop<=scrollPos)activeId="#"+s.el.id;'
            '        });'
            '        if(activeId)setActive(activeId);'
            '        ticking=false;'
            '      });'
            '      ticking=true;'
            '    }'
            '  });'
            '}'
            '})();'
            '</script>'
        )
        return (
            "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>AgentLens 审计报告</title>\n"
            f"<style>{self._CSS}</style>\n"
            "</head>\n<body>\n<div class=\"container\">\n"
            + self._section_header(self._r)
            + nav_html
            + self._dashboard()
            + self._section_graph(self._r.get("graph", {}))
            + self._section_decision(self._r.get("decision", {}))
            + self._section_evidence(self._r.get("evidence", {}))
            + self._section_cost(self._r.get("cost", {}))
            + self._section_shadow(self._r.get("shadow", {}))
            + self._section_compliance(self._r.get("compliance", {}))
            + self._section_compliance_mapping()
            + self._section_remediation_priority()
            + self._section_footer()
            + scrollspy_js
            + "</div>\n</body>\n</html>"
        )


# ──────────────────────────────────────────────────────────────────────
# Diff HTML builder
# ──────────────────────────────────────────────────────────────────────

class _DiffHtmlBuilder:
    def __init__(self, diff: dict, baseline_path: str, current_path: str):
        self._d = diff
        self._baseline = baseline_path
        self._current = current_path
        self._now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _esc(self, text) -> str:
        return html.escape(str(text))

    def _delta_class(self, val) -> str:
        if val > 0:
            return "delta-positive"
        elif val < 0:
            return "delta-negative"
        return "delta-zero"

    def _delta_sign(self, raw_val, display_val: str) -> str:
        if isinstance(raw_val, (int, float)) and raw_val > 0:
            return f"+{display_val}"
        return str(display_val)

    def _metric_row(self, label: str, b_val, c_val, delta_raw, delta_display: str = None) -> str:
        if delta_display is None:
            delta_display = str(delta_raw)
        return (
            f"<tr><td>{label}</td>"
            f"<td class='num'>{b_val}</td>"
            f"<td class='num'>{c_val}</td>"
            f"<td class='num {self._delta_class(delta_raw)}'>{self._delta_sign(delta_raw, delta_display)}</td></tr>"
        )

    def _pct(self, val: float) -> str:
        return f"{val * 100:.1f}%"

    def _cost_fmt(self, val: float) -> str:
        return f"{val:.6f} CNY"

    def build(self) -> str:
        baseline = self._d.get("baseline", {})
        current = self._d.get("current", {})
        deltas = self._d.get("deltas", {})

        rows = []
        rows.append(self._metric_row("Events Loaded",
            baseline.get("events_loaded", 0), current.get("events_loaded", 0),
            deltas.get("events_loaded", 0)))
        rows.append(self._metric_row("Total Cost",
            self._cost_fmt(baseline.get("total_cost", 0)),
            self._cost_fmt(current.get("total_cost", 0)),
            deltas.get("total_cost", 0), self._cost_fmt(deltas.get("total_cost", 0))))
        rows.append(self._metric_row("Avoidable Cost Ratio",
            self._pct(baseline.get("avoidable_cost_ratio", 0)),
            self._pct(current.get("avoidable_cost_ratio", 0)),
            deltas.get("avoidable_cost_ratio", 0), self._pct(deltas.get("avoidable_cost_ratio", 0))))
        rows.append(self._metric_row("Findings Total",
            baseline.get("findings_total", 0), current.get("findings_total", 0),
            deltas.get("findings_total", 0)))
        rows.append(self._metric_row("  High",
            baseline.get("findings", {}).get("high", 0),
            current.get("findings", {}).get("high", 0),
            deltas.get("findings_high", 0)))
        rows.append(self._metric_row("  Medium",
            baseline.get("findings", {}).get("medium", 0),
            current.get("findings", {}).get("medium", 0),
            deltas.get("findings_medium", 0)))
        rows.append(self._metric_row("  Low",
            baseline.get("findings", {}).get("low", 0),
            current.get("findings", {}).get("low", 0),
            deltas.get("findings_low", 0)))
        rows.append(self._metric_row("  Info",
            baseline.get("findings", {}).get("info", 0),
            current.get("findings", {}).get("info", 0),
            deltas.get("findings_info", 0)))
        rows.append(self._metric_row("Closure Rate",
            self._pct(baseline.get("closure_rate", 0)),
            self._pct(current.get("closure_rate", 0)),
            deltas.get("closure_rate", 0), self._pct(deltas.get("closure_rate", 0))))

        css = """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  background:#f5f6fa;color:#2d3436;line-height:1.6;padding:20px}
.container{max-width:900px;margin:0 auto}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:30px;
  border-radius:12px;margin-bottom:24px}
.header h1{font-size:24px;margin-bottom:16px}
.header-meta{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;opacity:0.85}
.section{background:#fff;border-radius:10px;padding:24px;margin-bottom:20px;
  box-shadow:0 1px 4px rgba(0,0,0,0.06)}
.section h2{font-size:18px;border-bottom:2px solid #eee;padding-bottom:10px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #eee}
th{background:#f8f9fa;font-weight:600;color:#555}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover{background:#f8f9fa}
.delta-positive{color:#198754;font-weight:700}
.delta-negative{color:#dc3545;font-weight:700}
.delta-zero{color:#6c757d}
.footer{margin-top:30px;padding:20px;text-align:center;color:#888;font-size:12px;
  border-top:1px solid #ddd}
.disclaimer{color:#aaa;font-size:11px;margin-top:6px}
"""

        return (
            "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>AgentLens 审计对比报告</title>\n"
            f"<style>{css}</style>\n"
            "</head>\n<body>\n<div class=\"container\">\n"
            f'<div class="header">'
            f'<h1>AgentLens 审计对比报告</h1>'
            f'<div class="header-meta">'
            f'<span>基线: <strong>{self._esc(self._baseline)}</strong></span>'
            f'<span>当前: <strong>{self._esc(self._current)}</strong></span>'
            f'<span>生成时间: <strong>{self._esc(self._now)}</strong></span>'
            f'</div></div>'
            f'<div class="section">'
            f'<h2>指标对比</h2>'
            f'<table><thead><tr>'
            f'<th>指标</th><th>基线 (Baseline)</th><th>当前 (Current)</th><th>变化 (Delta)</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f'</div>'
            f'<div class="footer">'
            f'<p>本报告由 agentlens-cli 自动生成 — {self._esc(self._now)}</p>'
            f'<p class="disclaimer">免责声明：本对比报告基于两次审计事件流自动分析生成，'
            f'仅供审计参考，不构成法律或合规建议。所有成本数据均为估算值。</p>'
            f'</div>'
            f'</div>\n</body>\n</html>'
        )
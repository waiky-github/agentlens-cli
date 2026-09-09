"""FastAPI Web 服务：REST API + 浏览器操作界面（Langfuse 式观测平台）。

提供审计报告浏览、审计触发、watchdog 漂移状态查看、趋势数据等功能。
"""

import base64
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from starlette.middleware.base import BaseHTTPMiddleware
except ImportError:
    raise ImportError(
        "Web dependencies not installed. Run: pip install agentlens-audit[web]"
    )

# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────

REPORT_DIR = Path(
    os.environ.get(
        "AGENTLENS_REPORT_DIR",
        os.path.expanduser("~/.hermes/agentlens-reports"),
    )
)

app = FastAPI(title="AgentLens Audit Web", version="0.2.1")

# In-memory task log for /audit page
_TASKS_FILE = REPORT_DIR / "audit-tasks.json"
_AUDIT_TASKS: list[dict] = []
_TASK_ID_COUNTER = 0


def _load_tasks() -> list[dict]:
    """Load persisted audit tasks from JSON file. Returns empty list on failure."""
    global _TASK_ID_COUNTER
    if not _TASKS_FILE.is_file():
        return []
    try:
        data = json.loads(_TASKS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            # Determine max id for counter
            ids = [t.get("id", 0) for t in data if isinstance(t, dict)]
            _TASK_ID_COUNTER = max(ids) if ids else 0
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_tasks():
    """Persist audit tasks to JSON file atomically (write temp + os.replace)."""
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _TASKS_FILE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(_AUDIT_TASKS, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, _TASKS_FILE)
    except OSError:
        pass


# Load persisted tasks on module import
_AUDIT_TASKS = _load_tasks()


# ─────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/reports/") and request.url.path.endswith("/html"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth 访问控制。

    若设置了 AGENTLENS_WEB_PASSWORD 环境变量则强制校验（用户名默认 admin，
    可用 AGENTLENS_WEB_USERNAME 覆盖）；未设置则放行（本地/开发模式）。
    """

    def __init__(self, app):
        super().__init__(app)
        self._username = os.environ.get("AGENTLENS_WEB_USERNAME", "admin")
        self._password = os.environ.get("AGENTLENS_WEB_PASSWORD", "")
        self._enabled = bool(self._password)

    async def dispatch(self, request: Request, call_next):
        if not self._enabled:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        ok = False
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                user, _, pwd = decoded.partition(":")
                ok = secrets.compare_digest(user, self._username) and secrets.compare_digest(
                    pwd, self._password
                )
            except Exception:
                ok = False
        if not ok:
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="AgentLens Audit"'},
            )
        return await call_next(request)


app.add_middleware(NoCacheMiddleware)
app.add_middleware(BasicAuthMiddleware)


# ─────────────────────────────────────────────────────────────────
# HTML parsing helpers
# ─────────────────────────────────────────────────────────────────

def _parse_html_report(html_content: str) -> dict:
    """Parse an audit HTML report to extract metadata fields.

    Returns a dict with keys: events, high, medium, low, info, findings_total,
    total_cost, est_waste, total_tokens_in, avoidable_cost_ratio.
    Values are 0 if parsing fails.
    """
    result = {
        "events": 0, "high": 0, "medium": 0, "low": 0, "info": 0,
        "findings_total": 0, "total_cost": 0.0, "est_waste": 0.0,
        "total_tokens_in": 0, "avoidable_cost_ratio": 0.0,
    }

    # Events count: <span>事件数: <strong>N</strong></span>
    m = re.search(r"事件数[：:]\s*<strong>(\d+)</strong>", html_content)
    if m:
        result["events"] = int(m.group(1))

    # Severity distribution in KPI sub text: e.g. "High 1 / Med 0 / Low 2 / Info 0"
    m = re.search(
        r"High\s+(\d+)\s*/\s*Med\s+(\d+)\s*/\s*Low\s+(\d+)\s*/\s*Info\s+(\d+)",
        html_content,
    )
    if m:
        result["high"] = int(m.group(1))
        result["medium"] = int(m.group(2))
        result["low"] = int(m.group(3))
        result["info"] = int(m.group(4))
        result["findings_total"] = result["high"] + result["medium"] + result["low"] + result["info"]
    else:
        # Fallback: count FINDING severity badges in the HTML
        for sev, label in [("high", "HIGH"), ("medium", "MEDIUM"), ("low", "LOW"), ("info", "INFO")]:
            count = len(re.findall(rf">\s*{label}\s*<", html_content))
            result[sev] = count
        result["findings_total"] = result["high"] + result["medium"] + result["low"] + result["info"]

    # Total cost: 总成本: <strong>846.271500 CNY</strong>
    m = re.search(r"总成本[：:]\s*<strong>([\d.]+)\s*CNY</strong>", html_content)
    if m:
        result["total_cost"] = float(m.group(1))

    # Est waste: 预估浪费: <strong>649.391234 CNY</strong>
    m = re.search(r"预估浪费[：:]\s*<strong>([\d.]+)\s*CNY</strong>", html_content)
    if m:
        result["est_waste"] = float(m.group(1))

    # Total tokens in: 总输入 Token: <strong>12,345</strong>
    m = re.search(r"总输入\s*Token[：:]\s*<strong>([\d,]+)</strong>", html_content)
    if m:
        result["total_tokens_in"] = int(m.group(1).replace(",", ""))

    # Avoidable cost ratio: 可避免占比: <strong>76.7%</strong>
    m = re.search(r"可避免占比[：:]\s*<strong>([\d.]+)%</strong>", html_content)
    if m:
        result["avoidable_cost_ratio"] = float(m.group(1)) / 100.0

    return result


def _list_report_files() -> list[dict]:
    """List all audit-*.html files in the report directory with metadata."""
    reports = []
    if not REPORT_DIR.is_dir():
        return reports

    for f in sorted(REPORT_DIR.glob("audit-*.html"), reverse=True):
        m = re.match(r"audit-(\d{8})\.html", f.name)
        if not m:
            continue
        date_str = m.group(1)
        stat = f.stat()
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        try:
            html = f.read_text(encoding="utf-8")
        except Exception:
            html = ""
        meta = _parse_html_report(html)

        reports.append({
            "date": date_str,
            "filename": f.name,
            "size_bytes": size,
            "mtime": mtime,
            "events": meta["events"],
            "high": meta["high"],
            "medium": meta["medium"],
            "low": meta["low"],
            "info": meta["info"],
            "findings_total": meta["findings_total"],
            "total_cost": meta["total_cost"],
            "est_waste": meta["est_waste"],
            "total_tokens_in": meta["total_tokens_in"],
        })

    return reports


def _get_report_path(date_str: str) -> Optional[Path]:
    """Get the report file path for a given date string (YYYYMMDD)."""
    f = REPORT_DIR / f"audit-{date_str}.html"
    if f.is_file():
        return f
    return None


# ─────────────────────────────────────────────────────────────────
# CSS: Dark theme (Langfuse-style)
# ─────────────────────────────────────────────────────────────────

_CSS_DARK = """\
:root{--bg-primary:#0f1117;--bg-panel:#171a21;--bg-sidebar:#0b0d12;--border:#262b36;
  --text-primary:#e6e9ef;--text-secondary:#8b93a7;--brand:#4f8cff;--success:#22c55e;
  --warning:#f59e0b;--danger:#ef4444;--purple:#8b5cf6}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  background:var(--bg-primary);color:var(--text-primary);line-height:1.6}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}
/* ── sidebar ── */
.sidebar{position:fixed;left:0;top:0;bottom:0;width:220px;background:var(--bg-sidebar);
  border-right:1px solid var(--border);display:flex;flex-direction:column;z-index:100;
  overflow-y:auto}
.sidebar-brand{padding:20px 20px 12px}
.sidebar-brand .logo{font-size:18px;font-weight:800;color:var(--text-primary);display:flex;
  align-items:center;gap:8px}
.sidebar-brand .logo-icon{color:var(--brand)}
.sidebar-brand .sub{font-size:11px;color:var(--text-secondary);margin-top:2px}
.sidebar-nav{flex:1;padding:8px 12px}
.sidebar-nav a{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:6px;
  font-size:13px;font-weight:500;color:var(--text-secondary);transition:all 0.15s;
  margin-bottom:2px;text-decoration:none}
.sidebar-nav a:hover{background:rgba(79,140,255,0.08);color:var(--text-primary);text-decoration:none}
.sidebar-nav a.active{background:#1a2233;color:var(--brand);border-left:3px solid var(--brand);
  padding-left:9px}
.sidebar-nav .nav-icon{font-size:15px;width:20px;text-align:center}
.sidebar-footer{padding:12px 20px;border-top:1px solid var(--border);font-size:11px;
  color:var(--text-secondary)}
.sidebar-footer .ver{margin-bottom:4px}
/* ── main content ── */
.main-content{margin-left:220px;min-height:100vh;display:flex;flex-direction:column}
.full-width{margin-left:0}
/* ── topbar ── */
.topbar{height:56px;background:var(--bg-panel);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;padding:0 24px;
  position:sticky;top:0;z-index:50}
.topbar-title{font-size:15px;font-weight:700}
.topbar-right{display:flex;align-items:center;gap:12px}
.topbar-right .time-filter{display:flex;gap:4px}
.topbar-right .time-filter button{padding:4px 12px;border-radius:4px;font-size:12px;
  border:1px solid var(--border);background:transparent;color:var(--text-secondary);
  cursor:pointer;transition:all 0.15s}
.topbar-right .time-filter button:hover{background:var(--bg-panel);color:var(--text-primary)}
.topbar-right .time-filter button.active{background:var(--brand);color:#fff;border-color:var(--brand)}
/* ── page content ── */
.page-content{padding:24px;flex:1}
/* ── KPI grid ── */
.kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px}
.kpi-card{background:var(--bg-panel);border:1px solid var(--border);border-radius:8px;
  padding:16px 20px;position:relative;overflow:hidden}
.kpi-card .kpi-label{font-size:11px;color:var(--text-secondary);text-transform:uppercase;
  letter-spacing:0.5px;margin-bottom:6px}
.kpi-card .kpi-value{font-size:28px;font-weight:800;line-height:1.2}
.kpi-card .kpi-sub{font-size:11px;color:var(--text-secondary);margin-top:2px}
.kpi-card .kpi-spark{position:absolute;right:12px;bottom:12px;width:80px;height:24px}
.kpi-card .kpi-accent{position:absolute;top:0;left:0;right:0;height:3px;border-radius:8px 8px 0 0}
.kpi-card .kpi-accent.blue{background:var(--brand)}
.kpi-card .kpi-accent.red{background:var(--danger)}
.kpi-card .kpi-accent.green{background:var(--success)}
.kpi-card .kpi-accent.orange{background:var(--warning)}
.kpi-card .kpi-accent.purple{background:var(--purple)}
.kpi-card .kpi-accent.gray{background:var(--text-secondary)}
/* ── card ── */
.card{background:var(--bg-panel);border:1px solid var(--border);border-radius:8px;
  padding:20px;margin-bottom:20px}
.card h2{font-size:15px;font-weight:700;margin-bottom:16px;padding-bottom:10px;
  border-bottom:1px solid var(--border)}
.card h3{font-size:13px;margin:16px 0 8px;color:var(--text-secondary)}
/* ── chart grid ── */
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
.chart-box{background:var(--bg-panel);border:1px solid var(--border);border-radius:8px;
  padding:16px}
.chart-box h4{font-size:13px;color:var(--text-secondary);margin:0 0 12px;font-weight:600}
.chart-box.wide{grid-column:1/-1}
.chart-canvas{width:100%;height:300px}
.chart-canvas-sm{width:100%;height:200px}
.chart-canvas-spark{width:100%;height:24px}
/* ── table ── */
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)}
th{background:rgba(139,147,167,0.06);font-weight:600;color:var(--text-secondary);
  font-size:11px;text-transform:uppercase;letter-spacing:0.5px;cursor:pointer;
  user-select:none;white-space:nowrap}
th:hover{color:var(--text-primary)}
th .sort-arrow{font-size:10px;margin-left:2px;opacity:0.4}
th.sorted .sort-arrow{opacity:1;color:var(--brand)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover{background:rgba(79,140,255,0.04)}
/* ── badges ── */
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700}
.badge-ok{background:rgba(34,197,94,0.15);color:var(--success)}
.badge-warn{background:rgba(245,158,11,0.15);color:var(--warning)}
.badge-err{background:rgba(239,68,68,0.15);color:var(--danger)}
.badge-info{background:rgba(79,140,255,0.15);color:var(--brand)}
/* ── severity ── */
.sev-high{color:var(--danger);font-weight:700}
.sev-medium{color:var(--warning);font-weight:700}
.sev-low{color:#ffc107;font-weight:700}
.sev-info{color:var(--brand);font-weight:700}
/* ── dot indicator ── */
.dot-red{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--danger);
  margin-right:4px;vertical-align:middle}
/* ── buttons ── */
.btn{display:inline-block;padding:8px 18px;border-radius:6px;font-size:13px;font-weight:600;
  border:none;cursor:pointer;text-decoration:none;transition:all 0.15s;color:#fff}
.btn:hover{opacity:0.85;text-decoration:none}
.btn-primary{background:var(--brand)}
.btn-success{background:var(--success)}
.btn-danger{background:var(--danger)}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--text-secondary)}
.btn-ghost:hover{background:var(--bg-panel);color:var(--text-primary)}
.btn-sm{padding:4px 10px;font-size:12px}
.btn:disabled{opacity:0.5;cursor:not-allowed}
/* ── forms ── */
.form-group{margin-bottom:14px}
.form-group label{display:block;font-size:12px;font-weight:600;margin-bottom:4px;
  color:var(--text-secondary)}
.form-group input{width:100%;padding:10px 14px;border:1px solid var(--border);
  border-radius:6px;font-size:14px;background:var(--bg-primary);color:var(--text-primary)}
.form-group input:focus{outline:none;border-color:var(--brand);
  box-shadow:0 0 0 2px rgba(79,140,255,0.15)}
.form-group input::placeholder{color:var(--text-secondary)}
/* ── result boxes ── */
.result-box{margin-top:12px;padding:12px 16px;border-radius:6px;font-size:13px}
.result-box.success{background:rgba(34,197,94,0.1);color:var(--success);border:1px solid rgba(34,197,94,0.2)}
.result-box.error{background:rgba(239,68,68,0.1);color:var(--danger);border:1px solid rgba(239,68,68,0.2)}
.result-box.info{background:rgba(79,140,255,0.1);color:var(--brand);border:1px solid rgba(79,140,255,0.2)}
/* ── empty state ── */
.empty{color:var(--text-secondary);font-style:italic;padding:30px;text-align:center}
.empty-big{padding:60px 20px;text-align:center}
.empty-big .empty-icon{font-size:40px;margin-bottom:12px}
.empty-big .empty-text{color:var(--text-secondary);font-size:14px}
/* ── search ── */
.search-box{display:flex;align-items:center;gap:8px;margin-bottom:16px}
.search-box input{padding:8px 14px;border:1px solid var(--border);border-radius:6px;
  font-size:13px;background:var(--bg-primary);color:var(--text-primary);width:240px}
.search-box input:focus{outline:none;border-color:var(--brand)}
.search-box input::placeholder{color:var(--text-secondary)}
/* ── report list ── */
.report-link{color:var(--brand);font-weight:600;text-decoration:none}
.report-link:hover{text-decoration:underline}
/* ── breadcrumb ── */
.breadcrumb{display:flex;align-items:center;gap:8px;font-size:13px;padding:0}
.breadcrumb a{color:var(--text-secondary)}
.breadcrumb a:hover{color:var(--text-primary)}
.breadcrumb .sep{color:var(--text-secondary)}
/* ── iframe ── */
.iframe-wrap{background:var(--bg-panel);border:1px solid var(--border);border-radius:8px;
  overflow:hidden}
.iframe-wrap iframe{width:100%;height:calc(100vh - 120px);border:none}
/* ── summary list ── */
.summary-list{list-style:none;padding:0}
.summary-list li{padding:6px 0;font-size:13px;border-bottom:1px solid var(--border)}
.summary-list li:last-child{border-bottom:none}
.summary-list .finding-title{color:var(--text-primary);font-weight:600}
.summary-list .finding-sev{font-size:10px;margin-left:8px}
/* ── task list ── */
.task-list{list-style:none;padding:0}
.task-list li{padding:10px 0;border-bottom:1px solid var(--border);font-size:13px;
  display:flex;align-items:center;gap:12px}
.task-list li:last-child{border-bottom:none}
.task-list .task-time{color:var(--text-secondary);font-size:11px;min-width:70px}
.task-list .task-status{font-size:11px;font-weight:600}
/* ── footer ── */
.footer{margin-top:30px;padding:20px;text-align:center;color:var(--text-secondary);
  font-size:11px;border-top:1px solid var(--border)}
/* ── responsive ── */
@media(max-width:768px){
  .sidebar{width:100%;height:auto;position:relative;flex-direction:row;flex-wrap:wrap;
    padding:8px;align-items:center}
  .sidebar-brand{padding:0;flex:0 0 auto}
  .sidebar-nav{display:flex;flex:1;padding:0;gap:4px;overflow-x:auto}
  .sidebar-nav a{white-space:nowrap;padding:6px 10px;font-size:12px}
  .sidebar-nav a.active{border-left:none;border-bottom:2px solid var(--brand);padding-left:10px}
  .sidebar-footer{display:none}
  .main-content{margin-left:0}
  .kpi-grid{grid-template-columns:repeat(2,1fr)}
  .chart-grid{grid-template-columns:1fr}
  .topbar{padding:0 12px}
  .page-content{padding:12px}
}
@media(min-width:1400px){
  .kpi-grid{grid-template-columns:repeat(6,1fr)}
}
"""


# ─────────────────────────────────────────────────────────────────
# Page builders
# ─────────────────────────────────────────────────────────────────

def _sidebar_html(active_nav: str = "") -> str:
    """Build the sidebar navigation HTML."""
    nav_items = [
        ("/", "📊", "仪表盘"),
        ("/reports", "📄", "报告列表"),
        ("/audit", "🔍", "触发审计"),
        ("/#watchdog", "🛡", "Watchdog"),
    ]
    nav_links = []
    for href, icon, label in nav_items:
        cls = "active" if href == active_nav or (active_nav == "/" and href == "/") else ""
        nav_links.append(
            f'<a href="{href}" class="{cls}">'
            f'<span class="nav-icon">{icon}</span>{label}</a>'
        )

    return (
        '<aside class="sidebar">'
        f'<div class="sidebar-brand">'
        f'<div class="logo"><span class="logo-icon">◈</span> AgentLens</div>'
        f'<div class="sub">Audit Platform</div>'
        f'</div>'
        f'<nav class="sidebar-nav">{"".join(nav_links)}</nav>'
        f'<div class="sidebar-footer">'
        f'<div class="ver">v0.2.1</div>'
        f'<div>报告目录: {REPORT_DIR}</div>'
        f'</div>'
        f'</aside>'
    )


def _topbar_html(title: str, extra: str = "") -> str:
    """Build the topbar with title and optional right-side content."""
    return (
        '<header class="topbar">'
        f'<div class="topbar-title">{title}</div>'
        f'<div class="topbar-right">{extra}</div>'
        f'</header>'
    )


def _time_filter_html() -> str:
    return (
        '<div class="time-filter" id="time-filter">'
        '<button data-range="all" class="active">全部</button>'
        '<button data-range="7d">近 7 天</button>'
        '<button data-range="30d">近 30 天</button>'
        '</div>'
    )


def _base_page(title: str, content: str, active_nav: str = "", full_width: bool = False,
               topbar_title: str = "", topbar_extra: str = "", extra_head: str = "") -> str:
    """Build a complete HTML page with sidebar + topbar + content."""
    if not topbar_title:
        topbar_title = title

    main_class = "main-content full-width" if full_width else "main-content"

    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        f"<title>{title} — AgentLens Audit</title>\n"
        f"<style>{_CSS_DARK}</style>\n"
        f"{extra_head}\n"
        "</head>\n<body>\n"
        f'<div class="app-layout">\n'
        + ("" if full_width else _sidebar_html(active_nav))
        + f'<div class="{main_class}">\n'
        + _topbar_html(topbar_title, topbar_extra)
        + f'<div class="page-content">\n'
        + content
        + "\n</div>\n</div>\n</div>\n"
        # Time filter JS
        + (
            '<script>(function(){'
            'var btns=document.querySelectorAll("#time-filter button");'
            'var saved=localStorage.getItem("agentlens_time_range")||"all";'
            'btns.forEach(function(b){'
            '  b.classList.toggle("active",b.dataset.range===saved);'
            '  b.addEventListener("click",function(){'
            '    localStorage.setItem("agentlens_time_range",this.dataset.range);'
            '    btns.forEach(function(x){x.classList.remove("active")});'
            '    this.classList.add("active");'
            '    window.dispatchEvent(new CustomEvent("timerange",{detail:this.dataset.range}));'
            '  });'
            '});'
            '})();</script>'
            if "time-filter" in content else ""
        )
        + "</body>\n</html>"
    )


def _js(obj) -> str:
    """Serialize obj to a JS-safe JSON literal."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


# ── Dashboard page ──────────────────────────────────────────────

def _build_dashboard() -> str:
    reports = _list_report_files()

    # Latest report
    latest = reports[0] if reports else None
    latest_date = latest["date"] if latest else "—"
    latest_events = latest["events"] if latest else 0
    latest_findings = latest["findings_total"] if latest else 0
    latest_high = latest["high"] if latest else 0
    latest_cost = latest["total_cost"] if latest else 0
    latest_waste = latest["est_waste"] if latest else 0

    # Aggregate across all reports
    total_events = sum(r["events"] for r in reports)
    total_cost_all = sum(r["total_cost"] for r in reports)
    total_high_all = sum(r["high"] for r in reports)

    # Trends data for sparklines and chart
    # Reports are sorted reverse-chronological; reverse for chronological order
    trends_reports = list(reversed(reports))
    trends_dates = [r["date"] for r in trends_reports]
    trends_cost = [round(r["total_cost"], 2) for r in trends_reports]
    trends_waste = [round(r["est_waste"], 2) for r in trends_reports]
    trends_findings = [r["findings_total"] for r in trends_reports]
    trends_high = [r["high"] for r in trends_reports]
    trends_events = [r["events"] for r in trends_reports]
    trends_cost_agg = [round(r["total_cost"], 2) for r in trends_reports]

    trends_js = _js({
        "dates": trends_dates,
        "cost": trends_cost,
        "waste": trends_waste,
        "findings": trends_findings,
        "high": trends_high,
        "events": trends_events,
    })

    # Format dates for display
    date_display = (
        f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:8]}"
        if latest_date != "—" else "—"
    )

    # KPI cards
    kpi_cards = (
        f'<div class="kpi-card">'
        f'<div class="kpi-accent blue"></div>'
        f'<div class="kpi-label">最新报告日期</div>'
        f'<div class="kpi-value" style="font-size:22px">{date_display}</div>'
        f'<div class="kpi-sub">共 {len(reports)} 份报告</div>'
        f'</div>'
        f'<div class="kpi-card">'
        f'<div class="kpi-accent {"red" if latest_high > 0 else "green"}"></div>'
        f'<div class="kpi-label">总发现数</div>'
        f'<div class="kpi-value">{latest_findings}</div>'
        f'<div class="kpi-sub">High {latest_high} / Med {latest["medium"] if latest else 0}</div>'
        f'<div class="kpi-spark"><div id="spark-findings" class="chart-canvas-spark"></div></div>'
        f'</div>'
        f'<div class="kpi-card">'
        f'<div class="kpi-accent {"red" if latest_high > 0 else "green"}"></div>'
        f'<div class="kpi-label">高风险数</div>'
        f'<div class="kpi-value">{latest_high}</div>'
        f'<div class="kpi-sub">累计 {total_high_all}</div>'
        f'<div class="kpi-spark"><div id="spark-high" class="chart-canvas-spark"></div></div>'
        f'</div>'
        f'<div class="kpi-card">'
        f'<div class="kpi-accent orange"></div>'
        f'<div class="kpi-label">预估浪费 CNY</div>'
        f'<div class="kpi-value">{latest_waste:.2f}</div>'
        f'<div class="kpi-sub">总成本 {latest_cost:.2f}</div>'
        f'<div class="kpi-spark"><div id="spark-waste" class="chart-canvas-spark"></div></div>'
        f'</div>'
        f'<div class="kpi-card">'
        f'<div class="kpi-accent blue"></div>'
        f'<div class="kpi-label">事件总数</div>'
        f'<div class="kpi-value">{latest_events}</div>'
        f'<div class="kpi-sub">累计 {total_events}</div>'
        f'</div>'
        f'<div class="kpi-card">'
        f'<div class="kpi-accent purple"></div>'
        f'<div class="kpi-label">成本合计 CNY</div>'
        f'<div class="kpi-value">{latest_cost:.2f}</div>'
        f'<div class="kpi-sub">累计 {total_cost_all:.2f}</div>'
        f'</div>'
    )

    # Watchdog status
    baseline_path = REPORT_DIR / "baseline.json"
    baseline_exists = baseline_path.is_file()
    baseline_mtime = "—"
    baseline_events = 0
    if baseline_exists:
        try:
            baseline_mtime = datetime.fromtimestamp(
                baseline_path.stat().st_mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline_events = baseline.get("events_loaded", 0)
        except Exception:
            baseline_exists = False

    if baseline_exists:
        wd_badge = '<span class="badge badge-ok">基线存在</span>'
    else:
        wd_badge = '<span class="badge badge-warn">尚未建立基线，运行首次审计后生成</span>'

    watchdog_html = (
        f'<div class="card" id="watchdog"><h2>🛡 Watchdog 漂移状态</h2>'
        f'<table><tbody>'
        f'<tr><td style="width:120px">基线文件</td><td>{wd_badge}</td></tr>'
        f'<tr><td>更新时间</td><td>{baseline_mtime}</td></tr>'
        f'<tr><td>基线事件数</td><td>{baseline_events}</td></tr>'
        f'</tbody></table></div>'
    )

    # Latest report summary
    if latest:
        # Try to extract top finding titles
        path = _get_report_path(latest["date"])
        titles = []
        if path:
            try:
                html = path.read_text(encoding="utf-8")
                # Extract finding titles from the report
                title_matches = re.findall(
                    r'<strong>([^<]+)</strong>',
                    html[html.find("layer-"):] if "layer-" in html else html
                )
                # Filter to likely finding titles (not KPI labels)
                skip_words = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                              "N/A", "无", "检出", "High", "Medium", "Low"}
                titles = [t for t in title_matches if t not in skip_words and len(t) > 3][:3]
            except Exception:
                titles = []

        titles_html = ""
        if titles:
            titles_html = "".join(
                f'<li><span class="finding-title">{t[:60]}{"…" if len(t) > 60 else ""}</span></li>'
                for t in titles
            )
        else:
            titles_html = '<li class="empty">无法解析发现标题</li>'

        latest_summary = (
            f'<div class="card"><h2>📋 最新报告摘要</h2>'
            f'<div style="display:flex;gap:24px;margin-bottom:16px;font-size:13px">'
            f'<span>报告日期: <strong>{date_display}</strong></span>'
            f'<span>事件数: <strong>{latest_events}</strong></span>'
            f'<span>发现数: <strong>{latest_findings}</strong></span>'
            f'</div>'
            f'<h3>Top 发现标题</h3>'
            f'<ul class="summary-list">{titles_html}</ul>'
            f'</div>'
        )
    else:
        latest_summary = (
            '<div class="card"><h2>📋 最新报告摘要</h2>'
            '<p class="empty">暂无报告</p></div>'
        )

    # Recent audit dynamics
    recent_rows = []
    for r in reports[:5]:
        date_fmt = f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:8]}"
        dot = '<span class="dot-red"></span>' if r["high"] > 0 else ""
        recent_rows.append(
            f'<tr><td>{dot}{date_fmt}</td>'
            f'<td class="num">{r["findings_total"]}</td>'
            f'<td class="num"><span class="sev-high">{r["high"]}</span></td>'
            f'<td><a href="/reports/{r["date"]}" class="report-link">查看</a></td></tr>'
        )

    recent_html = (
        f'<div class="card"><h2>📊 最近审计动态</h2>'
        f'<table><thead><tr><th>日期</th><th>发现</th><th>High</th><th>操作</th></tr></thead>'
        f'<tbody>{"".join(recent_rows) if recent_rows else "<tr><td colspan=4 class=empty>暂无</td></tr>"}'
        f'</tbody></table></div>'
    )

    content = (
        f'<div class="kpi-grid">{kpi_cards}</div>'
        f'<div class="chart-grid">'
        f'<div class="chart-box wide"><h4>成本趋势（总成本 vs 预估浪费）</h4>'
        f'<div id="chart-trend" class="chart-canvas-sm"></div>'
        f'<div id="chart-trend-hint" style="display:none;text-align:center;padding:20px;'
        f'color:var(--text-secondary);font-size:13px">数据积累中 — 需要多份报告展示趋势</div>'
        f'</div>'
        f'<div class="chart-box"><h4>严重度分布（最新报告）</h4>'
        f'<div id="chart-severity" class="chart-canvas"></div></div>'
        f'</div>'
        + latest_summary
        + watchdog_html
        + recent_html
        # ECharts + dashboard init
        + '<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>'
        + '<script>'
        + f'var TRENDS={trends_js};'
        + '(function(){'
        + 'if(typeof echarts==="undefined"){'
        + '  var boxes=document.querySelectorAll(".chart-canvas,.chart-canvas-sm,.chart-canvas-spark");'
        + '  for(var i=0;i<boxes.length;i++){'
        + '    boxes[i].innerHTML="<div style=\\"color:#8b93a7;text-align:center;padding:20px\\">'
        + '图表需要联网加载 ECharts</div>";'
        + '  }'
        + '  return;'
        + '}'
        # Trend chart
        + 'if(TRENDS.dates.length>0){'
        + '  var trendDates=TRENDS.dates.map(function(d){return d.slice(4,6)+"-"+d.slice(6,8)});'
        + '  if(TRENDS.dates.length===1){'
        + '    document.getElementById("chart-trend-hint").style.display="block";'
        + '  }'
        + '  var trendChart=echarts.init(document.getElementById("chart-trend"));'
        + '  trendChart.setOption({'
        + '    animation:false,'
        + '    tooltip:{trigger:"axis"},'
        + '    legend:{top:0,textStyle:{color:"#8b93a7"}},'
        + '    grid:{left:8,right:30,top:30,bottom:8,containLabel:true},'
        + '    xAxis:{type:"category",data:trendDates,axisLabel:{color:"#8b93a7"}},'
        + '    yAxis:['
        + '      {type:"value",name:"CNY",axisLabel:{color:"#8b93a7",formatter:function(v){return v.toFixed(2);}}},'
        + '      {type:"value",name:"CNY",splitLine:{show:false},axisLabel:{color:"#8b93a7",formatter:function(v){return v.toFixed(2);}}}'
        + '    ],'
        + '    series:['
        + '      {name:"总成本",type:"bar",data:TRENDS.cost,itemStyle:{color:"#4f8cff",borderRadius:[4,4,0,0]}},'
        + '      {name:"预估浪费",type:"line",yAxisIndex:1,data:TRENDS.waste,'
        + '        itemStyle:{color:"#ef4444"},smooth:true,'
        + '        lineStyle:{width:2},symbol:"circle",symbolSize:6}'
        + '    ]'
        + '  });'
        + '}'
        # Severity donut (latest report)
        + 'var sevData=['
        + f'  {{name:"High",value:{latest_high},itemStyle:{{color:"#ef4444"}}}},'
        + f'  {{name:"Medium",value:{latest["medium"] if latest else 0},itemStyle:{{color:"#f59e0b"}}}},'
        + f'  {{name:"Low",value:{latest["low"] if latest else 0},itemStyle:{{color:"#fbbf24"}}}},'
        + f'  {{name:"Info",value:{latest["info"] if latest else 0},itemStyle:{{color:"#4f8cff"}}}}'
        + '];'
        + 'var sevChart=echarts.init(document.getElementById("chart-severity"));'
        + 'sevChart.setOption({'
        + '  animation:false,'
        + '  tooltip:{trigger:"item",formatter:"{b}: {c} ({d}%)"},'
        + '  legend:{bottom:0,textStyle:{color:"#8b93a7"}},'
        + '  series:[{'
        + '    name:"严重度",type:"pie",radius:["45%","70%"],center:["50%","45%"],'
        + '    avoidLabelOverlap:true,'
        + '    itemStyle:{borderRadius:6,borderColor:"#0f1117",borderWidth:2},'
        + '    label:{show:true,formatter:"{b} {c}",color:"#8b93a7"},'
        + '    data:sevData'
        + '  }]'
        + '});'
        # Sparklines
        + 'function makeSparkline(elId,data,color){'
        + '  var el=document.getElementById(elId);'
        + '  if(!el||!data||data.length===0)return;'
        + '  var chart=echarts.init(el);'
        + '  chart.setOption({'
        + '    animation:false,'
        + '    grid:{left:0,right:0,top:2,bottom:2},'
        + '    xAxis:{show:false,data:data.map(function(_,i){return i})},'
        + '    yAxis:{show:false,min:function(v){return v.min-1},max:function(v){return v.max+1}},'
        + '    series:[{'
        + '      type:"line",data:data,smooth:true,symbol:"none",'
        + '      lineStyle:{color:color,width:1.5},'
        + '      areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,['
        + '        {offset:0,color:color+"40"},{offset:1,color:color+"05"}])}'
        + '    }]'
        + '  });'
        + '}'
        + f'makeSparkline("spark-findings",TRENDS.findings,"#4f8cff");'
        + f'makeSparkline("spark-high",TRENDS.high,"#ef4444");'
        + f'makeSparkline("spark-waste",TRENDS.waste,"#f59e0b");'
        # Resize handler
        + 'function resizeAll(){'
        + '  try{trendChart.resize()}catch(e){}'
        + '  try{sevChart.resize()}catch(e){}'
        + '}'
        + 'window.addEventListener("resize",resizeAll);'
        + '})();'
        + '</script>'
    )

    return _base_page(
        "仪表盘", content, active_nav="/",
        topbar_title="仪表盘", topbar_extra=_time_filter_html()
    )


# ── Reports list page ────────────────────────────────────────────

def _build_reports_list() -> str:
    reports = _list_report_files()

    if not reports:
        content = '<div class="empty-big"><div class="empty-icon">📄</div><div class="empty-text">暂无报告</div></div>'
        return _base_page("报告列表", content, active_nav="/reports",
                          topbar_title="报告列表", topbar_extra=_time_filter_html())

    rows = []
    for r in reports:
        date_fmt = f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:8]}"
        dot = '<span class="dot-red"></span>' if r["high"] > 0 else ""
        size_kb = round(r["size_bytes"] / 1024, 1)
        rows.append(
            f'<tr data-date="{r["date"]}">'
            f'<td>{dot}{date_fmt}</td>'
            f'<td class="num">{r["events"]}</td>'
            f'<td class="num">{r["findings_total"]}</td>'
            f'<td class="num"><span class="sev-high">{r["high"]}</span></td>'
            f'<td class="num"><span class="sev-medium">{r["medium"]}</span></td>'
            f'<td class="num"><span class="sev-low">{r["low"]}</span></td>'
            f'<td class="num">{r["est_waste"]:.2f}</td>'
            f'<td class="num">{size_kb} KB</td>'
            f'<td>'
            f'<a href="/reports/{r["date"]}" class="btn btn-primary btn-sm">查看</a> '
            f'<a href="/api/reports/{r["date"]}/html" class="btn btn-ghost btn-sm">原始 HTML</a>'
            f'</td></tr>'
        )

    content = (
        f'<div class="card"><h2>全部报告 ({len(reports)})</h2>'
        f'<div class="search-box">'
        f'<input type="text" id="report-search" placeholder="按日期搜索（如 20260909 或 09-09）…" '
        f'oninput="filterReports()">'
        f'</div>'
        f'<table id="report-table"><thead><tr>'
        f'<th data-sort="date" class="sorted" data-dir="desc">日期 <span class="sort-arrow">▼</span></th>'
        f'<th data-sort="events" class="num">事件 <span class="sort-arrow"></span></th>'
        f'<th data-sort="findings" class="num">发现 <span class="sort-arrow"></span></th>'
        f'<th data-sort="high" class="num">High <span class="sort-arrow"></span></th>'
        f'<th data-sort="medium" class="num">Med <span class="sort-arrow"></span></th>'
        f'<th data-sort="low" class="num">Low <span class="sort-arrow"></span></th>'
        f'<th data-sort="waste" class="num">预估浪费 <span class="sort-arrow"></span></th>'
        f'<th data-sort="size" class="num">大小 <span class="sort-arrow"></span></th>'
        f'<th>操作</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
        # Sort + search JS
        + '<script>'
        + '(function(){'
        + 'var table=document.getElementById("report-table");'
        + 'var tbody=table.querySelector("tbody");'
        + 'var headers=table.querySelectorAll("th[data-sort]");'
        + 'var currentSort="date";'
        + 'var currentDir="desc";'
        + 'function getVal(row,key){'
        + '  var cells=row.querySelectorAll("td");'
        + '  var idx={date:0,events:1,findings:2,high:3,medium:4,low:5,waste:6,size:7}[key];'
        + '  var text=cells[idx].textContent.trim().replace(/,|\\s*KB|CNY/g,"");'
        + '  if(key==="date")return text.replace(/-/g,"");'
        + '  return parseFloat(text)||0;'
        + '}'
        + 'function sortTable(key){'
        + '  if(key===currentSort){currentDir=currentDir==="asc"?"desc":"asc"}'
        + '  else{currentSort=key;currentDir=key==="date"?"desc":"asc"}'
        + '  var rows=Array.from(tbody.querySelectorAll("tr"));'
        + '  rows.sort(function(a,b){'
        + '    var va=getVal(a,key),vb=getVal(b,key);'
        + '    if(va<vb)return currentDir==="asc"?-1:1;'
        + '    if(va>vb)return currentDir==="asc"?1:-1;'
        + '    return 0;'
        + '  });'
        + '  rows.forEach(function(r){tbody.appendChild(r)});'
        + '  headers.forEach(function(h){'
        + '    h.classList.remove("sorted");'
        + '    var arrow=h.querySelector(".sort-arrow");'
        + '    if(arrow)arrow.textContent="";'
        + '  });'
        + '  var active=table.querySelector("th[data-sort=\\""+key+"\\"]");'
        + '  if(active){'
        + '    active.classList.add("sorted");'
        + '    active.dataset.dir=currentDir;'
        + '    var arrow=active.querySelector(".sort-arrow");'
        + '    if(arrow)arrow.textContent=currentDir==="asc"?"▲":"▼";'
        + '  }'
        + '}'
        + 'headers.forEach(function(h){'
        + '  h.addEventListener("click",function(){sortTable(this.dataset.sort)});'
        + '});'
        + 'window.filterReports=function(){'
        + '  var q=document.getElementById("report-search").value.trim().toLowerCase();'
        + '  var rows=tbody.querySelectorAll("tr");'
        + '  rows.forEach(function(r){'
        + '    var date=r.dataset.date||"";'
        + '    var dateFmt=date.slice(4,6)+"-"+date.slice(6,8);'
        + '    r.style.display=(!q||date.includes(q)||dateFmt.includes(q))?"":"none";'
        + '  });'
        + '};'
        + '})();'
        + '</script>'
    )

    return _base_page(
        "报告列表", content, active_nav="/reports",
        topbar_title="报告列表", topbar_extra=_time_filter_html()
    )


# ── Report detail page ───────────────────────────────────────────

def _build_report_detail(date: str) -> HTMLResponse:
    path = _get_report_path(date)
    if path is None:
        content = (
            f'<div class="card"><h2>报告未找到</h2>'
            f'<p class="empty">日期 {date} 的报告不存在</p>'
            f'<p style="margin-top:12px"><a href="/reports" class="btn btn-primary">返回报告列表</a></p></div>'
        )
        return HTMLResponse(
            content=_base_page("报告未找到", content, active_nav="/reports",
                               topbar_title="报告未找到"),
            status_code=404,
        )

    date_formatted = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    topbar_extra = (
        f'<span style="font-size:13px;color:var(--text-secondary)">{date_formatted}</span>'
        f'<a href="/api/reports/{date}/html" class="btn btn-ghost btn-sm">原始 HTML</a>'
        f'<a href="/reports" class="btn btn-primary btn-sm">返回列表</a>'
    )

    # Read report HTML and extract body + style for inline embedding
    try:
        raw_html = path.read_text(encoding="utf-8")
    except Exception:
        raw_html = ""

    report_body = ""
    report_style = ""
    try:
        # Extract <style>...</style> blocks
        style_matches = re.findall(r"<style[^>]*>(.*?)</style>", raw_html, re.DOTALL)
        if style_matches:
            report_style = "\n".join(style_matches)

        # Extract <body>...</body> content
        body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, re.DOTALL)
        if body_match:
            report_body = body_match.group(1)
        else:
            # Fallback: use everything between <body> and </html>
            body_match = re.search(r"<body[^>]*>(.*?)</html>", raw_html, re.DOTALL)
            if body_match:
                report_body = body_match.group(1)

        # Extract <script>...</script> blocks and wrap in IIFE
        script_matches = re.findall(r"<script[^>]*>(.*?)</script>", raw_html, re.DOTALL)
        inline_scripts = []
        for script_content in script_matches:
            # Wrap in IIFE to avoid global variable conflicts with site scripts
            # Skip the ECharts CDN loader (empty or just src)
            if script_content.strip():
                inline_scripts.append(
                    f"<script>(function(){{\n{script_content}\n}})();</script>"
                )
        # Also include the ECharts CDN <script src="...">
        cdn_matches = re.findall(r'<script[^>]*src="[^"]*echarts[^"]*"[^>]*></script>', raw_html)
        cdn_script = cdn_matches[0] if cdn_matches else ""
    except Exception:
        report_body = ""
        report_style = ""
        inline_scripts = []
        cdn_script = ""

    if not report_body:
        # Fallback: iframe
        content = (
            f'<div class="breadcrumb" style="margin-bottom:16px">'
            f'<a href="/reports">← 返回列表</a>'
            f'<span class="sep">|</span>'
            f'<span>{date_formatted} 审计报告</span>'
            f'<a href="/api/reports/{date}/html" style="margin-left:auto" class="btn btn-ghost btn-sm">原始 HTML</a>'
            f'</div>'
            f'<div class="result-box info" style="margin-bottom:12px">'
            f'报告解析失败，使用 iframe 回退显示</div>'
            f'<div class="iframe-wrap">'
            f'<iframe src="/api/reports/{date}/html" '
            f'sandbox="allow-scripts allow-same-origin"></iframe>'
            f'</div>'
        )
    else:
        # Scoped report CSS: prefix all selectors with .report-frame to avoid leaking
        # into the site's dark theme
        scoped_style = (
            f'<style>\n'
            f'.report-frame {{\n'
            f'  background:#fff;color:#2d3436;font-family:-apple-system,BlinkMacSystemFont,'
            f'"Segoe UI",Helvetica,Arial,sans-serif;line-height:1.6;\n'
            f'  border-radius:8px;border:1px solid var(--border);'
            f'  box-shadow:0 4px 20px rgba(0,0,0,0.3);\n'
            f'  padding:20px;overflow-x:auto;\n'
            f'}}\n'
            f'.report-frame .container{{max-width:100%;margin:0}}\n'
            f'.report-frame body{{background:#fff;color:#2d3436}}\n'
            f'{report_style}\n'
            f'</style>'
        )

        content = (
            f'<div class="breadcrumb" style="margin-bottom:16px">'
            f'<a href="/reports">← 返回列表</a>'
            f'<span class="sep">|</span>'
            f'<span>{date_formatted} 审计报告</span>'
            f'<a href="/api/reports/{date}/html" style="margin-left:auto" class="btn btn-ghost btn-sm">原始 HTML</a>'
            f'</div>'
            f'<div class="report-frame">\n'
            f'{report_body}\n'
            f'</div>'
            f'{cdn_script}\n'
            + "\n".join(inline_scripts)
        )

    return HTMLResponse(
        content=_base_page(
            f"{date_formatted} 审计报告", content,
            active_nav="/reports", full_width=True,
            topbar_title=f"{date_formatted} 审计报告",
            topbar_extra=topbar_extra,
            extra_head=scoped_style if report_body else "",
        )
    )


# ── Audit page ───────────────────────────────────────────────────

def _build_audit_page() -> str:
    # Recent tasks from memory
    task_rows = []
    for t in reversed(_AUDIT_TASKS[-10:]):
        status_badge = {
            "running": '<span class="badge badge-info">运行中</span>',
            "ok": '<span class="badge badge-ok">成功</span>',
            "error": '<span class="badge badge-err">失败</span>',
        }.get(t.get("status", ""), '<span class="badge badge-warn">未知</span>')
        report_link = f'<a href="{t["report_url"]}" class="report-link">查看报告</a>' if t.get("report_url") else "—"
        task_rows.append(
            f'<li>'
            f'<span class="task-time">{t.get("time", "")}</span>'
            f'<span style="flex:1">{t.get("input", "")}</span>'
            f'{status_badge}'
            f'<span>{report_link}</span>'
            f'</li>'
        )

    task_list_html = (
        f'<div class="card"><h2>最近审计任务</h2>'
        + (f'<ul class="task-list">{"".join(task_rows)}</ul>' if task_rows else '<p class="empty">暂无任务记录</p>')
        + '</div>'
    )

    form_html = (
        f'<div class="card"><h2>🔍 触发审计</h2>'
        f'<form id="audit-form" onsubmit="return triggerAudit(event)">'
        f'<div class="form-group">'
        f'<label for="input-path">事件流文件路径</label>'
        f'<input type="text" id="input-path" name="input" '
        f'placeholder="例如: /path/to/events.jsonl" required>'
        f'</div>'
        f'<div class="form-group">'
        f'<label for="output-path">输出路径（可选，默认写入报告目录）</label>'
        f'<input type="text" id="output-path" name="output" '
        f'placeholder="留空则自动生成到 {REPORT_DIR}">'
        f'</div>'
        f'<button type="submit" class="btn btn-primary" id="audit-btn">触发审计</button>'
        f'</form>'
        f'<div id="audit-result"></div>'
        f'</div>'
        f'<script>'
        f'async function triggerAudit(e){{'
        f'  e.preventDefault();'
        f'  var btn=document.getElementById("audit-btn");'
        f'  var result=document.getElementById("audit-result");'
        f'  var inputVal=document.getElementById("input-path").value.trim();'
        f'  var outputVal=document.getElementById("output-path").value.trim();'
        f'  if(!inputVal)return;'
        f'  btn.disabled=true;btn.textContent="审计执行中…";'
        f'  result.innerHTML="";'
        f'  try{{'
        f'    var body={{input:inputVal}};'
        f'    if(outputVal)body.output=outputVal;'
        f'    var resp=await fetch("/api/audit/run",{{'
        f'      method:"POST",'
        f'      headers:{{"Content-Type":"application/json"}},'
        f'      body:JSON.stringify(body)'
        f'    }});'
        f'    var data=await resp.json();'
        f'    if(data.status==="ok"){{'
        f'      result.innerHTML=\'<div class="result-box success">审计成功！'
        f'      <a href="\'+data.report_url+\'">查看报告</a></div>\';'
        f'      // Poll audit status to refresh task list'
        f'      setTimeout(function(){{window.location.reload()}},2000);'
        f'    }}else{{'
        f'      result.innerHTML=\'<div class="result-box error">审计失败: \'+data.detail+\'</div>\';'
        f'    }}'
        f'  }}catch(err){{'
        f'    result.innerHTML=\'<div class="result-box error">请求失败: \'+err.message+\'</div>\';'
        f'  }}finally{{'
        f'    btn.disabled=false;btn.textContent="触发审计";'
        f'  }}'
        f'}}'
        f'</script>'
    )

    content = form_html + task_list_html
    return _base_page(
        "触发审计", content, active_nav="/audit",
        topbar_title="触发审计",
    )


# ─────────────────────────────────────────────────────────────────
# API: Reports
# ─────────────────────────────────────────────────────────────────

@app.get("/api/reports")
async def api_reports():
    """List all audit reports in the report directory."""
    return _list_report_files()


@app.get("/api/reports/trends")
async def api_reports_trends():
    """Return trend data for all reports: dates, costs, waste, findings, etc."""
    reports = _list_report_files()
    if not reports:
        return {
            "dates": [],
            "total_cost": [],
            "est_waste": [],
            "findings": [],
            "high": [],
            "events": [],
        }

    # Sort chronologically
    reports_sorted = sorted(reports, key=lambda r: r["date"])

    return {
        "dates": [r["date"] for r in reports_sorted],
        "total_cost": [round(r["total_cost"], 2) for r in reports_sorted],
        "est_waste": [round(r["est_waste"], 2) for r in reports_sorted],
        "findings": [r["findings_total"] for r in reports_sorted],
        "high": [r["high"] for r in reports_sorted],
        "events": [r["events"] for r in reports_sorted],
    }


@app.get("/api/reports/{date}")
async def api_report_detail(date: str):
    """Get report metadata and summary for a specific date."""
    path = _get_report_path(date)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Report not found for date: {date}")

    try:
        html = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {e}")

    meta = _parse_html_report(html)
    stat = path.stat()

    return {
        "date": date,
        "filename": path.name,
        "size_bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "events": meta["events"],
        "high": meta["high"],
        "medium": meta["medium"],
        "low": meta["low"],
        "info": meta["info"],
        "findings_total": meta["findings_total"],
        "total_cost": meta["total_cost"],
        "est_waste": meta["est_waste"],
        "total_tokens_in": meta["total_tokens_in"],
        "avoidable_cost_ratio": meta["avoidable_cost_ratio"],
    }


@app.get("/api/reports/{date}/html", response_class=HTMLResponse)
async def api_report_html(date: str):
    """Return the raw HTML report for a specific date."""
    path = _get_report_path(date)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Report not found for date: {date}")

    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {e}")


# ─────────────────────────────────────────────────────────────────
# API: Audit
# ─────────────────────────────────────────────────────────────────

@app.post("/api/audit/run")
async def api_audit_run(request: Request):
    """Trigger an audit run. Body: {"input": "/path/to/events.jsonl", "output": "/optional/output.html"}."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    input_path = body.get("input")
    if not input_path:
        raise HTTPException(status_code=400, detail="Missing required field: input")
    if not os.path.isfile(input_path):
        raise HTTPException(status_code=400, detail=f"Input file not found: {input_path}")

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_path = body.get("output")
    if not output_path:
        output_path = str(REPORT_DIR / f"audit-{today}.html")

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    task_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    global _TASK_ID_COUNTER
    _TASK_ID_COUNTER += 1
    task_entry = {
        "id": _TASK_ID_COUNTER,
        "time": task_time,
        "input": input_path,
        "status": "running",
        "report_url": None,
    }
    _AUDIT_TASKS.append(task_entry)
    # Keep only 50 most recent
    if len(_AUDIT_TASKS) > 50:
        _AUDIT_TASKS[:] = _AUDIT_TASKS[-50:]
    _save_tasks()

    # Run audit via subprocess
    cmd = [
        sys.executable, "-m", "agentlens_cli", "audit",
        "--input", input_path,
        "--format", "html",
        "--output", output_path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        if proc.returncode != 0:
            task_entry["status"] = "error"
            _save_tasks()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "detail": proc.stderr.strip() or proc.stdout.strip()},
            )
    except subprocess.TimeoutExpired:
        task_entry["status"] = "error"
        _save_tasks()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Audit timed out after 300 seconds"},
        )
    except Exception as e:
        task_entry["status"] = "error"
        _save_tasks()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )

    report_url = f"/reports/{today}"
    task_entry["status"] = "ok"
    task_entry["report_url"] = report_url
    _save_tasks()

    return {
        "status": "ok",
        "report_url": report_url,
        "date": today,
    }


@app.get("/api/audit/status")
async def api_audit_status():
    """Return audit status: last audit info, report dir, baseline status."""
    reports = _list_report_files()
    last_audit = None
    if reports:
        latest = reports[0]
        last_audit = {
            "date": latest["date"],
            "status": "completed",
        }

    baseline_path = REPORT_DIR / "baseline.json"
    baseline = {"exists": baseline_path.is_file()}
    if baseline["exists"]:
        baseline["mtime"] = datetime.fromtimestamp(
            baseline_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    return {
        "last_audit": last_audit,
        "report_dir": str(REPORT_DIR),
        "baseline": baseline,
    }


# ─────────────────────────────────────────────────────────────────
# API: Watchdog
# ─────────────────────────────────────────────────────────────────

@app.get("/api/watchdog")
async def api_watchdog():
    """Return watchdog baseline status."""
    baseline_path = REPORT_DIR / "baseline.json"
    if not baseline_path.is_file():
        return {"baseline_exists": False}

    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"baseline_exists": False}

    if not isinstance(baseline, dict):
        return {"baseline_exists": False}

    return {
        "baseline_exists": True,
        "baseline_mtime": datetime.fromtimestamp(
            baseline_path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "event_count": baseline.get("events_loaded", 0),
    }


# ─────────────────────────────────────────────────────────────────
# Pages: HTML UI
# ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def page_dashboard():
    """Dashboard page: KPI cards, charts, recent reports, watchdog, audit dynamics."""
    return _build_dashboard()


@app.get("/reports", response_class=HTMLResponse)
async def page_reports():
    """Full report list page with sortable table and search."""
    return _build_reports_list()


@app.get("/audit", response_class=HTMLResponse)
async def page_audit():
    """Audit trigger page with form and recent tasks."""
    return _build_audit_page()


@app.get("/reports/{date}", response_class=HTMLResponse)
async def page_report_detail(date: str):
    """Report detail page with iframe-embedded HTML (full-width layout)."""
    return _build_report_detail(date)
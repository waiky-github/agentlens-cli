"""FastAPI Web 服务：REST API + 浏览器操作界面（Langfuse 式观测平台）。

提供审计报告浏览、审计触发、watchdog 漂移状态查看、趋势数据等功能。
"""

import base64
import csv
import io
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.parse
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

from agentlens_cli.notify import (
    get_notify_config,
    save_notify_config,
    send_notify,
)
from .budget import check_budget, format_budget_alert_body

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
# P2-1: Fixed-findings tracking
# ─────────────────────────────────────────────────────────────────

_FIXED_FILE = REPORT_DIR / "fixed-findings.json"

# 任务3（2026-09-10）：修复回归验证——连续缺席 N 次审计才确认修复（verified）
VERIFY_STREAK_REQUIRED = 3


def _load_fixed_findings() -> list[dict]:
    """Load persisted fixed-findings tracking data."""
    if not _FIXED_FILE.is_file():
        return []
    try:
        data = json.loads(_FIXED_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_fixed_findings(data: list[dict]):
    """Persist fixed-findings tracking data atomically."""
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _FIXED_FILE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, _FIXED_FILE)
    except OSError:
        pass


def _finding_key(layer: str, title: str) -> str:
    """Build a URL-safe key from (layer, title)."""
    raw = f"{layer}|{title}"
    return urllib.parse.quote(raw, safe="")


def _decode_finding_key(key: str) -> tuple[str, str]:
    """Decode a URL-safe key back to (layer, title)."""
    raw = urllib.parse.unquote(key)
    parts = raw.split("|", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return raw, ""


# ─────────────────────────────────────────────────────────────────
# P2-2: Multi-project / multi-environment support
# ─────────────────────────────────────────────────────────────────

def _get_project_dir(project: str) -> Path:
    """Get the subdirectory for a given project within REPORT_DIR."""
    project = (project or "default").strip()
    if project == "default":
        return REPORT_DIR
    return REPORT_DIR / project


def _get_report_path(date_str: str, project: str = "default") -> Optional[Path]:
    """Get the report file path for a given date and project.

    Checks project subdirectory first, then falls back to root dir
    for backward compatibility.
    """
    proj_dir = _get_project_dir(project)
    if project != "default":
        f = proj_dir / f"audit-{date_str}.html"
        if f.is_file():
            return f
    # Fallback: root dir
    f = REPORT_DIR / f"audit-{date_str}.html"
    if f.is_file():
        return f
    # Also check project dir for default
    if project == "default":
        f = proj_dir / f"audit-{date_str}.html"
        if f.is_file():
            return f
    return None


def _list_report_files(project: str = "default") -> list[dict]:
    """List all audit-*.html files for a given project.

    For default project: also scans the root dir (backward compat).
    For non-default projects: only scans the project subdirectory.
    """
    reports = []
    if not REPORT_DIR.is_dir():
        return reports

    proj_dir = _get_project_dir(project)
    seen_dates: set[str] = set()

    # Scan project subdirectory
    if proj_dir.is_dir():
        for f in sorted(proj_dir.glob("audit-*.html"), reverse=True):
            m = re.match(r"audit-(\d{8})\.html", f.name)
            if not m:
                continue
            date_str = m.group(1)
            if date_str in seen_dates:
                continue
            seen_dates.add(date_str)
            entry = _build_report_entry(f, date_str, project)
            if entry:
                reports.append(entry)

    # For default project, also scan root dir (backward compat)
    if project == "default" and proj_dir != REPORT_DIR:
        for f in sorted(REPORT_DIR.glob("audit-*.html"), reverse=True):
            m = re.match(r"audit-(\d{8})\.html", f.name)
            if not m:
                continue
            date_str = m.group(1)
            if date_str in seen_dates:
                continue
            seen_dates.add(date_str)
            entry = _build_report_entry(f, date_str, project)
            if entry:
                reports.append(entry)

    return reports


def _build_report_entry(f: Path, date_str: str, project: str) -> dict | None:
    """Build a report metadata dict for a single file."""
    stat = f.stat()
    size = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    try:
        html = f.read_text(encoding="utf-8")
    except Exception:
        html = ""
    meta = _parse_html_report(html)

    return {
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
        "project": project,
    }


def _list_projects() -> list[str]:
    """List all project names (subdirectories with audit-*.html files)."""
    projects: set[str] = set()
    if not REPORT_DIR.is_dir():
        return []

    # Root dir has reports → "default"
    root_reports = list(REPORT_DIR.glob("audit-*.html"))
    if root_reports:
        projects.add("default")

    # Subdirectories with reports
    for subdir in sorted(REPORT_DIR.iterdir()):
        if subdir.is_dir() and not subdir.name.startswith("."):
            sub_reports = list(subdir.glob("audit-*.html"))
            if sub_reports:
                projects.add(subdir.name)

    return sorted(projects)


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


def _extract_embedded_findings(html_content: str) -> list[dict]:
    """Extract the full findings list embedded as JSON in the report.

    The report embeds `<script id="findings-data" type="application/json">`
    with the complete findings from all layers. Returns [] if absent.
    """
    m = re.search(
        r'<script id="findings-data" type="application/json">(.*?)</script>',
        html_content,
        re.DOTALL,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return data


def _parse_html_findings(html_content: str) -> list[dict]:
    """Parse individual findings from an audit HTML report.

    Returns a list of dicts, each with keys: layer, severity, title,
    est_wasted_cost, detail, recommendation, regulation_refs, remediation,
    count (N>1 for aggregated findings).

    The finding unique key is (layer, title).
    """
    findings: list[dict] = []
    layer_names = {
        "layer-graph": "协作图谱",
        "layer-decision": "决策审计",
        "layer-evidence": "证据链",
        "layer-cost": "成本治理",
        "layer-shadow": "影子智能体",
        "layer-compliance": "决策权限合规",
    }

    # Split into layer sections
    sections = re.split(r'<div class="section" id="(layer-\w+)"', html_content)
    for i in range(1, len(sections), 2):
        layer_id = sections[i]
        layer_name = layer_names.get(layer_id, layer_id)
        section_html = sections[i + 1] if i + 1 < len(sections) else ""

        # Find all finding blocks (both .finding and .finding-group)
        # .finding-group blocks (aggregated with <details>)
        for m in re.finditer(
            r'<details class="finding-group"[^>]*data-severity="(\w+)"[^>]*>'
            r'(.*?)</details>',
            section_html,
            re.DOTALL,
        ):
            block = m.group(2)
            finding = _extract_single_finding(block, m.group(1), layer_name)
            if finding:
                # Check for aggregation count
                count_m = re.search(r'<span class="finding-count">x(\d+)\s*条</span>', block)
                if count_m:
                    finding["count"] = int(count_m.group(1))
                findings.append(finding)

        # .finding blocks (single findings)
        # The severity is inside the block, not as a data attribute.
        # Use a depth-based approach to handle nested divs inside findings.
        pos = 0
        while True:
            start_m = re.search(r'<div class="finding"[^>]*>', section_html[pos:])
            if not start_m:
                break
            block_start = pos + start_m.end()
            # Find matching </div> by counting depth
            depth = 1
            i = block_start
            while i < len(section_html) and depth > 0:
                next_open = section_html.find("<div", i)
                next_close = section_html.find("</div>", i)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1
                    i = next_open + 4
                else:
                    depth -= 1
                    if depth == 0:
                        block_end = next_close
                        break
                    i = next_close + 6
            else:
                # No matching close found
                pos = block_start
                continue

            block = section_html[block_start:block_end]
            # Extract severity from span
            sev_m = re.search(r'<span class="finding-sev"[^>]*>(\w+)</span>', block)
            sev = sev_m.group(1).lower() if sev_m else "info"
            finding = _extract_single_finding(block, sev, layer_name)
            if finding:
                finding["count"] = 1
                findings.append(finding)
            pos = block_end + 6

    return findings


def _extract_single_finding(block: str, severity: str, layer: str) -> dict | None:
    """Extract fields from a single finding block HTML."""
    # Title from <strong>...</strong>
    title_m = re.search(r"<strong>(.+?)</strong>", block)
    if not title_m:
        return None
    title = html_decode(title_m.group(1))

    finding: dict = {
        "layer": layer,
        "severity": severity,
        "title": title,
        "est_wasted_cost": None,
        "detail": "",
        "recommendation": "",
        "regulation_refs": [],
        "remediation": [],
        "count": 1,
    }

    # Est wasted cost
    waste_m = re.search(r"预估浪费[：:]\s*([\d.]+)\s*CNY", block)
    if waste_m:
        finding["est_wasted_cost"] = float(waste_m.group(1))

    # Detail
    detail_m = re.search(r'<p class="finding-detail">(.+?)</p>', block, re.DOTALL)
    if detail_m:
        finding["detail"] = html_decode(strip_tags(detail_m.group(1)))

    # Recommendation
    rec_m = re.search(r'<p class="finding-rec">建议[：:]\s*(.+?)</p>', block, re.DOTALL)
    if rec_m:
        finding["recommendation"] = html_decode(strip_tags(rec_m.group(1)))

    # Regulation refs
    regs_block = re.search(
        r'<div class="finding-regs">(.*?)</div>', block, re.DOTALL
    )
    if regs_block:
        for li in re.finditer(r"<li>(.+?)</li>", regs_block.group(1), re.DOTALL):
            finding["regulation_refs"].append(html_decode(strip_tags(li.group(1))))

    # Remediation
    rems_block = re.search(
        r'<div class="finding-rems">(.*?)</div>', block, re.DOTALL
    )
    if rems_block:
        for li in re.finditer(r"<li>(.+?)</li>", rems_block.group(1), re.DOTALL):
            finding["remediation"].append(html_decode(strip_tags(li.group(1))))

    return finding


def html_decode(text: str) -> str:
    """Decode HTML entities."""
    import html as _html
    return _html.unescape(text)


def strip_tags(text: str) -> str:
    """Remove HTML tags from text."""
    return re.sub(r"<[^>]+>", "", text).strip()


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
        ("/fix-track", "🔧", "修复跟踪"),
        ("/notify", "🔔", "通知配置"),
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
        f'<div class="ver">v0.3.0</div>'
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

def _build_reports_list(project: str = "default") -> str:
    reports = _list_report_files(project)
    projects = _list_projects()

    # Project selector
    project_options = []
    for p in projects:
        sel = 'selected' if p == project else ''
        project_options.append(f'<option value="{p}" {sel}>{p}</option>')

    project_selector = (
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">'
        f'<span style="font-size:13px;color:var(--text-secondary)">项目:</span>'
        f'<select id="project-selector" onchange="switchProject(this.value)" '
        f'style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;'
        f'background:var(--bg-primary);color:var(--text-primary);font-size:13px">'
        + "".join(project_options)
        + f'</select>'
        f'</div>'
        f'<script>'
        f'function switchProject(p){{window.location.href="/reports?project="+encodeURIComponent(p)}}'
        f'</script>'
    ) if len(projects) > 1 else ""

    if not reports:
        content = project_selector + '<div class="empty-big"><div class="empty-icon">📄</div><div class="empty-text">暂无报告</div></div>'
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
            f'<a href="/api/reports/{r["date"]}/findings.csv" class="btn btn-ghost btn-sm">导出 CSV</a> '
            f'<a href="/api/reports/{r["date"]}/html" class="btn btn-ghost btn-sm">原始 HTML</a>'
            f'</td></tr>'
        )

    content = (
        project_selector
        + f'<div class="card" style="margin-bottom:16px"><h2>对比报告</h2>'
        f'<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">'
        f'<select id="compare-base" style="padding:8px 12px;border:1px solid var(--border);'
        f'border-radius:6px;background:var(--bg-primary);color:var(--text-primary);font-size:13px">'
        f'<option value="">选择基线报告…</option>'
        + "".join(
            f'<option value="{r["date"]}">{r["date"][:4]}-{r["date"][4:6]}-{r["date"][6:8]}</option>'
            for r in reports
        )
        + f'</select>'
        f'<span style="color:var(--text-secondary)">vs</span>'
        f'<select id="compare-curr" style="padding:8px 12px;border:1px solid var(--border);'
        f'border-radius:6px;background:var(--bg-primary);color:var(--text-primary);font-size:13px">'
        f'<option value="">选择当前报告…</option>'
        + "".join(
            f'<option value="{r["date"]}">{r["date"][:4]}-{r["date"][4:6]}-{r["date"][6:8]}</option>'
            for r in reports
        )
        + f'</select>'
        f'<button onclick="doCompare()" class="btn btn-primary btn-sm">对比</button>'
        f'</div>'
        f'<script>'
        f'function doCompare(){{'
        f'var b=document.getElementById("compare-base").value;'
        f'var c=document.getElementById("compare-curr").value;'
        f'if(b&&c)window.location.href="/reports/compare?base="+b+"&curr="+c;'
        f'else alert("请选择两份报告日期");'
        f'}}'
        f'</script>'
        f'</div>'
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
        f'<a href="/api/reports/{date}/findings.csv" class="btn btn-ghost btn-sm">导出 CSV</a>'
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


# ── Report compare page ──────────────────────────────────────────

def _build_report_compare(base: str, curr: str) -> HTMLResponse:
    """Build a findings comparison page between two reports."""
    base_path = _get_report_path(base)
    curr_path = _get_report_path(curr)

    if base_path is None:
        return HTMLResponse(
            content=_base_page("报告未找到", f'<div class="card"><h2>报告未找到</h2>'
                               f'<p class="empty">基线日期 {base} 的报告不存在</p>'
                               f'<p style="margin-top:12px"><a href="/reports" class="btn btn-primary">返回报告列表</a></p></div>',
                               active_nav="/reports", topbar_title="报告未找到"),
            status_code=404,
        )
    if curr_path is None:
        return HTMLResponse(
            content=_base_page("报告未找到", f'<div class="card"><h2>报告未找到</h2>'
                               f'<p class="empty">当前日期 {curr} 的报告不存在</p>'
                               f'<p style="margin-top:12px"><a href="/reports" class="btn btn-primary">返回报告列表</a></p></div>',
                               active_nav="/reports", topbar_title="报告未找到"),
            status_code=404,
        )

    base_html = base_path.read_text(encoding="utf-8")
    curr_html = curr_path.read_text(encoding="utf-8")

    base_findings = _extract_embedded_findings(base_html)
    if not base_findings:
        base_findings = _parse_html_findings(base_html)
    curr_findings = _extract_embedded_findings(curr_html)
    if not curr_findings:
        curr_findings = _parse_html_findings(curr_html)

    # Build unique key sets
    base_keys: dict[tuple, dict] = {}
    for f in base_findings:
        key = (f["layer"], f["title"])
        if key not in base_keys:
            base_keys[key] = f
        else:
            base_keys[key]["count"] = base_keys[key].get("count", 1) + 1

    curr_keys: dict[tuple, dict] = {}
    for f in curr_findings:
        key = (f["layer"], f["title"])
        if key not in curr_keys:
            curr_keys[key] = f
        else:
            curr_keys[key]["count"] = curr_keys[key].get("count", 1) + 1

    base_set = set(base_keys.keys())
    curr_set = set(curr_keys.keys())

    only_base = base_set - curr_set  # fixed
    only_curr = curr_set - base_set  # new
    common = base_set & curr_set     # persistent

    base_fmt = f"{base[:4]}-{base[4:6]}-{base[6:8]}"
    curr_fmt = f"{curr[:4]}-{curr[4:6]}-{curr[6:8]}"

    # Summary cards
    base_total = len(base_keys)
    curr_total = len(curr_keys)
    new_count = len(only_curr)
    fixed_count = len(only_base)
    persistent_count = len(common)

    base_waste = sum((f.get("est_wasted_cost") or 0) for f in base_keys.values())
    curr_waste = sum((f.get("est_wasted_cost") or 0) for f in curr_keys.values())
    waste_delta = curr_waste - base_waste

    def _sev_badge(sev: str) -> str:
        colors = {"high": "badge-err", "medium": "badge-warn", "low": "badge-info", "info": "badge-info"}
        return f'<span class="badge {colors.get(sev, "badge-info")}">{sev.upper()}</span>'

    def _layer_badge(layer: str) -> str:
        colors = {
            "协作图谱": "badge-info", "决策审计": "badge-warn", "证据链": "badge-ok",
            "成本治理": "badge-err", "影子智能体": "badge-err", "决策权限合规": "badge-warn",
        }
        return f'<span class="badge {colors.get(layer, "badge-info")}">{layer}</span>'

    def _waste_str(waste_val) -> str:
        if waste_val is None:
            return "-"
        return f"{waste_val:.2f}"

    def _render_table_rows(keys, findings_map, tag: str, tag_class: str):
        rows = []
        for key in sorted(keys, key=lambda k: (findings_map[k].get("est_wasted_cost") or 0), reverse=True):
            f = findings_map[key]
            waste = f.get("est_wasted_cost")

            if tag == "persistent":
                # Show both baseline and current waste with delta
                base_f = base_keys.get(key)
                base_w = base_f.get("est_wasted_cost") if base_f else None
                curr_w = waste
                if base_w is not None and curr_w is not None:
                    delta = curr_w - base_w
                    if delta > 0.005:
                        arrow = " ↑"
                    elif delta < -0.005:
                        arrow = " ↓"
                    else:
                        arrow = ""
                    waste_cell = f'{_waste_str(base_w)} → {_waste_str(curr_w)}{arrow}'
                else:
                    waste_cell = f'{_waste_str(base_w)} → {_waste_str(curr_w)}'
            else:
                waste_cell = _waste_str(waste)

            count_str = f' x{f["count"]}' if f.get("count", 1) > 1 else ""

            rows.append(
                f'<tr>'
                f'<td><span class="badge {tag_class} tag-label">{tag}</span> '
                f'{_layer_badge(f["layer"])}</td>'
                f'<td>{f["title"][:80]}{"…" if len(f["title"]) > 80 else ""}{count_str}</td>'
                f'<td>{_sev_badge(f["severity"])}</td>'
                f'<td class="num">{waste_cell}</td>'
                f'</tr>'
            )
        return "".join(rows) if rows else '<tr><td colspan="4" class="empty">无</td></tr>'

    # All rows combined for "all" tab
    all_rows = []
    all_rows.append(_render_table_rows(only_curr, curr_keys, "新增", "badge-err"))
    all_rows.append(_render_table_rows(only_base, base_keys, "已修复", "badge-ok"))
    all_rows.append(_render_table_rows(common, curr_keys, "持续", "badge-warn"))

    # Tab content
    new_rows = _render_table_rows(only_curr, curr_keys, "新增", "badge-err")
    fixed_rows = _render_table_rows(only_base, base_keys, "已修复", "badge-ok")
    persistent_rows = _render_table_rows(common, curr_keys, "持续", "badge-warn")

    waste_delta_str = f"{waste_delta:+.2f}" if waste_delta else "0.00"
    waste_delta_color = "var(--danger)" if waste_delta > 0 else ("var(--success)" if waste_delta < 0 else "var(--text-secondary)")

    summary_cards = (
        f'<div class="kpi-grid" style="grid-template-columns:repeat(6,1fr)">'
        f'<div class="kpi-card"><div class="kpi-accent blue"></div>'
        f'<div class="kpi-label">基线发现数</div><div class="kpi-value">{base_total}</div>'
        f'<div class="kpi-sub">{base_fmt}</div></div>'
        f'<div class="kpi-card"><div class="kpi-accent blue"></div>'
        f'<div class="kpi-label">当前发现数</div><div class="kpi-value">{curr_total}</div>'
        f'<div class="kpi-sub">{curr_fmt}</div></div>'
        f'<div class="kpi-card"><div class="kpi-accent red"></div>'
        f'<div class="kpi-label">新增</div><div class="kpi-value">{new_count}</div></div>'
        f'<div class="kpi-card"><div class="kpi-accent green"></div>'
        f'<div class="kpi-label">已修复</div><div class="kpi-value">{fixed_count}</div></div>'
        f'<div class="kpi-card"><div class="kpi-accent orange"></div>'
        f'<div class="kpi-label">持续存在</div><div class="kpi-value">{persistent_count}</div></div>'
        f'<div class="kpi-card"><div class="kpi-accent purple"></div>'
        f'<div class="kpi-label">预估浪费变化</div>'
        f'<div class="kpi-value" style="color:{waste_delta_color}">{waste_delta_str}</div>'
        f'<div class="kpi-sub">CNY</div></div>'
        f'</div>'
    )

    table_html = (
        f'<div class="card"><h2>发现对比</h2>'
        f'<div class="tab-bar" style="display:flex;gap:4px;margin-bottom:16px">'
        f'<button class="tab-btn active" data-tab="all">全部 ({base_total + curr_total - persistent_count})</button>'
        f'<button class="tab-btn" data-tab="new">新增 ({new_count})</button>'
        f'<button class="tab-btn" data-tab="fixed">已修复 ({fixed_count})</button>'
        f'<button class="tab-btn" data-tab="persistent">持续存在 ({persistent_count})</button>'
        f'</div>'
        f'<table id="compare-table"><thead><tr>'
        f'<th>分类</th><th>标题</th><th>严重度</th><th>预估浪费 CNY</th>'
        f'</tr></thead>'
        f'<tbody id="tab-all">{"".join(all_rows)}</tbody>'
        f'<tbody id="tab-new" style="display:none">{new_rows}</tbody>'
        f'<tbody id="tab-fixed" style="display:none">{fixed_rows}</tbody>'
        f'<tbody id="tab-persistent" style="display:none">{persistent_rows}</tbody>'
        f'</table></div>'
    )

    empty_state = (
        f'<div class="empty-big"><div class="empty-icon">📋</div>'
        f'<div class="empty-text">两份报告均无发现</div></div>'
    )

    content = (
        f'<div class="breadcrumb" style="margin-bottom:16px">'
        f'<a href="/reports">← 返回列表</a>'
        f'<span class="sep">|</span>'
        f'<span>报告对比</span>'
        f'<span class="sep">|</span>'
        f'<span>{base_fmt} vs {curr_fmt}</span>'
        f'</div>'
        + (summary_cards + table_html if base_total > 0 or curr_total > 0 else empty_state)
        + (
            '<style>'
            '.tab-bar .tab-btn{padding:6px 16px;border-radius:6px;font-size:13px;'
            'border:1px solid var(--border);background:transparent;color:var(--text-secondary);'
            'cursor:pointer;transition:all 0.15s}'
            '.tab-bar .tab-btn:hover{background:var(--bg-panel);color:var(--text-primary)}'
            '.tab-bar .tab-btn.active{background:var(--brand);color:#fff;border-color:var(--brand)}'
            '.tag-label{font-size:10px;margin-right:4px}'
            '</style>'
            '<script>'
            '(function(){'
            'var btns=document.querySelectorAll(".tab-btn");'
            'btns.forEach(function(b){'
            '  b.addEventListener("click",function(){'
            '    btns.forEach(function(x){x.classList.remove("active")});'
            '    this.classList.add("active");'
            '    var tab=this.dataset.tab;'
            '    document.querySelectorAll("#compare-table tbody").forEach(function(t){'
            '      t.style.display="none";'
            '    });'
            '    var target=document.getElementById("tab-"+tab);'
            '    if(target)target.style.display="";'
            '  });'
            '});'
            '})();'
            '</script>'
        )
    )

    return HTMLResponse(
        content=_base_page(
            "报告对比", content, active_nav="/reports", full_width=True,
            topbar_title="报告对比",
            topbar_extra=f'<span style="font-size:13px;color:var(--text-secondary)">{base_fmt} vs {curr_fmt}</span>'
            f'<a href="/reports" class="btn btn-ghost btn-sm">返回列表</a>',
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
async def api_reports(project: str = "default"):
    """List all audit reports in the report directory."""
    return _list_report_files(project)


@app.get("/api/reports/trends")
async def api_reports_trends(project: str = "default"):
    """Return trend data for all reports: dates, costs, waste, findings, etc."""
    reports = _list_report_files(project)
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


@app.get("/api/reports/{date}/findings.csv")
async def api_report_findings_csv(date: str):
    """Export report findings as CSV (UTF-8-sig, Excel-compatible)."""
    path = _get_report_path(date)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Report not found for date: {date}")

    try:
        html = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {e}")

    findings = _extract_embedded_findings(html)
    if not findings:
        findings = _parse_html_findings(html)

    # Aggregate by (layer, title) same as P0-1
    groups: dict[tuple, dict] = {}
    for f in findings:
        key = (f["layer"], f["title"])
        if key not in groups:
            groups[key] = dict(f)
            groups[key]["count"] = f.get("count", 1)
        else:
            groups[key]["count"] = groups[key].get("count", 1) + f.get("count", 1)
            # Keep the higher est_wasted_cost
            if (f.get("est_wasted_cost") or 0) > (groups[key].get("est_wasted_cost") or 0):
                groups[key]["est_wasted_cost"] = f.get("est_wasted_cost")

    date_fmt = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    # Header
    writer.writerow([
        "日期", "层名", "严重度", "标题", "预估浪费 CNY",
        "出现次数", "建议", "法规依据", "修复建议",
    ])

    for (layer, title), f in sorted(groups.items(), key=lambda x: (x[1].get("est_wasted_cost") or 0), reverse=True):
        writer.writerow([
            date_fmt,
            layer,
            f.get("severity", "-"),
            title,
            f"{f['est_wasted_cost']:.6f}" if f.get("est_wasted_cost") is not None else "-",
            str(f.get("count", 1)),
            f.get("recommendation", "-") or "-",
            _join_field(f.get("regulation_refs")),
            _join_field(f.get("remediation")),
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    filename = f"agentlens-findings-{date}.csv"

    from fastapi.responses import Response
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _join_field(items) -> str:
    """Join a list of string/dict items into a single '; '-separated string.

    Findings from the embedded JSON may carry dict entries (e.g. regulation
    refs with {'ref': ...}), while the HTML-parsed path gives plain strings.
    Normalize both before joining.
    """
    if not items:
        return "-"
    parts = []
    for it in items:
        if isinstance(it, dict):
            # Prefer common readable keys
            parts.append(str(it.get("ref") or it.get("text") or it.get("title") or it.get("name") or it))
        else:
            parts.append(str(it))
    return "; ".join(p for p in parts if p) or "-"


# ─────────────────────────────────────────────────────────────────
# API: Audit
# ─────────────────────────────────────────────────────────────────

@app.post("/api/audit/run")
async def api_audit_run(request: Request):
    """Trigger an audit run. Body: {"input": "...", "output": "...", "project": "..."}."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    input_path = body.get("input")
    if not input_path:
        raise HTTPException(status_code=400, detail="Missing required field: input")
    if not os.path.isfile(input_path):
        raise HTTPException(status_code=400, detail=f"Input file not found: {input_path}")

    project = body.get("project", "default")
    project = (project or "default").strip()

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_path = body.get("output")
    if not output_path:
        proj_dir = _get_project_dir(project)
        proj_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(proj_dir / f"audit-{today}.html")

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
        "project": project,
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
    if project != "default":
        report_url = f"/reports/{today}?project={urllib.parse.quote(project)}"
    task_entry["status"] = "ok"
    task_entry["report_url"] = report_url

    # P2-1: Auto-recheck marked_fixed findings against new report
    try:
        recheck_result = _recheck_fixed_findings(output_path)
        if recheck_result:
            task_entry["recheck"] = recheck_result
    except Exception:
        pass

    # 任务4（2026-09-10）: 成本预算告警——超阈值走 notify 通道
    try:
        html_content = Path(output_path).read_text(encoding="utf-8")
        meta = _parse_html_report(html_content)
        budget_result = check_budget({
            "events_loaded": meta.get("events", 0),
            "cost": {
                "total_cost": meta.get("total_cost", 0.0),
                "total_est_wasted_cost": meta.get("est_waste", 0.0),
                "avoidable_cost_ratio": meta.get("avoidable_cost_ratio", 0.0),
            },
        })
        if budget_result["triggered"]:
            body = format_budget_alert_body(
                {
                    "events_loaded": meta.get("events", 0),
                    "cost": {
                        "total_cost": meta.get("total_cost", 0.0),
                        "total_est_wasted_cost": meta.get("est_waste", 0.0),
                        "avoidable_cost_ratio": meta.get("avoidable_cost_ratio", 0.0),
                    },
                },
                budget_result["alerts"],
            )
            notify_results = send_notify("🚨 AgentLens 成本预算告警", body)
            task_entry["budget_alert"] = {
                "triggered": True,
                "alerts": budget_result["alerts"],
                "notify": notify_results,
            }
    except Exception:
        pass

    _save_tasks()

    return {
        "status": "ok",
        "report_url": report_url,
        "date": today,
        "project": project,
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
# P2-1: Fix tracking API
# ─────────────────────────────────────────────────────────────────

def _get_latest_findings() -> list[dict]:
    """Get all findings from the latest report (across all projects)."""
    reports = _list_report_files()
    if not reports:
        return []
    latest = reports[0]
    path = _get_report_path(latest["date"], latest.get("project", "default"))
    if path is None:
        return []
    try:
        html = path.read_text(encoding="utf-8")
    except Exception:
        return []
    findings = _extract_embedded_findings(html)
    if not findings:
        findings = _parse_html_findings(html)
    return findings


def _recheck_fixed_findings(report_path: str) -> dict | None:
    """Recheck marked_fixed / closed findings against a new report (regression verification).

    状态机（2026-09-10 任务3 增强，连续缺席 N 次审计才确认修复，期间出现即回归）:
    - marked_fixed + 再次出现 → status="reopened", verify_status="regressed"（回归）
    - marked_fixed + 缺席 → absent_streak+=1；连续 VERIFY_STREAK_REQUIRED 次缺席
      → status="closed", verify_status="verified"；不足则保持 marked_fixed + "verifying"
    - closed + 再次出现 → status="reopened", verify_status="regressed"（回归，闭环防复发）
    - closed + 持续缺席 → 保持 closed + "verified"

    Returns a summary dict or None if no recheck was needed.
    """
    fixed_list = _load_fixed_findings()
    marked = [f for f in fixed_list if f.get("status") in ("marked_fixed", "closed")]
    if not marked:
        return None

    try:
        html = Path(report_path).read_text(encoding="utf-8")
    except Exception:
        return None

    current_findings = _extract_embedded_findings(html)
    if not current_findings:
        current_findings = _parse_html_findings(html)

    current_keys: set[tuple] = set()
    for f in current_findings:
        current_keys.add((f["layer"], f["title"]))

    recheck_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reopened = 0
    closed = 0
    verified = 0
    regressed = 0

    for entry in fixed_list:
        if entry.get("status") not in ("marked_fixed", "closed"):
            continue
        layer, title = _decode_finding_key(entry["key"])
        history = entry.setdefault("recheck_history", [])
        if (layer, title) in current_keys:
            # 再次出现 → 回归（无论之前是 marked_fixed 还是 closed）
            entry["status"] = "reopened"
            entry["verify_status"] = "regressed"
            entry["absent_streak"] = 0
            reopened += 1
            regressed += 1
            history.append({"ts": recheck_time, "result": "regressed"})
        else:
            # 缺席 → 累计连续缺席次数
            streak = int(entry.get("absent_streak", 0)) + 1
            entry["absent_streak"] = streak
            if entry.get("status") == "marked_fixed":
                if streak >= VERIFY_STREAK_REQUIRED:
                    entry["status"] = "closed"
                    entry["verify_status"] = "verified"
                    closed += 1
                    verified += 1
                    history.append({"ts": recheck_time, "result": "verified"})
                else:
                    entry["verify_status"] = "verifying"
                    history.append(
                        {"ts": recheck_time, "result": f"absent {streak}/{VERIFY_STREAK_REQUIRED}"}
                    )
            else:  # closed 且持续缺席 → 保持验证通过
                entry["verify_status"] = "verified"
                history.append({"ts": recheck_time, "result": "still_absent"})
        entry["rechecked_at"] = recheck_time

    _save_fixed_findings(fixed_list)
    return {
        "rechecked_at": recheck_time,
        "reopened": reopened,
        "closed": closed,
        "verified": verified,
        "regressed": regressed,
        "total": len(marked),
    }


@app.get("/api/findings/verification")
async def api_findings_verification():
    """任务3（2026-09-10）：修复回归验证汇总——verified / verifying / regressed 状态与历史。

    基于 fixed-findings.json 的 verify_status 状态机（连续 VERIFY_STREAK_REQUIRED 次
    审计缺席才 verified；期间再次出现即 regressed）。
    """
    fixed_list = _load_fixed_findings()
    entries = [e for e in fixed_list if e.get("verify_status")]
    summary = {"verified": 0, "verifying": 0, "regressed": 0}
    for e in entries:
        vs = e.get("verify_status", "verifying")
        summary[vs] = summary.get(vs, 0) + 1
    return {
        "summary": summary,
        "streak_required": VERIFY_STREAK_REQUIRED,
        "entries": entries,
    }


@app.get("/api/findings/status")
async def api_findings_status():
    """Return all findings statuses from the latest report, merged with fix tracking."""
    findings = _get_latest_findings()
    if not findings:
        return {"findings": [], "fixed_tracking": []}

    # Aggregate by (layer, title)
    groups: dict[tuple, dict] = {}
    for f in findings:
        key = (f["layer"], f["title"])
        if key not in groups:
            groups[key] = dict(f)
            groups[key]["count"] = f.get("count", 1)
        else:
            groups[key]["count"] = groups[key].get("count", 1) + f.get("count", 1)
            if (f.get("est_wasted_cost") or 0) > (groups[key].get("est_wasted_cost") or 0):
                groups[key]["est_wasted_cost"] = f.get("est_wasted_cost")

    # Load fixed tracking
    fixed_list = _load_fixed_findings()
    fixed_map: dict[str, dict] = {}
    for entry in fixed_list:
        fixed_map[entry["key"]] = entry

    result_findings = []
    for (layer, title), f in groups.items():
        url_key = _finding_key(layer, title)
        # Path params are auto-decoded by FastAPI, so fixed-findings.json stores
        # the raw decoded key ("layer|title"). Look up with the raw key.
        raw_key = f"{layer}|{title}"
        status = fixed_map.get(raw_key, {}).get("status", "open")
        result_findings.append({
            "key": url_key,
            "layer": layer,
            "severity": f.get("severity", "info"),
            "title": title,
            "est_wasted_cost": f.get("est_wasted_cost"),
            "count": f.get("count", 1),
            "recommendation": f.get("recommendation", ""),
            "status": status,
        })

    return {
        "findings": result_findings,
        "fixed_tracking": fixed_list,
    }


@app.post("/api/findings/{key:path}/mark-fixed")
async def api_findings_mark_fixed(key: str, request: Request):
    """Mark a finding as fixed. Body: {"note": "..."}."""
    try:
        body = await request.json() or {}
    except Exception:
        body = {}
    note = str(body.get("note", "")).strip()

    fixed_list = _load_fixed_findings()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Check if already exists
    for entry in fixed_list:
        if entry["key"] == key:
            if entry.get("status") in ("closed",):
                entry["status"] = "marked_fixed"
                entry["marked_at"] = now
                entry["note"] = note
                entry.pop("rechecked_at", None)
                _save_fixed_findings(fixed_list)
                return {"status": "ok", "key": key, "action": "re-marked"}
            # Already marked_fixed or reopened
            entry["note"] = note or entry.get("note", "")
            _save_fixed_findings(fixed_list)
            return {"status": "ok", "key": key, "action": "note-updated"}

    # New entry
    entry = {
        "key": key,
        "status": "marked_fixed",
        "marked_at": now,
        "note": note,
    }
    fixed_list.append(entry)
    _save_fixed_findings(fixed_list)
    return {"status": "ok", "key": key, "action": "marked"}


@app.get("/api/findings/{key:path}/status")
async def api_findings_key_status(key: str):
    """Get status for a single finding key."""
    fixed_list = _load_fixed_findings()
    for entry in fixed_list:
        if entry["key"] == key:
            return entry
    # Not tracked → "open"
    return {"key": key, "status": "open"}


# ─────────────────────────────────────────────────────────────────
# P2-2: Multi-project API
# ─────────────────────────────────────────────────────────────────

@app.get("/api/projects")
async def api_projects():
    """List all project names with report counts."""
    projects = _list_projects()
    result = []
    for p in projects:
        reports = _list_report_files(p)
        result.append({
            "name": p,
            "report_count": len(reports),
            "latest_date": reports[0]["date"] if reports else None,
        })
    return result


# ─────────────────────────────────────────────────────────────────
# P2-3: Notification API
# ─────────────────────────────────────────────────────────────────

@app.get("/api/notify/config")
async def api_notify_get_config():
    """Return the current notification config (safe, masked)."""
    return get_notify_config()


@app.post("/api/notify/config")
async def api_notify_set_config(request: Request):
    """Save notification config. Body: {"enabled": true, "channels": [...]}."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    if "enabled" not in body or "channels" not in body:
        raise HTTPException(status_code=400, detail="Missing required fields: enabled, channels")

    if not isinstance(body["channels"], list):
        raise HTTPException(status_code=400, detail="channels must be a list")

    ok = save_notify_config(body)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save config")
    return {"status": "ok"}


@app.post("/api/notify/test")
async def api_notify_test(request: Request):
    """Send a test notification via configured channels."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    subject = str(body.get("subject", "AgentLens 通知测试"))
    test_body = str(body.get("body", f"这是一条来自 AgentLens 的测试通知，发送时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"))

    results = send_notify(subject, test_body)
    return {"status": "ok", "results": results}


# ─────────────────────────────────────────────────────────────────
# P2-1: Fix tracking page
# ─────────────────────────────────────────────────────────────────

def _build_fix_track_page() -> str:
    """Build the fix tracking page with findings status table and tracking history."""
    findings = _get_latest_findings()
    fixed_list = _load_fixed_findings()
    fixed_map: dict[str, dict] = {}
    for entry in fixed_list:
        fixed_map[entry["key"]] = entry

    # Aggregate findings
    groups: dict[tuple, dict] = {}
    for f in findings:
        key = (f["layer"], f["title"])
        if key not in groups:
            groups[key] = dict(f)
            groups[key]["count"] = f.get("count", 1)
        else:
            groups[key]["count"] = groups[key].get("count", 1) + f.get("count", 1)
            if (f.get("est_wasted_cost") or 0) > (groups[key].get("est_wasted_cost") or 0):
                groups[key]["est_wasted_cost"] = f.get("est_wasted_cost")

    def _sev_badge(sev: str) -> str:
        colors = {"high": "badge-err", "medium": "badge-warn", "low": "badge-info", "info": "badge-info"}
        return f'<span class="badge {colors.get(sev, "badge-info")}">{sev.upper()}</span>'

    def _status_badge(status: str) -> str:
        labels = {
            "open": '<span class="badge badge-warn">待处理</span>',
            "marked_fixed": '<span class="badge badge-info">已标记修复</span>',
            "reopened": '<span class="badge badge-err">重新出现</span>',
            "closed": '<span class="badge badge-ok">已闭环</span>',
        }
        return labels.get(status, f'<span class="badge">{status}</span>')

    def _verify_badge(entry: dict) -> str:
        """任务3（2026-09-10）：修复回归验证状态徽章（verifying/verified/regressed）。"""
        vs = entry.get("verify_status", "")
        streak = entry.get("absent_streak", 0)
        if vs == "verified":
            return ' <span class="badge badge-ok" title="连续缺席审计验证通过">✓ 已验证</span>'
        if vs == "regressed":
            return ' <span class="badge badge-err" title="修复后再次出现，已回归">回归</span>'
        if vs == "verifying":
            return (
                f' <span class="badge badge-info" title="修复验证中，连续缺席 '
                f'{VERIFY_STREAK_REQUIRED} 次审计确认">验证中 {streak}/{VERIFY_STREAK_REQUIRED}</span>'
            )
        return ""

    # Build findings table rows
    rows = []
    for (layer, title), f in sorted(groups.items(), key=lambda x: (x[1].get("est_wasted_cost") or 0), reverse=True):
        url_key = _finding_key(layer, title)
        tracked = fixed_map.get(url_key, {})
        status = tracked.get("status", "open")
        note = tracked.get("note", "")
        count_str = f' x{f["count"]}' if f.get("count", 1) > 1 else ""
        waste_val = f.get("est_wasted_cost")
        waste_display = f"{waste_val:.2f}" if waste_val is not None else "-"
        rows.append(
            f'<tr>'
            f'<td>{_sev_badge(f.get("severity", "info"))}</td>'
            f'<td>{f["layer"]}</td>'
            f'<td>{f["title"][:60]}{"…" if len(f["title"]) > 60 else ""}{count_str}</td>'
            f'<td class="num">{waste_display}</td>'
            f'<td>{_status_badge(status)}{_verify_badge(tracked)}</td>'
            f'<td>'
            f'<button class="btn btn-ghost btn-sm" onclick="markFixed(\'{url_key}\')" '
            f'{"disabled" if status in ("marked_fixed", "closed") else ""}>标记已修复</button>'
            f'</td>'
            f'</tr>'
        )

    # Build tracking history table
    tracking_rows = []
    for entry in reversed(fixed_list):
        key = entry.get("key", "")
        layer, title = _decode_finding_key(key)
        history = entry.get("recheck_history", [])
        hist_txt = " → ".join(h.get("result", "") for h in history[-3:]) if history else "-"
        tracking_rows.append(
            f'<tr>'
            f'<td>{title[:50]}{"…" if len(title) > 50 else ""}</td>'
            f'<td>{layer}</td>'
            f'<td>{_status_badge(entry.get("status", ""))}{_verify_badge(entry)}</td>'
            f'<td>{entry.get("marked_at", entry.get("rechecked_at", "-"))}</td>'
            f'<td>{entry.get("note", "-")}</td>'
            f'<td class="verify-hist">{hist_txt}</td>'
            f'</tr>'
        )

    content = (
        f'<div class="card"><h2>🔧 发现列表</h2>'
        f'<div class="search-box">'
        f'<input type="text" id="finding-search" placeholder="搜索发现标题…" oninput="filterFindings()">'
        f'<select id="status-filter" onchange="filterFindings()" style="padding:8px 12px;border:1px solid var(--border);'
        f'border-radius:6px;background:var(--bg-primary);color:var(--text-primary);font-size:13px">'
        f'<option value="">全部状态</option>'
        f'<option value="open">待处理</option>'
        f'<option value="marked_fixed">已标记修复</option>'
        f'<option value="reopened">重新出现</option>'
        f'<option value="closed">已闭环</option>'
        f'</select>'
        f'</div>'
        f'<table id="findings-table"><thead><tr>'
        f'<th>严重度</th><th>层</th><th>标题</th><th>预估浪费</th><th>状态</th><th>操作</th>'
        f'</tr></thead><tbody>{"".join(rows) if rows else "<tr><td colspan=6 class=empty>暂无发现</td></tr>"}'
        f'</tbody></table></div>'
        f'<div class="card"><h2>📋 修复跟踪记录</h2>'
        f'<p style="font-size:12px;color:#888;margin-bottom:8px">验证状态：连续缺席 '
        f'{VERIFY_STREAK_REQUIRED} 次审计确认修复（✓已验证），期间再次出现即标记回归（回归）。</p>'
        + (f'<table><thead><tr><th>标题</th><th>层</th><th>状态</th><th>时间</th><th>备注</th><th>验证记录</th></tr></thead>'
           f'<tbody>{"".join(tracking_rows) if tracking_rows else "<tr><td colspan=6 class=empty>暂无记录</td></tr>"}'
           f'</tbody></table>'
           if tracking_rows else '<p class="empty">暂无修复跟踪记录</p>')
        + '</div>'
        # Modal for mark-fixed note
        + '<div id="mark-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;'
        'background:rgba(0,0,0,0.6);z-index:1000;align-items:center;justify-content:center">'
        '<div style="background:var(--bg-panel);border:1px solid var(--border);border-radius:8px;'
        'padding:24px;min-width:400px;max-width:500px">'
        '<h3 style="margin-bottom:12px">标记已修复</h3>'
        '<div class="form-group"><label>备注（可选）</label>'
        '<input type="text" id="mark-note" placeholder="例如：已启用压缩策略">'
        '</div>'
        '<div style="display:flex;gap:8px;justify-content:flex-end">'
        '<button class="btn btn-ghost" onclick="closeModal()">取消</button>'
        '<button class="btn btn-primary" id="mark-confirm-btn" onclick="confirmMark()">确认</button>'
        '</div>'
        '</div></div>'
        + '<script>'
        'var currentKey="";'
        'function markFixed(key){'
        '  currentKey=key;'
        '  document.getElementById("mark-modal").style.display="flex";'
        '  document.getElementById("mark-note").value="";'
        '  document.getElementById("mark-note").focus();'
        '}'
        'function closeModal(){'
        '  document.getElementById("mark-modal").style.display="none";'
        '  currentKey="";'
        '}'
        'async function confirmMark(){'
        '  var note=document.getElementById("mark-note").value.trim();'
        '  var btn=document.getElementById("mark-confirm-btn");'
        '  btn.disabled=true;btn.textContent="提交中…";'
        '  try{'
        '    var resp=await fetch("/api/findings/"+encodeURIComponent(currentKey)+"/mark-fixed",{'
        '      method:"POST",'
        '      headers:{"Content-Type":"application/json"},'
        '      body:JSON.stringify({note:note})'
        '    });'
        '    if(resp.ok){window.location.reload()}'
        '    else{alert("标记失败")}'
        '  }catch(e){alert("请求失败: "+e.message)}'
        '  finally{btn.disabled=false;btn.textContent="确认"}'
        '}'
        'function filterFindings(){'
        '  var q=document.getElementById("finding-search").value.trim().toLowerCase();'
        '  var s=document.getElementById("status-filter").value;'
        '  var rows=document.querySelectorAll("#findings-table tbody tr");'
        '  rows.forEach(function(r){'
        '    var title=r.cells[2].textContent.toLowerCase();'
        '    var statusBadge=r.cells[4].textContent;'
        '    var statusMap={"待处理":"open","已标记修复":"marked_fixed","重新出现":"reopened","已闭环":"closed"};'
        '    var status="";'
        '    for(var k in statusMap){if(statusBadge.includes(k)){status=statusMap[k];break}}'
        '    var matchQ=!q||title.includes(q);'
        '    var matchS=!s||status===s;'
        '    r.style.display=(matchQ&&matchS)?"":"none";'
        '  });'
        '}'
        '</script>'
    )

    return _base_page(
        "修复跟踪", content, active_nav="/fix-track",
        topbar_title="修复跟踪",
    )


# ─────────────────────────────────────────────────────────────────
# P2-3: Notification config page
# ─────────────────────────────────────────────────────────────────

def _build_notify_page() -> str:
    """Build the notification configuration page."""
    config = get_notify_config()
    config_js = _js(config)

    channels_html = ""
    if config.get("channels"):
        for i, ch in enumerate(config["channels"]):
            ch_type = ch.get("type", "")
            ch_type_label = {"feishu": "飞书", "webhook": "Webhook", "command": "命令"}.get(ch_type, ch_type)
            detail = ""
            if ch_type == "feishu":
                detail = f"target: {ch.get('target', '-')} | token_cmd: {ch.get('token_cmd', '-')}"
            elif ch_type == "webhook":
                detail = f"url: {ch.get('url', '-')}"
            elif ch_type == "command":
                detail = f"cmd: {ch.get('cmd', '-')}"
            channels_html += (
                f'<tr>'
                f'<td><span class="badge badge-info">{ch_type_label}</span></td>'
                f'<td>{detail}</td>'
                f'<td><button class="btn btn-ghost btn-sm" onclick="removeChannel({i})">删除</button></td>'
                f'</tr>'
            )

    js_script = (
        '<script>\n'
        f'var CONFIG={config_js};\n'
        'document.getElementById("ch-type").addEventListener("change",function(){\n'
        '  var t=this.value;\n'
        '  document.getElementById("feishu-fields").style.display=t==="feishu"?"":"none";\n'
        '  document.getElementById("webhook-fields").style.display=t==="webhook"?"":"none";\n'
        '  document.getElementById("command-fields").style.display=t==="command"?"":"none";\n'
        '});\n'
        'function toggleEnabled(){\n'
        '  CONFIG.enabled=document.getElementById("notify-enabled").checked;\n'
        '  saveConfig();\n'
        '}\n'
        'async function saveConfig(){\n'
        '  try{\n'
        '    var resp=await fetch("/api/notify/config",{\n'
        '      method:"POST",headers:{"Content-Type":"application/json"},\n'
        '      body:JSON.stringify(CONFIG)\n'
        '    });\n'
        '    if(!resp.ok){alert("保存失败")}\n'
        '  }catch(e){alert("保存失败: "+e.message)}\n'
        '}\n'
        'function addChannel(){\n'
        '  var t=document.getElementById("ch-type").value;\n'
        '  var ch={type:t};\n'
        '  if(t==="feishu"){\n'
        '    ch.target=document.getElementById("feishu-target").value.trim();\n'
        '    ch.token_cmd=document.getElementById("feishu-token-cmd").value.trim();\n'
        '  }else if(t==="webhook"){\n'
        '    ch.url=document.getElementById("webhook-url").value.trim();\n'
        '    ch.secret=document.getElementById("webhook-secret").value.trim();\n'
        '  }else if(t==="command"){\n'
        '    ch.cmd=document.getElementById("command-cmd").value.trim();\n'
        '  }\n'
        '  if(!CONFIG.channels)CONFIG.channels=[];\n'
        '  CONFIG.channels.push(ch);\n'
        '  saveConfig().then(function(){window.location.reload()});\n'
        '}\n'
        'function removeChannel(idx){\n'
        '  if(!confirm("确认删除此渠道?"))return;\n'
        '  CONFIG.channels.splice(idx,1);\n'
        '  saveConfig().then(function(){window.location.reload()});\n'
        '}\n'
        'async function testNotify(){\n'
        '  var subj=document.getElementById("test-subject").value.trim();\n'
        '  var body=document.getElementById("test-body").value.trim();\n'
        '  var result=document.getElementById("test-result");\n'
        "  result.innerHTML='<div class=\"result-box info\">发送中…</div>';\n"
        '  try{\n'
        '    var resp=await fetch("/api/notify/test",{\n'
        '      method:"POST",headers:{"Content-Type":"application/json"},\n'
        '      body:JSON.stringify({subject:subj,body:body})\n'
        '    });\n'
        '    var data=await resp.json();\n'
        '    if(data.status==="ok"){\n'
        '      var html="";\n'
        '      data.results.forEach(function(r){\n'
        '        var cls=r.status==="ok"?"success":"error";\n'
        "        html+='<div class=\"result-box '+cls+'\">'+r.channel+': '+r.status+\n"
        "        +(r.detail?\" — \"+r.detail:\"\")+'</div>';\n"
        '      });\n'
        '      result.innerHTML=html;\n'
        '    }else{\n'
        "      result.innerHTML='<div class=\"result-box error\">发送失败</div>';\n"
        '    }\n'
        "  }catch(e){result.innerHTML='<div class=\"result-box error\">请求失败: '+e.message+'</div>'}\n"
        '}\n'
        '</script>'
    )

    content = (
        f'<div class="card"><h2>🔔 通知渠道配置</h2>'
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">'
        f'<label style="display:flex;align-items:center;gap:8px;font-size:13px">'
        f'<input type="checkbox" id="notify-enabled" onchange="toggleEnabled()" '
        f'{"checked" if config.get("enabled") else ""}>'
        f'启用通知</label>'
        f'<span style="font-size:12px;color:var(--text-secondary)">'
        f'关闭时回退到 hermes send -t feishu 默认行为</span>'
        f'</div>'
        f'<h3>当前渠道</h3>'
        + (f'<table><thead><tr><th>类型</th><th>详情</th><th>操作</th></tr></thead>'
           f'<tbody>{channels_html if channels_html else "<tr><td colspan=3 class=empty>未配置渠道</td></tr>"}'
           f'</tbody></table>'
           if channels_html else '<p class="empty">未配置渠道</p>')
        + '</div>'
        f'<div class="card"><h2>添加渠道</h2>'
        f'<div class="form-group"><label>渠道类型</label>'
        f'<select id="ch-type" style="padding:10px 14px;border:1px solid var(--border);'
        f'border-radius:6px;font-size:14px;background:var(--bg-primary);color:var(--text-primary);width:100%">'
        f'<option value="feishu">飞书 (hermes send)</option>'
        f'<option value="webhook">Webhook (HTTP POST)</option>'
        f'<option value="command">自定义命令</option>'
        f'</select></div>'
        f'<div class="form-group" id="feishu-fields">'
        f'<label>飞书目标 (target)</label>'
        f'<input type="text" id="feishu-target" placeholder="例如: oc_xxx">'
        f'<label style="margin-top:8px">Token 获取命令 (可选)</label>'
        f'<input type="text" id="feishu-token-cmd" placeholder="例如: cat /path/to/token">'
        f'</div>'
        f'<div class="form-group" id="webhook-fields" style="display:none">'
        f'<label>Webhook URL</label>'
        f'<input type="text" id="webhook-url" placeholder="https://hooks.example.com/webhook">'
        f'<label style="margin-top:8px">密钥 (可选)</label>'
        f'<input type="text" id="webhook-secret" placeholder="bearer token 或 secret">'
        f'</div>'
        f'<div class="form-group" id="command-fields" style="display:none">'
        f'<label>命令模板</label>'
        f'<input type="text" id="command-cmd" placeholder="hermes send -t feishu -s {{subject}} -f {{body}}">'
        f'<span style="font-size:11px;color:var(--text-secondary)">'
        f'支持 {{subject}} {{body}} 占位符</span>'
        f'</div>'
        f'<button class="btn btn-primary" onclick="addChannel()">添加渠道</button>'
        f'<div id="add-result"></div>'
        f'</div>'
        f'<div class="card"><h2>测试通知</h2>'
        f'<div class="form-group"><label>测试主题</label>'
        f'<input type="text" id="test-subject" value="AgentLens 通知测试" placeholder="通知主题">'
        f'</div>'
        f'<div class="form-group"><label>测试内容</label>'
        f'<input type="text" id="test-body" value="这是一条来自 AgentLens 的测试通知" placeholder="通知内容">'
        f'</div>'
        f'<button class="btn btn-success" onclick="testNotify()">发送测试通知</button>'
        f'<div id="test-result"></div>'
        f'</div>'
        + js_script
    )

    return _base_page(
        "通知配置", content, active_nav="/notify",
        topbar_title="通知配置",
    )


# ─────────────────────────────────────────────────────────────────
# Pages: HTML UI
# ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def page_dashboard():
    """Dashboard page: KPI cards, charts, recent reports, watchdog, audit dynamics."""
    return _build_dashboard()


@app.get("/reports", response_class=HTMLResponse)
async def page_reports(project: str = "default"):
    """Full report list page with sortable table and search."""
    return _build_reports_list(project)


@app.get("/audit", response_class=HTMLResponse)
async def page_audit():
    """Audit trigger page with form and recent tasks."""
    return _build_audit_page()


@app.get("/reports/compare", response_class=HTMLResponse)
async def page_report_compare(base: str = "", curr: str = ""):
    """Compare findings between two reports."""
    if not base or not curr:
        return HTMLResponse(
            content=_base_page(
                "参数错误",
                '<div class="card"><h2>参数不完整</h2>'
                '<p class="empty">请选择两份报告日期。使用方式: /reports/compare?base=YYYYMMDD&curr=YYYYMMDD</p>'
                '<p style="margin-top:12px"><a href="/reports" class="btn btn-primary">返回报告列表</a></p></div>',
                active_nav="/reports",
                topbar_title="参数错误",
            ),
            status_code=400,
        )
    return _build_report_compare(base, curr)


@app.get("/reports/{date}", response_class=HTMLResponse)
async def page_report_detail(date: str):
    """Report detail page with iframe-embedded HTML (full-width layout)."""
    return _build_report_detail(date)


@app.get("/fix-track", response_class=HTMLResponse)
async def page_fix_track():
    """Fix tracking page: findings status table and tracking history."""
    return _build_fix_track_page()


@app.get("/notify", response_class=HTMLResponse)
async def page_notify():
    """Notification configuration page."""
    return _build_notify_page()
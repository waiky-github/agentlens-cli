"""FastAPI Web 服务：REST API + 浏览器操作界面。

提供审计报告浏览、审计触发、watchdog 漂移状态查看等功能。
"""

import json
import os
import re
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


app.add_middleware(NoCacheMiddleware)


# ─────────────────────────────────────────────────────────────────
# HTML parsing helpers
# ─────────────────────────────────────────────────────────────────

def _parse_html_report(html_content: str) -> dict:
    """Parse an audit HTML report to extract metadata fields.

    Returns a dict with keys: events, high, medium, low, info, findings_total.
    Values are 0 if parsing fails.
    """
    result = {"events": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "findings_total": 0}

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

    return result


def _list_report_files() -> list[dict]:
    """List all audit-*.html files in the report directory with metadata."""
    reports = []
    if not REPORT_DIR.is_dir():
        return reports

    for f in sorted(REPORT_DIR.glob("audit-*.html"), reverse=True):
        # Extract date from filename: audit-YYYYMMDD.html
        m = re.match(r"audit-(\d{8})\.html", f.name)
        if not m:
            continue
        date_str = m.group(1)
        stat = f.stat()
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        # Parse metadata from HTML
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
            "findings_total": meta["findings_total"],
        })

    return reports


def _get_report_path(date_str: str) -> Optional[Path]:
    """Get the report file path for a given date string (YYYYMMDD)."""
    f = REPORT_DIR / f"audit-{date_str}.html"
    if f.is_file():
        return f
    return None


# ─────────────────────────────────────────────────────────────────
# API: Reports
# ─────────────────────────────────────────────────────────────────

@app.get("/api/reports")
async def api_reports():
    """List all audit reports in the report directory."""
    return _list_report_files()


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
            return JSONResponse(
                status_code=500,
                content={"status": "error", "detail": proc.stderr.strip() or proc.stdout.strip()},
            )
    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Audit timed out after 300 seconds"},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )

    return {
        "status": "ok",
        "report_url": f"/reports/{today}",
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
# Pages: HTML UI (all inline CSS, no external deps)
# ─────────────────────────────────────────────────────────────────

_CSS = """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  background:#f5f6fa;color:#2d3436;line-height:1.6;padding:20px}
.container{max-width:1100px;margin:0 auto}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:24px 30px;
  border-radius:12px;margin-bottom:24px}
.header h1{font-size:22px;margin-bottom:4px}
.header .sub{font-size:13px;opacity:0.7}
.nav{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.nav a{text-decoration:none;padding:8px 16px;border-radius:6px;font-size:14px;font-weight:600;
  background:#fff;color:#333;box-shadow:0 1px 3px rgba(0,0,0,0.08);transition:background 0.15s}
.nav a:hover{background:#e8e8e8}
.nav a.active{background:#1a1a2e;color:#fff}
.card{background:#fff;border-radius:10px;padding:20px;margin-bottom:20px;
  box-shadow:0 1px 4px rgba(0,0,0,0.06)}
.card h2{font-size:17px;border-bottom:2px solid #eee;padding-bottom:10px;margin-bottom:16px}
.card h3{font-size:15px;margin:16px 0 8px;color:#555}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #eee}
th{background:#f8f9fa;font-weight:600;color:#555}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover{background:#f8f9fa}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.kpi-card{background:#fff;border-radius:10px;padding:16px;text-align:center;
  box-shadow:0 1px 4px rgba(0,0,0,0.06);border-top:3px solid #0d6efd}
.kpi-card.red{border-top-color:#dc3545}
.kpi-card.orange{border-top-color:#fd7e14}
.kpi-card.green{border-top-color:#198754}
.kpi-card.gray{border-top-color:#6c757d}
.kpi-label{font-size:12px;color:#888;margin-bottom:4px}
.kpi-value{font-size:26px;font-weight:800;line-height:1.2}
.kpi-sub{font-size:11px;color:#aaa;margin-top:2px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700}
.badge-ok{background:#d1e7dd;color:#0f5132}
.badge-warn{background:#f8d7da;color:#842029}
.badge-info{background:#cfe2ff;color:#084298}
.sev-high{color:#dc3545;font-weight:700}
.sev-medium{color:#fd7e14;font-weight:700}
.sev-low{color:#ffc107;font-weight:700}
.btn{display:inline-block;padding:8px 20px;border-radius:6px;font-size:14px;font-weight:600;
  border:none;cursor:pointer;text-decoration:none;color:#fff;transition:opacity 0.15s}
.btn:hover{opacity:0.85}
.btn-primary{background:#0d6efd}
.btn-success{background:#198754}
.btn-sm{padding:4px 10px;font-size:12px}
.form-group{margin-bottom:12px}
.form-group label{display:block;font-size:13px;font-weight:600;margin-bottom:4px;color:#555}
.form-group input{width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:6px;font-size:14px}
.form-group input:focus{outline:none;border-color:#0d6efd;box-shadow:0 0 0 2px rgba(13,110,253,0.15)}
.result-box{margin-top:12px;padding:12px;border-radius:6px;font-size:13px}
.result-box.success{background:#d1e7dd;color:#0f5132}
.result-box.error{background:#f8d7da;color:#842029}
.footer{margin-top:30px;padding:20px;text-align:center;color:#888;font-size:12px;border-top:1px solid #ddd}
.empty{color:#999;font-style:italic;padding:20px;text-align:center}
@media(max-width:768px){
  body{padding:10px}
  .header{padding:16px}
  .kpi-grid{grid-template-columns:repeat(2,1fr)}
  .nav{flex-direction:column}
}
"""


def _base_page(title: str, content: str, active_nav: str = "") -> str:
    """Build a complete HTML page with shared header/nav/footer."""
    nav_items = [
        ("/", "仪表盘"),
        ("/reports", "报告列表"),
    ]
    nav_html = []
    for href, label in nav_items:
        cls = "active" if href == active_nav else ""
        nav_html.append(f'<a href="{href}" class="{cls}">{label}</a>')
    nav_html = "\n".join(nav_html)

    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        f"<title>{title} — AgentLens Audit</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n<div class=\"container\">\n"
        f'<div class="header"><h1>AgentLens 审计 Web</h1>'
        f'<div class="sub">多智能体审计平台 — 报告浏览 / 审计触发 / 漂移监控</div></div>\n'
        f'<div class="nav">{nav_html}</div>\n'
        f"{content}\n"
        f'<div class="footer">'
        f'<p>agentlens-cli v0.2.1 — 报告目录: {REPORT_DIR}</p>'
        f'</div>\n'
        f'</div>\n</body>\n</html>'
    )


@app.get("/", response_class=HTMLResponse)
async def page_dashboard():
    """Dashboard page: KPI cards, recent reports, watchdog status, trigger audit."""
    reports = _list_report_files()

    # Latest report KPIs
    latest_events = 0
    latest_findings = 0
    latest_high = 0
    latest_date = "—"
    if reports:
        latest = reports[0]
        latest_date = latest["date"]
        latest_events = latest["events"]
        latest_findings = latest["findings_total"]
        latest_high = latest["high"]

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

    # KPI cards
    kpi_html = (
        f'<div class="kpi-card green">'
        f'<div class="kpi-label">最新报告日期</div>'
        f'<div class="kpi-value">{latest_date}</div></div>'
        f'<div class="kpi-card gray">'
        f'<div class="kpi-label">事件数</div>'
        f'<div class="kpi-value">{latest_events}</div></div>'
        f'<div class="kpi-card {"red" if latest_high > 0 else "green"}">'
        f'<div class="kpi-label">发现总数</div>'
        f'<div class="kpi-value">{latest_findings}</div>'
        f'<div class="kpi-sub">High: {latest_high}</div></div>'
        f'<div class="kpi-card {"red" if latest_high > 0 else "green"}">'
        f'<div class="kpi-label">高风险数</div>'
        f'<div class="kpi-value">{latest_high}</div></div>'
    )

    # Recent reports table
    report_rows = []
    for r in reports[:10]:
        date_formatted = f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:8]}"
        report_rows.append(
            f"<tr>"
            f"<td>{date_formatted}</td>"
            f"<td class='num'>{r['events']}</td>"
            f"<td class='num'>{r['findings_total']}</td>"
            f"<td class='num'><span class='sev-high'>{r['high']}</span></td>"
            f"<td class='num'>{r['size_bytes']:,}</td>"
            f"<td><a href='/reports/{r['date']}' class='btn btn-primary btn-sm'>查看</a></td>"
            f"</tr>"
        )
    report_table = (
        "<table><thead><tr>"
        "<th>日期</th><th>事件</th><th>发现</th><th>High</th><th>大小</th><th>操作</th>"
        "</tr></thead><tbody>"
        + "\n".join(report_rows)
        + "</tbody></table>"
    ) if report_rows else "<p class='empty'>暂无报告</p>"

    # Watchdog card
    wd_badge = '<span class="badge badge-ok">正常</span>' if baseline_exists else '<span class="badge badge-warn">基线不存在</span>'
    wd_html = (
        f'<div class="card"><h2>Watchdog 漂移状态</h2>'
        f'<table><tbody>'
        f'<tr><td>基线文件</td><td>{wd_badge}</td></tr>'
        f'<tr><td>更新时间</td><td>{baseline_mtime}</td></tr>'
        f'<tr><td>基线事件数</td><td>{baseline_events}</td></tr>'
        f'</tbody></table></div>'
    )

    # Trigger audit form
    trigger_html = (
        f'<div class="card"><h2>触发审计</h2>'
        f'<form id="audit-form" onsubmit="return triggerAudit(event)">'
        f'<div class="form-group">'
        f'<label for="input-path">事件流文件路径</label>'
        f'<input type="text" id="input-path" name="input" '
        f'placeholder="例如: /path/to/events.jsonl" required>'
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
        f'  btn.disabled=true;btn.textContent="审计执行中...";'
        f'  result.innerHTML="";'
        f'  try{{'
        f'    var resp=await fetch("/api/audit/run",{{'
        f'      method:"POST",'
        f'      headers:{{"Content-Type":"application/json"}},'
        f'      body:JSON.stringify({{input:document.getElementById("input-path").value}})'
        f'    }});'
        f'    var data=await resp.json();'
        f'    if(data.status==="ok"){{'
        f'      result.innerHTML=\'<div class="result-box success">审计成功！'
        f'      <a href="\'+data.report_url+\'">查看报告</a></div>\';'
        f'    }}else{{'
        f'      result.innerHTML=\'<div class="result-box error">审计失败: \'+data.detail+\'</div>\';'
        f'    }}'
        f'  }}catch(err){{'
        f'    result.innerHTML=\'<div class="result-box error">请求失败: \'+err.message+\'</div>\';'
        f'  }}'
        f'  btn.disabled=false;btn.textContent="触发审计";'
        f'}}'
        f'</script>'
    )

    content = kpi_html + report_table + wd_html + trigger_html
    return _base_page("仪表盘", content, active_nav="/")


@app.get("/reports", response_class=HTMLResponse)
async def page_reports():
    """Full report list page."""
    reports = _list_report_files()

    if not reports:
        content = "<p class='empty'>暂无报告</p>"
        return _base_page("报告列表", content, active_nav="/reports")

    rows = []
    for r in reports:
        date_formatted = f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:8]}"
        rows.append(
            f"<tr>"
            f"<td>{date_formatted}</td>"
            f"<td class='num'>{r['events']}</td>"
            f"<td class='num'>{r['findings_total']}</td>"
            f"<td class='num'><span class='sev-high'>{r['high']}</span></td>"
            f"<td class='num'><span class='sev-medium'>{r['medium']}</span></td>"
            f"<td class='num'><span class='sev-low'>{r['low']}</span></td>"
            f"<td class='num'>{r['size_bytes']:,}</td>"
            f"<td><a href='/reports/{r['date']}' class='btn btn-primary btn-sm'>查看</a>"
            f" <a href='/api/reports/{r['date']}/html' class='btn btn-sm' style='background:#6c757d'>原始HTML</a></td>"
            f"</tr>"
        )

    content = (
        f'<div class="card"><h2>全部报告 ({len(reports)})</h2>'
        f"<table><thead><tr>"
        f"<th>日期</th><th>事件</th><th>发现</th><th>High</th><th>Med</th><th>Low</th><th>大小</th><th>操作</th>"
        f"</tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table></div>"
    )
    return _base_page("报告列表", content, active_nav="/reports")


@app.get("/reports/{date}", response_class=HTMLResponse)
async def page_report_detail(date: str):
    """Report detail page with iframe-embedded HTML."""
    path = _get_report_path(date)
    if path is None:
        content = (
            f'<div class="card"><h2>报告未找到</h2>'
            f'<p class="empty">日期 {date} 的报告不存在</p>'
            f'<p><a href="/reports" class="btn btn-primary">返回报告列表</a></p></div>'
        )
        return HTMLResponse(
            content=_base_page("报告未找到", content, active_nav="/reports"),
            status_code=404,
        )

    date_formatted = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    content = (
        f'<div class="card" style="padding:8px">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'padding:8px 12px;background:#f8f9fa;border-radius:6px;margin-bottom:8px">'
        f'<span style="font-weight:700">{date_formatted} 审计报告</span>'
        f'<span>'
        f'<a href="/api/reports/{date}/html" class="btn btn-sm" style="background:#6c757d">原始 HTML</a> '
        f'<a href="/reports" class="btn btn-primary btn-sm">返回列表</a>'
        f'</span>'
        f'</div>'
        f'<iframe src="/api/reports/{date}/html" '
        f'style="width:100%;height:calc(100vh - 180px);border:none;border-radius:6px" '
        f'sandbox="allow-scripts allow-same-origin"></iframe>'
        f'</div>'
    )
    return _base_page(f"{date_formatted} 审计报告", content, active_nav="/reports")
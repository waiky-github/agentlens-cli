"""Pytest shared configuration.

Provides a shared AGENTLENS_REPORT_DIR for web-related tests and pre-seeds a
sample report (audit-20260909.html) so tests that read reports by date work in
a clean/portable environment (no dependency on host-local report directories).
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Shared, deterministic location (both test_web and test_verification import
# the web module; both must observe the SAME REPORT_DIR).
REPORT_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "agentlens-test-reports"


def pytest_configure(config):
    os.environ["AGENTLENS_REPORT_DIR"] = str(REPORT_DIR)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_sample_report()


def _ensure_sample_report():
    target = REPORT_DIR / "audit-20260909.html"
    if target.exists() and target.stat().st_size > 0:
        return
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    # Prefer the anonymized 11268-event stream (rich findings set for CSV
    # aggregation tests); fall back to the bundled demo data.
    anon = REPO_ROOT / "examples" / "hermes_gateway_events_anon.jsonl"
    cmd = None
    if anon.exists():
        cmd = [sys.executable, "-m", "agentlens_cli", "audit",
               "--input", str(anon), "--format", "html", "--output", str(target)]
    else:
        cmd = [sys.executable, "-m", "agentlens_cli", "demo",
               "--output", str(target)]
    result = subprocess.run(cmd, check=False, env=env, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to generate sample report for web tests:\n"
            + result.stderr.decode("utf-8", errors="replace")
        )

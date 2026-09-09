"""Tests for the demo subcommand: generates HTML with required sections."""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


PYTHON = "/home/agentuser/.hermes/hermes-agent/venv/bin/python"
PKG_DIR = Path(__file__).resolve().parent.parent


def _run_demo(output_path):
    """Run `python -m agentlens_cli demo -o <output_path>`."""
    cmd = [
        PYTHON, "-m", "agentlens_cli", "demo",
        "--output", str(output_path),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PKG_DIR)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(PKG_DIR),
        env=env,
    )


class TestDemo:
    """Demo subcommand: generates HTML with required sections, no external resources."""

    def test_demo_generates_html(self):
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            proc = _run_demo(tmp)
            assert proc.returncode == 0, (
                f"demo failed: rc={proc.returncode}\nstderr: {proc.stderr}"
            )
            with open(tmp, "r", encoding="utf-8") as fh:
                html = fh.read()
            assert "<!DOCTYPE html>" in html
            assert "AgentLens" in html
        finally:
            os.unlink(tmp)

    def test_demo_has_collaboration_graph_section(self):
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            proc = _run_demo(tmp)
            assert proc.returncode == 0
            with open(tmp, "r", encoding="utf-8") as fh:
                html = fh.read()
            assert "协作图谱" in html, "missing '协作图谱' section in demo HTML"
        finally:
            os.unlink(tmp)

    def test_demo_has_shadow_agent_section(self):
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            proc = _run_demo(tmp)
            assert proc.returncode == 0
            with open(tmp, "r", encoding="utf-8") as fh:
                html = fh.read()
            assert "影子智能体" in html, "missing '影子智能体' section in demo HTML"
        finally:
            os.unlink(tmp)

    def test_demo_no_external_resources(self):
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            proc = _run_demo(tmp)
            assert proc.returncode == 0
            with open(tmp, "r", encoding="utf-8") as fh:
                html = fh.read()
            # Allow SVG namespace xmlns="http://www.w3.org/2000/svg" (standard XML namespace, not a resource load)
            html_no_svg_ns = html.replace('xmlns="http://www.w3.org/2000/svg"', "")
            # Allow whitelisted ECharts CDN (dashboard option B, explicit product decision)
            html_no_cdn = html_no_svg_ns.replace(
                'https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js', ""
            )
            assert "http://" not in html_no_cdn, "demo HTML contains http:// reference"
            assert "https://" not in html_no_cdn, "demo HTML contains https:// reference"
            # Exactly four <script> tags: ECharts CDN loader + dashboard init +
            # scrollspy nav + embedded findings-data JSON (programmatic consumers).
            script_count = len(re.findall(r"<script", html_no_cdn.lower()))
            assert script_count == 4, (
                f"expected 4 <script> (ECharts CDN + dashboard init + scrollspy + findings-data), got {script_count}"
            )
            # Embedded findings JSON should be present and parseable.
            import json as _json
            m = re.search(
                r'<script id="findings-data" type="application/json">(.*?)</script>',
                html_no_cdn, re.DOTALL,
            )
            assert m, "findings-data JSON block missing"
            data = _json.loads(m.group(1))
            assert isinstance(data, list) and len(data) > 0, "findings-data should be a non-empty list"
        finally:
            os.unlink(tmp)

    def test_demo_has_all_seven_layers(self):
        """Demo HTML should reference all seven audit layers."""
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            proc = _run_demo(tmp)
            assert proc.returncode == 0
            with open(tmp, "r", encoding="utf-8") as fh:
                html = fh.read()
            # Check for layer sections
            assert "协作图谱" in html      # layer 1: graph
            assert "决策审计" in html      # layer 2: decision
            assert "证据链" in html        # layer 3: evidence
            assert "成本治理" in html      # layer 4: cost
            assert "影子智能体" in html    # layer 5: shadow
            assert "决策权限合规" in html  # layer 6: compliance
        finally:
            os.unlink(tmp)

    def test_demo_stdout_hints_at_output(self):
        """CLI stdout should mention the output file path."""
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            proc = _run_demo(tmp)
            assert proc.returncode == 0
            assert "Demo report generated" in proc.stdout or "demo" in proc.stdout.lower()
        finally:
            os.unlink(tmp)
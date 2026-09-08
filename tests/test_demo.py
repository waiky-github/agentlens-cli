"""Tests for the demo subcommand: generates HTML with required sections."""

import os
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
            assert "http://" not in html_no_svg_ns, "demo HTML contains http:// reference"
            assert "https://" not in html_no_svg_ns, "demo HTML contains https:// reference"
            assert "<script" not in html.lower(), "demo HTML contains <script>"
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
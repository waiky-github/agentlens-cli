"""Tests for CI gate exit codes via subprocess."""

import os
import subprocess
import sys
from pathlib import Path


PYTHON = "/home/agentuser/.hermes/hermes-agent/venv/bin/python"
PKG_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = PKG_DIR / "examples"


def _run_audit_gate(input_file, fail_on="high", max_high=0):
    """Run `python -m agentlens_cli audit --input <file> --gate --fail-on <fail_on>`."""
    cmd = [
        PYTHON, "-m", "agentlens_cli", "audit",
        "--input", str(input_file),
        "--gate",
        "--fail-on", fail_on,
        "--max-high", str(max_high),
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


class TestGateExitCodes:
    """CI gate: returncode 1 for shadow sample, returncode 0 for v2 sample."""

    def test_shadow_gate_fails_on_high(self):
        """shadow_agent_events.jsonl has high-severity findings → gate should fail."""
        proc = _run_audit_gate(
            EXAMPLES_DIR / "shadow_agent_events.jsonl",
            fail_on="high",
            max_high=0,
        )
        assert proc.returncode == 1, (
            f"expected returncode=1 for shadow gate, got {proc.returncode}\n"
            f"stderr: {proc.stderr}\nstdout: {proc.stdout[:500]}"
        )

    def test_v2_compliance_gate_passes(self):
        """multi_agent_task_events_v2.jsonl has no high-severity findings → gate passes."""
        proc = _run_audit_gate(
            EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl",
            fail_on="high",
            max_high=0,
        )
        assert proc.returncode == 0, (
            f"expected returncode=0 for v2 gate, got {proc.returncode}\n"
            f"stderr: {proc.stderr}\nstdout: {proc.stdout[:500]}"
        )

    def test_compliance_gate_fails_on_high(self):
        """compliance_violations.jsonl has high-severity findings → gate should fail."""
        proc = _run_audit_gate(
            EXAMPLES_DIR / "compliance_violations.jsonl",
            fail_on="high",
            max_high=0,
        )
        assert proc.returncode == 1, (
            f"expected returncode=1 for compliance gate, got {proc.returncode}\n"
            f"stderr: {proc.stderr}\nstdout: {proc.stdout[:500]}"
        )

    def test_approval_bypass_gate_fails_on_high(self):
        """approval_bypass.json has high-severity findings → gate should fail."""
        proc = _run_audit_gate(
            EXAMPLES_DIR / "approval_bypass.json",
            fail_on="high",
            max_high=0,
        )
        assert proc.returncode == 1, (
            f"expected returncode=1 for approval_bypass gate, got {proc.returncode}\n"
            f"stderr: {proc.stderr}\nstdout: {proc.stdout[:500]}"
        )

    def test_gate_fail_on_medium(self):
        """v2 has medium findings, fail-on=medium should fail with max-medium=0."""
        cmd = [
            PYTHON, "-m", "agentlens_cli", "audit",
            "--input", str(EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl"),
            "--gate",
            "--fail-on", "medium",
            "--max-high", "100",
            "--max-medium", "0",
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PKG_DIR)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PKG_DIR),
            env=env,
        )
        assert proc.returncode == 1, (
            f"expected returncode=1 for medium gate, got {proc.returncode}\n"
            f"stderr: {proc.stderr}\nstdout: {proc.stdout[:500]}"
        )
"""Tests for the diff subcommand: same-file → all-zero deltas, cross-file → changes."""

import os
import subprocess
import sys
from pathlib import Path


PYTHON = "/home/agentuser/.hermes/hermes-agent/venv/bin/python"
PKG_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = PKG_DIR / "examples"


def _run_diff(baseline, current, output_format="json"):
    """Run `python -m agentlens_cli diff -b <baseline> -c <current> --format <fmt>`."""
    cmd = [
        PYTHON, "-m", "agentlens_cli", "diff",
        "--baseline", str(baseline),
        "--current", str(current),
        "--format", output_format,
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


class TestDiffSameFile:
    """Diff of same file → all deltas should be 0."""

    def test_same_file_deltas_zero(self):
        import json
        f = EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl"
        proc = _run_diff(f, f)
        assert proc.returncode == 0, f"diff failed: {proc.stderr}"
        result = json.loads(proc.stdout)
        deltas = result["deltas"]
        assert deltas["events_loaded"] == 0, f"events_loaded delta: {deltas['events_loaded']}"
        assert deltas["total_cost"] == 0, f"total_cost delta: {deltas['total_cost']}"
        assert deltas["findings_total"] == 0, f"findings_total delta: {deltas['findings_total']}"
        assert deltas["findings_high"] == 0
        assert deltas["findings_medium"] == 0
        assert deltas["closure_rate"] == 0, f"closure_rate delta: {deltas['closure_rate']}"

    def test_same_file_baseline_current_equal(self):
        import json
        f = EXAMPLES_DIR / "shadow_agent_events.jsonl"
        proc = _run_diff(f, f)
        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        assert result["baseline"]["events_loaded"] == result["current"]["events_loaded"]
        assert result["baseline"]["total_cost"] == result["current"]["total_cost"]
        assert result["baseline"]["closure_rate"] == result["current"]["closure_rate"]


class TestDiffCrossFile:
    """Diff of different files → deltas should show changes."""

    def test_v2_vs_shadow_deltas_nonzero(self):
        """v2 (20 events, full pipeline) vs shadow (7 events, violations) → deltas differ."""
        import json
        proc = _run_diff(
            EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl",
            EXAMPLES_DIR / "shadow_agent_events.jsonl",
        )
        assert proc.returncode == 0, f"diff failed: {proc.stderr}"
        result = json.loads(proc.stdout)
        deltas = result["deltas"]

        # events_loaded differs
        assert deltas["events_loaded"] != 0, f"events_loaded delta should be nonzero: {deltas['events_loaded']}"

        # findings_total will differ (shadow has more high findings)
        assert deltas["findings_total"] != 0, (
            f"findings_total delta should be nonzero: {deltas['findings_total']}"
        )

    def test_v2_vs_shadow_closure_differs(self):
        import json
        proc = _run_diff(
            EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl",
            EXAMPLES_DIR / "shadow_agent_events.jsonl",
        )
        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        # v2 has closure_rate=1.0, shadow should be different
        assert result["baseline"]["closure_rate"] != result["current"]["closure_rate"], (
            f"closure rates should differ: baseline={result['baseline']['closure_rate']}, "
            f"current={result['current']['closure_rate']}"
        )

    def test_compliance_vs_shadow_deltas_nonzero(self):
        import json
        proc = _run_diff(
            EXAMPLES_DIR / "compliance_violations.jsonl",
            EXAMPLES_DIR / "shadow_agent_events.jsonl",
        )
        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        deltas = result["deltas"]
        assert deltas["events_loaded"] != 0
        assert deltas["findings_total"] != 0

    def test_diff_html_format(self):
        """Diff with --format html produces valid HTML."""
        proc = _run_diff(
            EXAMPLES_DIR / "multi_agent_task_events_v2.jsonl",
            EXAMPLES_DIR / "shadow_agent_events.jsonl",
            output_format="html",
        )
        assert proc.returncode == 0
        html = proc.stdout
        assert "<!DOCTYPE html>" in html
        assert "AgentLens" in html
        assert "基线" in html or "Baseline" in html
        # No external resources
        assert "http://" not in html
        assert "https://" not in html
        assert "<script" not in html.lower()
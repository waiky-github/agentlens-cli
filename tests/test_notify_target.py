"""Regression tests for notify.py feishu target handling.

2026-09-16: `_send_feishu` accepted a `target` argument but hard-coded
`-t feishu` in the hermes send command, so configured targets were silently
ignored and notifications went to the home channel (which, under systemd,
resolves to a different chat than the interactive session). Also, the legacy
fallback path in `send_notify` now honours AGENTLENS_FEISHU_TARGET.
"""

import os
from unittest import mock

from agentlens_cli import notify


def _fake_run(cmd, capture_output=True, text=True, timeout=30):
    """Record the hermes send command; simulate a successful send."""
    assert cmd[0] == "hermes" and cmd[1] == "send", f"unexpected cmd: {cmd}"
    return mock.Mock(returncode=0, stdout="sent\n", stderr="")


def test_send_feishu_explicit_target_used():
    """Configured feishu target must appear as -t feishu:<target>."""
    with mock.patch("subprocess.run", side_effect=_fake_run) as m:
        result = notify._send_feishu(
            "oc_abc123", "subject", "body body body", None
        )
    assert result["status"] == "ok"
    cmd = m.call_args[0][0]
    assert cmd[cmd.index("-t") + 1] == "feishu:oc_abc123"


def test_send_feishu_empty_target_uses_home_channel():
    """Empty target must fall back to bare 'feishu' (home channel)."""
    with mock.patch("subprocess.run", side_effect=_fake_run) as m:
        result = notify._send_feishu("", "subject", "body", None)
    assert result["status"] == "ok"
    cmd = m.call_args[0][0]
    assert cmd[cmd.index("-t") + 1] == "feishu"


def test_legacy_fallback_uses_env_target():
    """send_notify legacy fallback must use AGENTLENS_FEISHU_TARGET."""
    with mock.patch("subprocess.run", side_effect=_fake_run) as m:
        with mock.patch.dict(
            os.environ,
            {"AGENTLENS_FEISHU_TARGET": "feishu:oc_xyz789"},
            clear=False,
        ):
            results = notify.send_notify("subject", "body body body")
    assert results[0]["status"] == "ok"
    cmd = m.call_args[0][0]
    assert cmd[cmd.index("-t") + 1] == "feishu:oc_xyz789"


def test_legacy_fallback_default_target_home_channel():
    """Without AGENTLENS_FEISHU_TARGET the fallback keeps bare 'feishu'."""
    with mock.patch("subprocess.run", side_effect=_fake_run) as m:
        with mock.patch.dict(os.environ, {}, clear=True):
            results = notify.send_notify("subject", "body body body")
    assert results[0]["status"] == "ok"
    cmd = m.call_args[0][0]
    assert cmd[cmd.index("-t") + 1] == "feishu"

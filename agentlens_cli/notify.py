"""Notification channel dispatch for AgentLens audit alerts.

Supports multiple channels: feishu (via hermes send), webhook (HTTP POST),
and arbitrary shell commands. Configuration is read from
notify-config.json in the report directory.
"""

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


def _load_config(report_dir: Optional[Path] = None) -> dict:
    """Load notify-config.json from the report directory.

    Returns a dict with keys: enabled (bool), channels (list of dict).
    Returns {"enabled": False, "channels": []} if no config file exists.
    """
    if report_dir is None:
        report_dir = Path(
            os.environ.get(
                "AGENTLENS_REPORT_DIR",
                os.path.expanduser("~/.hermes/agentlens-reports"),
            )
        )
    config_path = report_dir / "notify-config.json"
    if not config_path.is_file():
        return {"enabled": False, "channels": []}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"enabled": False, "channels": []}
    if not isinstance(data, dict):
        return {"enabled": False, "channels": []}
    return data


def _send_feishu(target: str, subject: str, body: str, token_cmd: Optional[str] = None) -> dict:
    """Send notification via feishu (hermes send)."""
    if token_cmd:
        try:
            token = subprocess.run(
                token_cmd, shell=True, capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except Exception:
            token = ""
    else:
        token = ""

    # hermes send: message text via positional arg, -s for subject line.
    # -f expects a file path; body here is raw text, so pass it positionally.
    cmd = ["hermes", "send", "-t", "feishu", "-s", subject, body]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            return {"channel": "feishu", "target": target, "status": "ok"}
        else:
            return {"channel": "feishu", "target": target, "status": "error", "detail": proc.stderr.strip()}
    except Exception as e:
        return {"channel": "feishu", "target": target, "status": "error", "detail": str(e)}


def _send_webhook(url: str, subject: str, body: str, secret: Optional[str] = None) -> dict:
    """Send notification via HTTP webhook POST."""
    import urllib.request

    payload = json.dumps({"subject": subject, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AgentLens-Notify/1.0",
        },
        method="POST",
    )
    if secret:
        req.add_header("Authorization", f"Bearer {secret}")
    try:
        urllib.request.urlopen(req, timeout=15)
        return {"channel": "webhook", "url": url, "status": "ok"}
    except Exception as e:
        return {"channel": "webhook", "url": url, "status": "error", "detail": str(e)}


def _send_command(cmd_template: str, subject: str, body: str) -> dict:
    """Send notification via arbitrary shell command with {subject}/{body} placeholders."""
    cmd = cmd_template.replace("{subject}", shlex.quote(subject)).replace("{body}", shlex.quote(body))
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            return {"channel": "command", "cmd": cmd_template, "status": "ok"}
        else:
            return {"channel": "command", "cmd": cmd_template, "status": "error", "detail": proc.stderr.strip()}
    except Exception as e:
        return {"channel": "command", "cmd": cmd_template, "status": "error", "detail": str(e)}


def send_notify(subject: str, body: str, config: Optional[dict] = None, report_dir: Optional[Path] = None) -> list[dict]:
    """Send notification via all configured channels.

    If no config is provided, loads from notify-config.json in report_dir.
    Falls back to the legacy `hermes send -t feishu` behavior when no config exists.

    Returns a list of result dicts, one per channel.
    """
    if config is None:
        config = _load_config(report_dir)

    if not config.get("enabled", False) or not config.get("channels"):
        # Legacy fallback: hermes send -t feishu
        try:
            proc = subprocess.run(
                ["hermes", "send", "-t", "feishu", "-s", subject, body],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                return [{"channel": "feishu", "status": "ok", "note": "legacy fallback"}]
            else:
                return [{"channel": "feishu", "status": "error", "detail": proc.stderr.strip(), "note": "legacy fallback"}]
        except Exception as e:
            return [{"channel": "feishu", "status": "error", "detail": str(e), "note": "legacy fallback"}]

    results = []
    for ch in config["channels"]:
        ch_type = ch.get("type", "")
        try:
            if ch_type == "feishu":
                results.append(_send_feishu(
                    ch.get("target", ""), subject, body,
                    ch.get("token_cmd"),
                ))
            elif ch_type == "webhook":
                results.append(_send_webhook(
                    ch.get("url", ""), subject, body,
                    ch.get("secret"),
                ))
            elif ch_type == "command":
                results.append(_send_command(
                    ch.get("cmd", ""), subject, body,
                ))
            else:
                results.append({"channel": ch_type, "status": "error", "detail": f"unknown channel type: {ch_type}"})
        except Exception as e:
            results.append({"channel": ch_type, "status": "error", "detail": str(e)})

    return results


def get_notify_config(report_dir: Optional[Path] = None) -> dict:
    """Return the current notify configuration (safe for API exposure).

    Masks sensitive fields like webhook secrets and token_cmd arguments.
    """
    config = _load_config(report_dir)
    if not config.get("channels"):
        return config
    safe_channels = []
    for ch in config["channels"]:
        sc = dict(ch)
        if "secret" in sc:
            sc["secret"] = "***" if sc["secret"] else ""
        if "token_cmd" in sc and sc["token_cmd"]:
            sc["token_cmd"] = "*** (masked)"
        if "url" in sc and "webhook" in sc.get("url", ""):
            # Mask webhook path
            sc["url"] = sc["url"][:30] + "***" if len(sc["url"]) > 30 else sc["url"]
        safe_channels.append(sc)
    return {"enabled": config.get("enabled", False), "channels": safe_channels}


def save_notify_config(config: dict, report_dir: Optional[Path] = None) -> bool:
    """Save notify configuration to notify-config.json.

    Creates the file with 600 permissions (owner read/write only).
    """
    if report_dir is None:
        report_dir = Path(
            os.environ.get(
                "AGENTLENS_REPORT_DIR",
                os.path.expanduser("~/.hermes/agentlens-reports"),
            )
        )
    config_path = report_dir / "notify-config.json"
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = config_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, config_path)
        return True
    except OSError:
        return False
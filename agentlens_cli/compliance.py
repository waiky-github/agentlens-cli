"""Compliance audit: decision authority boundary checks per 网信办《智能体规范应用与创新发展实施意见》(2026-05) Article 6.

Checks:
  1. USER_ONLY_VIOLATION — agent executes a USER_ONLY action (always violates)
  2. HIGH_RISK_AUTONOMOUS_DECISION — L3 action executed without any user approval/authorization
  3. MISSING_USER_AUTHORIZATION — USER_AUTHORIZED action executed without matching approval
  4. MISSING_INFORMED_CONSENT — AGENT_AUTONOMOUS high-risk action without disclosure
"""

from .config import (
    USER_ONLY_ACTIONS,
    USER_AUTHORIZED_ACTIONS,
    AGENT_AUTONOMOUS_ACTIONS,
    ACTION_RISK_LEVELS,
)


def _action_name(evt: dict) -> str:
    """Extract the action/tool name from an event."""
    payload = evt.get("payload", {}) or {}
    # Check action_executed payload
    action = payload.get("action", "")
    if action:
        return action.lower()
    # Check tool_invocation payload
    tool = payload.get("tool", "")
    if tool:
        return tool.lower()
    return ""


def _get_agent(evt: dict) -> str:
    """Extract the agent identifier from an event."""
    payload = evt.get("payload", {}) or {}
    for field in ("from", "agent", "source"):
        val = payload.get(field)
        if val:
            return val
    return evt.get("source", "")


def _classify_action(action: str) -> str:
    """Classify an action name into USER_ONLY, USER_AUTHORIZED, AGENT_AUTONOMOUS, or 'unknown'.
    
    Uses fuzzy matching: checks if the action contains or is contained by any known action.
    """
    action_lower = action.lower()
    
    # Check USER_ONLY first (highest priority)
    for known in USER_ONLY_ACTIONS:
        if known in action_lower or action_lower in known:
            return "USER_ONLY"
    
    # Check USER_AUTHORIZED
    for known in USER_AUTHORIZED_ACTIONS:
        if known in action_lower or action_lower in known:
            return "USER_AUTHORIZED"
    
    # Check AGENT_AUTONOMOUS
    for known in AGENT_AUTONOMOUS_ACTIONS:
        if known in action_lower or action_lower in known:
            return "AGENT_AUTONOMOUS"
    
    return "unknown"


def _get_risk_level(action: str) -> str:
    """Get the risk level (L1/L2/L3) for an action."""
    action_lower = action.lower()
    for known, level in ACTION_RISK_LEVELS.items():
        if known in action_lower or action_lower in known:
            return level
    return "L1"


def _has_disclosure(evt: dict) -> bool:
    """Check if an event has user-visible disclosure (message_summary, evidence_ref, or notification)."""
    if evt.get("message_summary"):
        return True
    if evt.get("evidence_ref"):
        return True
    return False


def audit_compliance(events: list[dict]) -> dict:
    """Audit decision authority compliance for the given events.
    
    Returns a dict with 'findings' list and 'summary' string.
    """
    findings = []
    sorted_events = sorted(events, key=lambda e: e.get("timestamp", ""))
    
    # Check if there's an approval stream at all
    has_approval_stream = any(evt.get("type") == "approval" for evt in events)
    
    # Collect approval events and their references
    approval_refs = set()
    for evt in events:
        if evt.get("type") == "approval":
            approval_refs.add(evt.get("event_id", ""))
            payload = evt.get("payload", {}) or {}
            appr_ref = payload.get("approval_ref", "")
            if appr_ref:
                approval_refs.add(appr_ref)
    
    # Track which actions were seen (deduplicate per action+agent)
    seen_violations = set()
    
    for evt in sorted_events:
        etype = evt.get("type", "")
        if etype not in ("action_executed", "tool_invocation", "task_dispatch"):
            continue
        
        action = _action_name(evt)
        if not action:
            continue
        
        # Skip "request_*" actions — they are approval requests, not the actual risky action
        if action.startswith("request_"):
            continue
        
        event_id = evt.get("event_id", "")
        agent = _get_agent(evt)
        classification = _classify_action(action)
        risk_level = _get_risk_level(action)
        
        payload = evt.get("payload", {}) or {}
        approval_recorded = payload.get("approval_recorded", False)
        approval_ref = payload.get("approval_ref", "")
        approval_required = payload.get("approval_required", "")
        
        # Check if this action has a matching approval in the stream
        has_approval = False
        if approval_recorded:
            has_approval = True
        if approval_ref and approval_ref in approval_refs:
            has_approval = True
        # Also check if any approval event references this action's event_id
        for appr in events:
            if appr.get("type") != "approval":
                continue
            appr_payload = appr.get("payload", {}) or {}
            if appr_payload.get("approval_ref") == event_id:
                has_approval = True
                break
            # Check if approval mentions the same action name
            appr_action = appr_payload.get("action", "")
            if appr_action and (action in appr_action.lower() or appr_action.lower() in action):
                has_approval = True
                break
        
        # ── Detection a: USER_ONLY_VIOLATION ──
        if classification == "USER_ONLY":
            dedup_key = ("USER_ONLY_VIOLATION", action, agent)
            if dedup_key not in seen_violations:
                seen_violations.add(dedup_key)
                findings.append({
                    "severity": "high",
                    "title": "USER_ONLY_VIOLATION",
                    "evidence_refs": [event_id],
                    "recommendation": (
                        f"action '{action}' is classified as USER_ONLY and must never be "
                        f"executed by an agent; this action requires direct user decision"
                    ),
                    "detail": (
                        f"Agent '{agent}' executed action '{action}' which is classified as "
                        f"USER_ONLY — only the user may make this decision. "
                        f"Per 实施意见 Article 6, agents must not exceed authorization boundaries."
                    ),
                    "action": action,
                    "agent": agent,
                    "risk_level": risk_level,
                })
            continue
        
        # ── Detection b: HIGH_RISK_AUTONOMOUS_DECISION ──
        if risk_level == "L3" and not has_approval:
            if not has_approval_stream:
                # No approval stream at all → downgrade to info, emit once
                if "AUDIT_GAP_NO_APPROVAL_STREAM" not in seen_violations:
                    seen_violations.add("AUDIT_GAP_NO_APPROVAL_STREAM")
                    findings.append({
                        "severity": "info",
                        "title": "AUDIT_GAP_NO_APPROVAL_STREAM",
                        "evidence_refs": [],
                        "recommendation": (
                            "event stream contains no approval events; enable approval "
                            "logging or attach an approval trail before verifying L3 "
                            "decision authority compliance"
                        ),
                        "detail": (
                            "No approval-type event was found in this event stream, so "
                            "HIGH_RISK_AUTONOMOUS_DECISION checks are skipped to avoid "
                            "false positives. Connect an approval/audit stream to enable."
                        ),
                    })
                continue
            dedup_key = ("HIGH_RISK_AUTONOMOUS_DECISION", action, agent)
            if dedup_key not in seen_violations:
                seen_violations.add(dedup_key)
                findings.append({
                    "severity": "high",
                    "title": "HIGH_RISK_AUTONOMOUS_DECISION",
                    "evidence_refs": [event_id],
                    "recommendation": (
                        f"L3 risk action '{action}' was executed by '{agent}' without "
                        f"any user approval or authorization record; require user "
                        f"authorization before L3 actions"
                    ),
                    "detail": (
                        f"Agent '{agent}' executed L3 high-risk action '{action}' "
                        f"without a matching approval event. Per 实施意见 Article 6, "
                        f"high-risk decisions must have user authorization on record."
                    ),
                    "action": action,
                    "agent": agent,
                    "risk_level": risk_level,
                })
            continue
        
        # ── Detection c: MISSING_USER_AUTHORIZATION ──
        if classification == "USER_AUTHORIZED" and not has_approval:
            if not has_approval_stream:
                # Already handled above
                continue
            dedup_key = ("MISSING_USER_AUTHORIZATION", action, agent)
            if dedup_key not in seen_violations:
                seen_violations.add(dedup_key)
                findings.append({
                    "severity": "medium",
                    "title": "MISSING_USER_AUTHORIZATION",
                    "evidence_refs": [event_id],
                    "recommendation": (
                        f"action '{action}' requires user authorization but no "
                        f"approval event was found for this execution"
                    ),
                    "detail": (
                        f"Agent '{agent}' executed USER_AUTHORIZED action '{action}' "
                        f"without a matching approval event. Per 实施意见 Article 6, "
                        f"actions that require user authorization must have documented "
                        f"approval before execution."
                    ),
                    "action": action,
                    "agent": agent,
                    "risk_level": risk_level,
                })
            continue
        
        # ── Detection d: MISSING_INFORMED_CONSENT ──
        if classification == "AGENT_AUTONOMOUS" and risk_level in ("L2", "L3"):
            has_disclosure = _has_disclosure(evt)
            if not has_disclosure:
                dedup_key = ("MISSING_INFORMED_CONSENT", action, agent)
                if dedup_key not in seen_violations:
                    seen_violations.add(dedup_key)
                    findings.append({
                        "severity": "info",
                        "title": "MISSING_INFORMED_CONSENT",
                        "evidence_refs": [event_id],
                        "recommendation": (
                            f"AGENT_AUTONOMOUS {risk_level} action '{action}' lacks "
                            f"user-visible disclosure (message_summary or evidence_ref); "
                            f"add disclosure to satisfy informed consent requirement"
                        ),
                        "detail": (
                            f"Agent '{agent}' executed {risk_level} autonomous action "
                            f"'{action}' without a message_summary or evidence_ref. "
                            f"Per 实施意见 Article 6, users have the right to be informed "
                            f"of autonomous agent decisions."
                        ),
                        "action": action,
                        "agent": agent,
                        "risk_level": risk_level,
                    })
    
    # Build summary
    high_count = sum(1 for f in findings if f["severity"] == "high")
    medium_count = sum(1 for f in findings if f["severity"] == "medium")
    low_count = sum(1 for f in findings if f["severity"] == "low")
    info_count = sum(1 for f in findings if f["severity"] == "info")
    
    summary_parts = []
    if high_count:
        summary_parts.append(f"{high_count} high")
    if medium_count:
        summary_parts.append(f"{medium_count} medium")
    if low_count:
        summary_parts.append(f"{low_count} low")
    if info_count:
        summary_parts.append(f"{info_count} info")
    
    summary = f"{len(findings)} findings: {', '.join(summary_parts)}" if summary_parts else "no findings"
    
    return {
        "findings": findings,
        "summary": summary,
        "decision_boundary_model": {
            "user_only_actions": USER_ONLY_ACTIONS,
            "user_authorized_actions": USER_AUTHORIZED_ACTIONS,
            "agent_autonomous_action_count": len(AGENT_AUTONOMOUS_ACTIONS),
        },
    }
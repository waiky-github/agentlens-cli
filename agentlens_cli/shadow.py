"""Shadow agent detection: identify unregistered agents, unauthorized tool calls, and privilege boundary violations.

Implements the three detection categories required by 网信办《智能体规范应用与创新发展实施意见》(2026-05):
  1. SHADOW_AGENT_DETECTED — agent identifier not in known_agents whitelist
  2. UNAUTHORIZED_TOOL_CALL — dangerous tool invoked without matching approval event
  3. PRIVILEGE_BOUNDARY_VIOLATION — agent executes tool outside its role's permitted set
"""

from .config import (
    DEFAULT_KNOWN_AGENTS,
    DEFAULT_DANGEROUS_TOOLS,
    AGENT_ROLE_TOOLS,
)


def _infer_role(name: str) -> str:
    """Infer agent role from its name (same logic as graph.py:_infer_role)."""
    name_lower = name.lower()
    if "leader" in name_lower or "admin" in name_lower or "main" in name_lower or "manager" in name_lower:
        return "leader"
    if "collector" in name_lower:
        return "collector"
    if "graph" in name_lower or "builder" in name_lower:
        return "builder"
    if "decision" in name_lower or "auditor" in name_lower:
        return "auditor"
    if "cost" in name_lower or "analyst" in name_lower:
        return "analyst"
    if "evidence" in name_lower or "verifier" in name_lower:
        return "verifier"
    return "worker"


def _is_dangerous(tool: str, dangerous_tools: list) -> bool:
    """Check if a tool name matches any dangerous tool pattern (case-insensitive)."""
    tool_lower = tool.lower()
    for dt in dangerous_tools:
        if dt.lower() in tool_lower:
            return True
    return False


def _agent_from_event(evt: dict) -> str:
    """Extract the agent identifier from an event, checking multiple fields."""
    payload = evt.get("payload", {}) or {}
    for field in ("agent", "source", "from"):
        val = payload.get(field)
        if val:
            return val
    # Also check top-level source
    src = evt.get("source", "")
    if src:
        return src
    return ""


def _detect_shadow_agents(events: list, known_agents: set) -> list:
    """Detect agent identifiers that appear in events but are not in the known_agents whitelist."""
    findings = []
    seen_shadow = set()

    for evt in events:
        agent = _agent_from_event(evt)
        if not agent:
            continue
        if agent in known_agents or agent in seen_shadow:
            continue

        seen_shadow.add(agent)
        findings.append({
            "severity": "high",
            "title": "SHADOW_AGENT_DETECTED",
            "evidence_refs": [evt.get("event_id", "")],
            "recommendation": (
                f"agent '{agent}' is not in the registered known_agents whitelist; "
                f"register it or investigate this activity"
            ),
            "detail": (
                f"Unregistered agent '{agent}' appeared in event "
                f"'{evt.get('event_id')}' of type '{evt.get('type')}'. "
                f"This may indicate an unauthorized agent operating in the system."
            ),
            "agent": agent,
        })

    return findings


def _detect_unauthorized_tools(events: list, dangerous_tools: list) -> list:
    """Detect dangerous tool invocations that lack a matching approval event."""
    # If the stream has NO approval events at all, the source did not capture an
    # approval flow. Flagging every dangerous call as unauthorized would be mass
    # false positives — downgrade to a single info finding instead.
    has_approval_stream = any(evt.get("type") == "approval" for evt in events)
    if not has_approval_stream:
        return [{
            "severity": "info",
            "title": "AUDIT_GAP_NO_APPROVAL_STREAM",
            "evidence_refs": [],
            "recommendation": (
                "event stream contains no approval events; enable approval "
                "logging or attach an approval trail before treating dangerous "
                "tool calls as authorized"
            ),
            "detail": (
                "No approval-type event was found in this event stream, so "
                "unauthorized tool call verification is skipped to avoid false "
                "positives. Connect an approval/audit stream to enable this check."
            ),
        }]
    # Collect all approval events and their references
    approval_refs = set()
    for evt in events:
        if evt.get("type") == "approval":
            approval_refs.add(evt.get("event_id", ""))
            payload = evt.get("payload", {}) or {}
            appr_ref = payload.get("approval_ref", "")
            if appr_ref:
                approval_refs.add(appr_ref)

    findings = []
    for evt in events:
        etype = evt.get("type", "")
        # Only check tool_invocation events for unauthorized tool calls.
        # action_executed events are handled by the decision layer.
        if etype != "tool_invocation":
            continue

        payload = evt.get("payload", {}) or {}
        tool = payload.get("tool", "")
        if not tool or not _is_dangerous(tool, dangerous_tools):
            continue

        # Check if this invocation has an associated approval
        approval_recorded = payload.get("approval_recorded", False)
        approval_ref = payload.get("approval_ref", "")
        approval_required = payload.get("approval_required", "")

        # If approval_required is set and approval_recorded is False, skip —
        # this is already handled by decision.py's APPROVAL_BYPASS_CONFIRMED.
        # We're looking for dangerous tool calls that have NO approval mechanism at all.
        if approval_required and not approval_recorded:
            continue

        # If there's an approval_ref that resolves, it's authorized
        if approval_ref and approval_ref in approval_refs:
            continue

        # If approval_recorded is True, it's authorized
        if approval_recorded:
            continue

        # Tool invocation without any approval — check if there's a nearby approval
        # that explicitly covers this tool
        has_approval = False
        evt_id = evt.get("event_id", "")
        for appr in events:
            if appr.get("type") != "approval":
                continue
            appr_payload = appr.get("payload", {}) or {}
            # Check if approval references this event
            if appr_payload.get("approval_ref") == evt_id:
                has_approval = True
                break
            # Check if approval mentions the same tool/action
            if appr_payload.get("action", "").lower() == tool.lower():
                has_approval = True
                break

        if has_approval:
            continue

        agent = _agent_from_event(evt)
        findings.append({
            "severity": "high",
            "title": "UNAUTHORIZED_TOOL_CALL",
            "evidence_refs": [evt.get("event_id", "")],
            "recommendation": (
                f"dangerous tool '{tool}' was invoked by '{agent}' without "
                f"a matching approval event; require L3 approval for all "
                f"dangerous tool invocations"
            ),
            "detail": (
                f"Dangerous tool '{tool}' was invoked by '{agent}' in event "
                f"'{evt.get('event_id')}' without any corresponding approval "
                f"event in the stream. All dangerous tool calls must be "
                f"preceded by an explicit approval."
            ),
            "tool": tool,
            "agent": agent,
        })

    return findings


def _detect_privilege_violations(events: list, known_agents: set, dangerous_tools: list) -> list:
    """Detect agents executing tools that are outside their role's permitted set."""
    findings = []

    for evt in events:
        etype = evt.get("type", "")
        # Only check tool_invocation events for privilege violations.
        # action_executed events are handled by the decision layer.
        if etype != "tool_invocation":
            continue

        payload = evt.get("payload", {}) or {}
        tool = payload.get("tool", "")
        if not tool:
            continue

        agent = _agent_from_event(evt)
        if not agent:
            continue

        role = _infer_role(agent)
        permitted = AGENT_ROLE_TOOLS.get(role)

        # Empty list means all tools allowed (leader/admin)
        if permitted is not None and len(permitted) == 0:
            continue

        # Role not in mapping — treat as worker
        if permitted is None:
            permitted = AGENT_ROLE_TOOLS.get("worker", [])

        # Check if the tool is permitted for this role
        tool_lower = tool.lower()
        if any(p.lower() == tool_lower for p in permitted):
            continue

        # Only flag if the tool is dangerous OR the tool is clearly outside
        # the role's domain (e.g., a collector doing a write/delete operation)
        is_dangerous = _is_dangerous(tool, dangerous_tools)

        # For non-dangerous tools, only flag if the tool is clearly a
        # write/delete/modify operation (privilege escalation)
        if not is_dangerous:
            write_keywords = ("write", "delete", "modify", "update", "create",
                              "deploy", "config", "apply", "set", "change", "override")
            if not any(kw in tool_lower for kw in write_keywords):
                continue

        findings.append({
            "severity": "medium",
            "title": "PRIVILEGE_BOUNDARY_VIOLATION",
            "evidence_refs": [evt.get("event_id", "")],
            "recommendation": (
                f"agent '{agent}' (role: {role}) invoked tool '{tool}' which is "
                f"outside its permitted tool set; review the agent's permissions "
                f"or the tool invocation"
            ),
            "detail": (
                f"Agent '{agent}' with inferred role '{role}' executed tool "
                f"'{tool}' which is not in the permitted set for this role "
                f"({permitted}). This may indicate privilege escalation or "
                f"incorrect role assignment."
            ),
            "tool": tool,
            "agent": agent,
            "role": role,
        })

    return findings


def detect_shadow_agents(
    events: list,
    known_agents: list = None,
    dangerous_tools: list = None,
) -> list:
    """Run all three shadow agent detections and return a combined findings list.

    Args:
        events: List of normalized event dicts from the parser.
        known_agents: List of registered agent identifiers. Defaults to DEFAULT_KNOWN_AGENTS.
        dangerous_tools: List of dangerous tool names. Defaults to DEFAULT_DANGEROUS_TOOLS.

    Returns:
        List of finding dicts with severity, title, evidence_refs, recommendation, detail.
    """
    if known_agents is None:
        known_agents = DEFAULT_KNOWN_AGENTS
    if dangerous_tools is None:
        dangerous_tools = DEFAULT_DANGEROUS_TOOLS

    known_set = set(known_agents)

    findings = []
    findings.extend(_detect_shadow_agents(events, known_set))
    findings.extend(_detect_unauthorized_tools(events, dangerous_tools))
    findings.extend(_detect_privilege_violations(events, known_set, dangerous_tools))

    return findings
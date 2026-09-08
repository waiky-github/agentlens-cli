"""Decision audit: check dispatch rationale, approval chains, and approval bypass detection."""


def audit_decisions(events: list[dict]) -> dict:
    """Audit decision chains from events.

    Checks:
      1. task_dispatch has rationale/why
      2. High-risk action_executed has matching approval (L3 chain)
      3. Approval bypass detection → APPROVAL_BYPASS_CONFIRMED
    """
    sorted_events = sorted(events, key=lambda e: e.get("timestamp", ""))

    findings = []
    decision_chain = []
    step_counter = 0

    # Collect approvals indexed by what they approve
    approvals = {}  # approval_ref -> approval event
    action_executed_events = []

    for evt in sorted_events:
        etype = evt.get("type", "")
        payload = evt.get("payload", {}) or {}
        event_id = evt.get("event_id", "")
        evidence_ref = evt.get("evidence_ref", "")

        if etype == "approval":
            step_counter += 1
            decision_chain.append({
                "step": step_counter,
                "actor": payload.get("from", "unknown"),
                "action": payload.get("action", "approve"),
                "approval": payload.get("status", "approved"),
                "evidence_refs": [evidence_ref],
            })
            # Index by approval_ref
            approval_ref = payload.get("approval_ref", "")
            if approval_ref:
                approvals[approval_ref] = evt
            # Also index by own event_id
            approvals[event_id] = evt

        elif etype == "action_executed":
            action_executed_events.append(evt)
            step_counter += 1
            approval_required = payload.get("approval_required", "")
            approval_recorded = payload.get("approval_recorded", False)
            approval_ref = payload.get("approval_ref", "")

            decision_chain.append({
                "step": step_counter,
                "actor": payload.get("from", "unknown"),
                "action": payload.get("action", "unknown"),
                "approval": approval_required if approval_required else "auto",
                "evidence_refs": [evidence_ref],
            })

            # Check: is this a high-risk action that requires approval?
            # Skip "request" actions — they are approval requests, not the actual risky action
            if approval_required and approval_required.upper() in ("L3", "L2", "HIGH"):
                action_name = payload.get("action", "")
                requested_by = payload.get("requested_by", "")
                # A "request_*" action is an approval request, not the actual high-risk action.
                # The actual action (e.g. apply_high_risk_config) is what needs approval.
                if action_name.startswith("request_"):
                    # This is just a request — it's not the bypass itself
                    pass
                elif not approval_recorded and not approval_ref:
                    # No approval recorded at all → APPROVAL_BYPASS_CONFIRMED
                    findings.append({
                        "severity": "high",
                        "title": "APPROVAL_BYPASS_CONFIRMED",
                        "evidence_refs": [event_id],
                        "recommendation": (
                            f"high-risk action '{payload.get('action')}' requires "
                            f"{approval_required} approval; no approval event found"
                        ),
                        "detail": (
                            f"Action '{payload.get('action')}' by {payload.get('from')} "
                            f"requires {approval_required} approval but approval_recorded=false "
                            f"and no approval_ref"
                        ),
                        "est_impact": "regulatory/compliance violation; potential configuration drift",
                    })
                elif approval_ref and approval_ref not in approvals:
                    # Approval ref points to non-existent approval
                    findings.append({
                        "severity": "high",
                        "title": "APPROVAL_BYPASS_CONFIRMED",
                        "evidence_refs": [event_id],
                        "recommendation": (
                            f"approval_ref '{approval_ref}' does not resolve to any approval event"
                        ),
                        "detail": (
                            f"Action '{payload.get('action')}' references approval "
                            f"'{approval_ref}' which does not exist in the event stream"
                        ),
                        "est_impact": "regulatory/compliance violation; phantom approval reference",
                    })
                elif approval_ref and approval_ref in approvals:
                    # Verify the approval actually matches
                    appr = approvals[approval_ref]
                    appr_payload = appr.get("payload", {}) or {}
                    if appr_payload.get("status") != "approved":
                        findings.append({
                            "severity": "high",
                            "title": "APPROVAL_BYPASS_CONFIRMED",
                            "evidence_refs": [event_id, appr.get("event_id", "")],
                            "recommendation": (
                                f"approval exists but status is '{appr_payload.get('status')}', not 'approved'"
                            ),
                            "detail": (
                                f"Action references approval '{approval_ref}' which has status "
                                f"'{appr_payload.get('status')}'"
                            ),
                            "est_impact": "regulatory/compliance violation; unapproved high-risk action",
                        })
                    else:
                        # Valid L3 approval chain
                        findings.append({
                            "severity": "info",
                            "title": "L3 approval chain compliant",
                            "evidence_refs": [event_id, appr.get("event_id", "")],
                            "recommendation": "approval chain is intact; no action needed",
                            "detail": f"L3 approval by {appr_payload.get('from')} at {appr.get('timestamp')}",
                        })

        elif etype == "task_dispatch":
            step_counter += 1
            rationale = payload.get("rationale", "")
            decision_chain.append({
                "step": step_counter,
                "actor": payload.get("from", "unknown"),
                "action": f"dispatch to {payload.get('to', 'unknown')}",
                "approval": "auto",
                "rationale": rationale if rationale else None,
                "evidence_refs": [evidence_ref],
            })

            if not rationale:
                findings.append({
                    "severity": "medium",
                    "title": "task_dispatch missing rationale",
                    "evidence_refs": [event_id],
                    "recommendation": (
                        "every dispatch should include a 'why' (rationale) for auditability"
                    ),
                    "detail": (
                        f"Dispatch from {payload.get('from')} to {payload.get('to')} "
                        f"for task '{payload.get('task')}' has no rationale"
                    ),
                })

        elif etype == "task_split":
            step_counter += 1
            rationale = payload.get("rationale", "")
            decision_chain.append({
                "step": step_counter,
                "actor": payload.get("from", "unknown"),
                "action": "task_split",
                "approval": "auto",
                "rationale": rationale if rationale else None,
                "evidence_refs": [evidence_ref],
            })

            if not rationale:
                findings.append({
                    "severity": "medium",
                    "title": "task_split missing rationale",
                    "evidence_refs": [event_id],
                    "recommendation": "task decomposition should document why this split was chosen",
                    "detail": f"task_split by {payload.get('from')} has no rationale",
                })

    # Check for actions that explicitly signal approval bypass
    # (approval_required set but approval_recorded=false is the key signal)
    bypass_found = any(
        f.get("title") == "APPROVAL_BYPASS_CONFIRMED"
        for f in findings
    )

    summary_parts = []
    high_count = sum(1 for f in findings if f["severity"] == "high")
    medium_count = sum(1 for f in findings if f["severity"] == "medium")
    low_count = sum(1 for f in findings if f["severity"] == "low")
    info_count = sum(1 for f in findings if f["severity"] == "info")

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
        "audit_id": "audit-auto",
        "decision_chain": decision_chain,
        "findings": findings,
        "summary": summary,
        "approval_bypass_detected": bypass_found,
    }
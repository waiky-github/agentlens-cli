"""Evidence chain verification: check every claim/event is backed by reachable evidence."""


def verify_evidence(events: list[dict], findings: list[dict] = None) -> dict:
    """Verify evidence chain completeness for all events.

    Checks:
      1. Every event has an evidence_ref
      2. evidence_ref points to a real source (format check)
      3. Events with evidence_ref are counted as verified
      4. Claims/findings have evidence_refs that resolve to events
    """
    findings = findings or []

    # Build event_id index
    event_index = {}
    for evt in events:
        eid = evt.get("event_id", "")
        if eid:
            event_index[eid] = evt

    verified = 0
    unreachable = []
    missing_evidence = []

    total_claims = len(events)

    for evt in events:
        event_id = evt.get("event_id", "")
        evidence_ref = evt.get("evidence_ref", "")

        if not evidence_ref:
            missing_evidence.append({
                "event_id": event_id,
                "claim": evt.get("type", "unknown"),
                "reason": "no evidence_ref",
            })
            continue

        # Check evidence_ref format: should have at least "source:path" or similar
        if ":" not in evidence_ref and "/" not in evidence_ref:
            missing_evidence.append({
                "event_id": event_id,
                "claim": evt.get("type", "unknown"),
                "evidence_ref": evidence_ref,
                "reason": "evidence_ref format invalid",
            })
            continue

        verified += 1

    # Check findings have evidence_refs that resolve to real events
    for finding in findings:
        refs = finding.get("evidence_refs", [])
        if not refs:
            continue
        for ref in refs:
            if ref and ref not in event_index:
                # Don't double-count; just note
                unreachable.append({
                    "claim": finding.get("title", "unknown"),
                    "evidence_ref": ref,
                    "reason": "referenced event not found in stream",
                })

    completeness = round(verified / total_claims, 4) if total_claims > 0 else 0.0

    # Build evidence layer findings
    ev_findings = []
    if missing_evidence:
        ev_findings.append({
            "severity": "high",
            "title": "events missing evidence_ref",
            "evidence_refs": [m.get("event_id", "") for m in missing_evidence],
            "recommendation": "ensure every event carries a source reference (evidence_ref)",
            "detail": f"{len(missing_evidence)} events have no valid evidence_ref",
        })
    if unreachable:
        ev_findings.append({
            "severity": "medium",
            "title": "finding evidence_refs not resolvable",
            "evidence_refs": [u.get("evidence_ref", "") for u in unreachable],
            "recommendation": "verify that all evidence_refs point to events in the stream",
            "detail": f"{len(unreachable)} evidence references could not be resolved",
        })

    conclusion = (
        f"evidence chain complete: {verified}/{total_claims} events verified"
        if not missing_evidence
        else f"evidence chain incomplete: {len(missing_evidence)} events missing evidence_ref, {verified}/{total_claims} verified"
    )

    return {
        "verification_id": "verify-auto",
        "claims_checked": total_claims,
        "verified": verified,
        "unreachable": unreachable,
        "missing_evidence": missing_evidence,
        "completeness": completeness,
        "findings": ev_findings,
        "conclusion": conclusion,
    }
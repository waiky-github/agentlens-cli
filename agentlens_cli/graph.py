"""Collaboration graph builder: reconstruct task→decompose→dispatch→execute→summary chains."""

from collections import defaultdict


def build_graph(events: list[dict]) -> dict:
    """Build a collaboration graph from normalized events.

    Returns a dict with nodes, edges, metrics, and data_gaps.
    """
    sorted_events = sorted(events, key=lambda e: e.get("timestamp", ""))

    nodes = {}
    edges = []
    data_gaps = []

    # Track dispatched tasks for closure analysis
    # Key: (from, to) worker pair; value: list of task_ids
    dispatched_pairs = {}  # (from, to) -> [(task_id, event_id, task_name)]
    completed_pairs = set()  # (from, to) where from=worker who completed
    failed_pairs = set()
    retried_pairs = set()

    for evt in sorted_events:
        etype = evt.get("type", "")
        payload = evt.get("payload", {}) or {}
        event_id = evt.get("event_id", "")
        evidence_ref = evt.get("evidence_ref", "")

        # Collect nodes
        actor = payload.get("from")
        receiver = payload.get("to")
        agent_field = payload.get("agent")

        for name in (actor, receiver, agent_field):
            if name and name not in nodes:
                role = _infer_role(name)
                nodes[name] = {"id": name, "type": "agent", "role": role}

        # task_split → decomposition edges
        if etype == "task_split":
            plan = payload.get("plan", [])
            rationale = payload.get("rationale", "")
            if not rationale:
                data_gaps.append({
                    "event_id": event_id,
                    "reason": "task_split missing rationale/why",
                    "evidence_ref": evidence_ref,
                })
            for item in plan:
                if isinstance(item, dict):
                    edges.append({
                        "from": actor or "unknown",
                        "to": item.get("to", "unknown"),
                        "type": "task_dispatch",
                        "task_id": item.get("task", "unknown"),
                        "evidence_refs": [evidence_ref],
                        "timestamp": evt.get("timestamp"),
                    })

        # task_dispatch → directed edge
        elif etype == "task_dispatch":
            task_name = payload.get("task", "unknown")
            task_id = f"{actor or '?'}->{receiver or '?'}:{task_name}"
            pair_key = (actor or "?", receiver or "?")
            if pair_key not in dispatched_pairs:
                dispatched_pairs[pair_key] = []
            dispatched_pairs[pair_key].append({
                "task_id": task_id,
                "event_id": event_id,
                "task": task_name,
                "from": actor,
                "to": receiver,
            })
            edges.append({
                "from": actor or "unknown",
                "to": receiver or "unknown",
                "type": "task_dispatch",
                "task_id": task_id,
                "evidence_refs": [evidence_ref],
                "timestamp": evt.get("timestamp"),
            })

        # approval → approval edge
        elif etype == "approval":
            edges.append({
                "from": actor or "unknown",
                "to": receiver or "unknown",
                "type": "approval",
                "decision": payload.get("action", payload.get("status", "unknown")),
                "evidence_refs": [evidence_ref],
                "timestamp": evt.get("timestamp"),
            })

        # task_completion
        elif etype == "task_completion":
            task_name = payload.get("task", "unknown")
            task_id = f"{actor or '?'}->{receiver or '?'}:{task_name}"
            # Worker-based matching: completion flows from worker->leader, so
            # (from=worker, to=leader) maps to dispatch pair (leader, worker)
            pair_key = (receiver or "?", actor or "?")
            completed_pairs.add(pair_key)
            edges.append({
                "from": actor or "unknown",
                "to": receiver or "unknown",
                "type": "task_completion",
                "task_id": task_id,
                "evidence_refs": [evidence_ref],
                "timestamp": evt.get("timestamp"),
            })

        # task_failed
        elif etype == "task_failed":
            task_name = payload.get("task", "unknown")
            task_id = f"{actor or '?'}->{receiver or '?'}:{task_name}"
            pair_key = (receiver or "?", actor or "?")
            failed_pairs.add(pair_key)
            data_gaps.append({
                "event_id": event_id,
                "reason": f"task failed: {payload.get('reason', 'unknown')}",
                "evidence_ref": evidence_ref,
            })

        # task_retry
        elif etype == "task_retry":
            task_name = payload.get("task", "unknown")
            task_id = f"{actor or '?'}->{receiver or '?'}:{task_name}"
            pair_key = (actor or "?", receiver or "?")
            retried_pairs.add(pair_key)
            edges.append({
                "from": actor or "unknown",
                "to": receiver or "unknown",
                "type": "task_dispatch",
                "task_id": task_id,
                "evidence_refs": [evidence_ref],
                "timestamp": evt.get("timestamp"),
                "retry_of": payload.get("retry_of"),
            })

        # conflict_resolved → info_flow edge
        elif etype == "conflict_resolved":
            edges.append({
                "from": actor or "unknown",
                "to": "team",
                "type": "info_flow",
                "evidence_refs": [evidence_ref],
                "timestamp": evt.get("timestamp"),
                "decision": payload.get("decision", ""),
            })

    # Deduplicate edges
    seen_edge_keys = set()
    deduped_edges = []
    for edge in edges:
        key = (edge["from"], edge["to"], edge["type"], edge.get("task_id", ""))
        if key not in seen_edge_keys:
            seen_edge_keys.add(key)
            deduped_edges.append(edge)

    # Metrics: closure is based on (leader, worker) pairs
    total_dispatched = len(dispatched_pairs)
    closed_count = 0
    unclosed_tasks = []
    for pair_key, entries in dispatched_pairs.items():
        if pair_key in completed_pairs:
            closed_count += 1
        elif pair_key in failed_pairs and pair_key in retried_pairs:
            # Check if retried and then completed
            if pair_key in completed_pairs:
                closed_count += 1
            else:
                for e in entries:
                    unclosed_tasks.append(e["task_id"])
        else:
            for e in entries:
                unclosed_tasks.append(e["task_id"])

    closure_rate = round(closed_count / total_dispatched, 4) if total_dispatched > 0 else 0.0

    # Absent workers: dispatched to but never completed
    workers_seen = set()
    workers_completed = set()
    for pair_key in dispatched_pairs:
        workers_seen.add(pair_key[1])  # to=worker
    for pair_key in completed_pairs:
        # completed_pairs uses (receiver, actor) = (leader, worker) from completion
        workers_completed.add(pair_key[1])  # actor=worker
    absent_workers = [w for w in workers_seen if w and w not in workers_completed]

    # Build node list
    node_list = list(nodes.values())

    # Build findings for graph layer
    findings = []
    if unclosed_tasks:
        findings.append({
            "severity": "high",
            "title": "unclosed tasks detected",
            "evidence_refs": [],
            "recommendation": "ensure every dispatched task has a completion or failure event",
            "detail": f"unclosed tasks: {unclosed_tasks}",
        })
    if absent_workers:
        findings.append({
            "severity": "high",
            "title": "absent workers: dispatched but no completion",
            "evidence_refs": [],
            "recommendation": "check if workers are online or tasks were reassigned",
            "detail": f"absent workers: {absent_workers}",
        })
    if data_gaps:
        gaps_without_failures = [g for g in data_gaps if "task failed" not in g.get("reason", "")]
        if gaps_without_failures:
            findings.append({
                "severity": "medium",
                "title": "data gaps in collaboration graph",
                "evidence_refs": [g.get("evidence_ref", "") for g in gaps_without_failures],
                "recommendation": "review source events for missing fields or unmapped types",
                "detail": str(gaps_without_failures),
            })

    return {
        "graph_id": "g-auto",
        "nodes": node_list,
        "edges": deduped_edges,
        "data_gaps": data_gaps,
        "metrics": {
            "total_dispatched": total_dispatched,
            "closed_count": closed_count,
            "closure_rate": closure_rate,
            "unclosed_tasks": unclosed_tasks,
            "absent_workers": absent_workers,
        },
        "findings": findings,
    }


def _infer_role(name: str) -> str:
    """Infer agent role from name."""
    name_lower = name.lower()
    if "leader" in name_lower or "admin" in name_lower:
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
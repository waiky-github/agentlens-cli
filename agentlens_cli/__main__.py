"""CLI entry point for agentlens-audit. Provides the `cost` and `audit` subcommands."""

import argparse
import json
import os
import sys

from .config import DEFAULT_COST_MODEL
from .parser import parse_jsonl, parse_gateway_log
from .attribution import attribute_costs
from .governance import detect_waste
from .graph import build_graph
from .decision import audit_decisions
from .evidence import verify_evidence
from .shadow import detect_shadow_agents
from .compliance import audit_compliance
from .integrity import build_integrity_block, embed_integrity_meta, verify_report


def _load_events(input_path: str) -> list[dict]:
    """Load events from a file. Handles JSONL, nested JSON with 'events' key, and gateway.log."""
    ext = os.path.splitext(input_path)[1].lower()
    if ext in (".jsonl",):
        return list(parse_jsonl(input_path))
    elif ext == ".json":
        # Try JSONL first, then nested JSON
        events = list(parse_jsonl(input_path))
        if events:
            return events
        # Try nested JSON with 'events' key
        with open(input_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "events" in data:
            return data["events"]
        if isinstance(data, list):
            return data
        return []
    else:
        return list(parse_gateway_log(input_path))


def _format_findings_block(title: str, findings: list[dict]) -> str:
    """Format a block of findings in human-readable form."""
    lines = []
    lines.append("")
    lines.append(f"--- {title} ---")
    lines.append(f"  Total findings: {len(findings)}")
    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    for f in sorted(findings, key=lambda x: (severity_order.get(x.get("severity", "info"), 99), x.get("title", ""))):
        severity = f.get("severity", "info").upper()
        lines.append("")
        lines.append(f"  [{severity}] {f['title']}")
        if f.get("evidence_refs"):
            refs = [r for r in f["evidence_refs"] if r]
            if refs:
                lines.append(f"    Evidence: {', '.join(refs[:5])}")
        if f.get("detail"):
            lines.append(f"    Detail: {f['detail']}")
        if f.get("tool"):
            lines.append(f"    Tool: {f['tool']}")
        if f.get("recommendation"):
            lines.append(f"    Recommendation: {f['recommendation']}")
    return "\n".join(lines)


def format_human(cost_data: dict, governance_data: dict) -> str:
    """Format results as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("  AgentLens Cost Audit Report")
    lines.append("=" * 60)

    # Cost attribution
    lines.append("")
    lines.append("--- Cost Attribution ---")
    lines.append(f"  Total tokens in:  {cost_data['total_tokens_in']:>12,}")
    lines.append(f"  Total tokens out: {cost_data['total_tokens_out']:>12,}")
    lines.append(f"  Total cost:       {cost_data['total_cost']:>12.6f} CNY")
    lines.append("")
    lines.append("  By Agent:")
    for agent, data in sorted(cost_data["cost_by_agent"].items()):
        lines.append(f"    {agent}:")
        lines.append(f"      tokens_in={data['tokens_in']:,}  tokens_out={data['tokens_out']:,}")
        lines.append(f"      model_calls={data['model_calls']}  tool_calls={data['tool_calls']}")
        lines.append(f"      cost={data['cost']:.6f} CNY")
    lines.append(f"  Pricing: {cost_data['cost_model']['input_price_per_1m']} CNY/M in, "
                  f"{cost_data['cost_model']['output_price_per_1m']} CNY/M out")

    # Waste findings
    findings = governance_data["findings"]
    lines.append("")
    lines.append("--- Waste Findings ---")
    lines.append(f"  Total findings: {len(findings)}")
    lines.append(f"  Total est. wasted cost: {governance_data['total_est_wasted_cost']:.6f} CNY")
    total_cost = cost_data["total_cost"]
    avoidable = (governance_data["total_est_wasted_cost"] / total_cost * 100) if total_cost > 0 else 0
    lines.append(f"  Avoidable cost ratio: {avoidable:.1f}%")

    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    for f in sorted(findings, key=lambda x: (severity_order.get(x.get("severity", "info"), 99), x.get("title", ""))):
        severity = f.get("severity", "info").upper()
        lines.append("")
        lines.append(f"  [{severity}] {f['title']}")
        if f.get("evidence_refs"):
            lines.append(f"    Evidence: {', '.join(f['evidence_refs'])}")
        if f.get("tool"):
            lines.append(f"    Tool: {f['tool']}")
        if f.get("injected_chars"):
            lines.append(f"    Injected chars: {f['injected_chars']:,}")
        if f.get("call_count"):
            lines.append(f"    Call count: {f['call_count']}")
        if f.get("extra_tokens_in"):
            lines.append(f"    Extra tokens in: {f['extra_tokens_in']:,}")
        if f.get("waste_ratio"):
            lines.append(f"    Waste ratio: {f['waste_ratio']}")
        if f.get("est_wasted_cost"):
            lines.append(f"    Est. wasted cost: {f['est_wasted_cost']:.6f} CNY")
        lines.append(f"    Recommendation: {f['recommendation']}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def format_audit_human(result: dict) -> str:
    """Format full audit results as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("  AgentLens Full Audit Report (Six-Layer)")
    lines.append("=" * 60)
    lines.append(f"  Events loaded: {result['events_loaded']}")
    lines.append("")

    # Layer 1: Graph
    graph = result["graph"]
    metrics = graph.get("metrics", {})
    lines.append("--- 1. Collaboration Graph ---")
    lines.append(f"  Nodes: {len(graph.get('nodes', []))}")
    lines.append(f"  Edges: {len(graph.get('edges', []))}")
    lines.append(f"  Tasks dispatched: {metrics.get('total_dispatched', 0)}")
    lines.append(f"  Tasks closed: {metrics.get('closed_count', 0)}")
    lines.append(f"  Closure rate: {metrics.get('closure_rate', 0):.1%}")
    if metrics.get("unclosed_tasks"):
        lines.append(f"  Unclosed tasks: {metrics['unclosed_tasks']}")
    if metrics.get("absent_workers"):
        lines.append(f"  Absent workers: {metrics['absent_workers']}")
    lines.append(_format_findings_block("Graph Findings", graph.get("findings", [])))

    # Layer 2: Decision
    decision = result["decision"]
    lines.append("")
    lines.append("--- 2. Decision Audit ---")
    lines.append(f"  Decision chain steps: {len(decision.get('decision_chain', []))}")
    lines.append(f"  Summary: {decision.get('summary', '')}")
    if decision.get("approval_bypass_detected"):
        lines.append("  *** APPROVAL_BYPASS DETECTED ***")
    lines.append(_format_findings_block("Decision Findings", decision.get("findings", [])))

    # Layer 3: Evidence
    evidence = result["evidence"]
    lines.append("")
    lines.append("--- 3. Evidence Chain ---")
    lines.append(f"  Claims checked: {evidence.get('claims_checked', 0)}")
    lines.append(f"  Verified: {evidence.get('verified', 0)}")
    lines.append(f"  Completeness: {evidence.get('completeness', 0):.1%}")
    if evidence.get("missing_evidence"):
        lines.append(f"  Missing evidence: {len(evidence['missing_evidence'])} events")
    lines.append(_format_findings_block("Evidence Findings", evidence.get("findings", [])))

    # Layer 4: Cost
    cost = result["cost"]
    lines.append("")
    lines.append("--- 4. Cost Layer ---")
    lines.append(f"  Total tokens in:  {cost.get('total_tokens_in', 0):>12,}")
    lines.append(f"  Total tokens out: {cost.get('total_tokens_out', 0):>12,}")
    lines.append(f"  Total cost:       {cost.get('total_cost', 0):>12.6f} CNY")
    lines.append(f"  Waste findings: {len(cost.get('findings', []))}")
    lines.append(f"  Est. wasted cost: {cost.get('total_est_wasted_cost', 0):.6f} CNY")
    avoidable = cost.get("avoidable_cost_ratio", 0)
    lines.append(f"  Avoidable ratio: {avoidable:.1%}")

    # Layer 5: Shadow Agent Detection
    shadow = result.get("shadow", {})
    lines.append("")
    lines.append("--- 5. Shadow Agent Detection ---")
    lines.append(f"  Summary: {shadow.get('summary', 'no shadow agent findings')}")
    lines.append(_format_findings_block("Shadow Findings", shadow.get("findings", [])))

    # Layer 6: Compliance
    compliance = result.get("compliance", {})
    lines.append("")
    lines.append("--- 6. Decision Authority Compliance ---")
    lines.append(f"  Summary: {compliance.get('summary', 'no findings')}")
    lines.append(_format_findings_block("Compliance Findings", compliance.get("findings", [])))

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def build_cmd_cost(subparsers):
    """Register the `cost` subcommand."""
    p = subparsers.add_parser("cost", help="Cost attribution + waste detection")
    p.add_argument(
        "--input", "-i", required=True,
        help="Path to input file (JSONL event stream or Hermes gateway.log)",
    )
    p.add_argument(
        "--json", action="store_true", default=False,
        help="Output results as JSON (default: human-readable text)",
    )
    p.add_argument(
        "--input-price", type=float, default=2.4,
        help="Input token price per 1M tokens (default: 2.4 CNY)",
    )
    p.add_argument(
        "--output-price", type=float, default=8.0,
        help="Output token price per 1M tokens (default: 8.0 CNY)",
    )
    p.set_defaults(func=cmd_cost)


def build_cmd_audit(subparsers):
    """Register the `audit` subcommand."""
    p = subparsers.add_parser("audit", help="Full six-layer audit (graph + decision + evidence + cost + shadow + compliance)")
    p.add_argument(
        "--input", "-i", required=True,
        help="Path to input file (JSONL event stream, nested JSON, or Hermes gateway.log)",
    )
    p.add_argument(
        "--json", action="store_true", default=False,
        help="Output results as JSON (default: human-readable text)",
    )
    p.add_argument(
        "--format", choices=["json", "html"], default=None,
        help="Output format: 'json' for JSON, 'html' for self-contained HTML report",
    )
    p.add_argument(
        "--output", "-o", default=None,
        help="Write output to file (default: stdout)",
    )
    p.add_argument(
        "--input-price", type=float, default=2.4,
        help="Input token price per 1M tokens (default: 2.4 CNY)",
    )
    p.add_argument(
        "--output-price", type=float, default=8.0,
        help="Output token price per 1M tokens (default: 8.0 CNY)",
    )
    p.add_argument(
        "--known-agents", default=None,
        help="Comma-separated list of known/registered agent identifiers (default: see config.py)",
    )
    p.add_argument(
        "--dangerous-tools", default=None,
        help="Comma-separated list of dangerous tool names (default: see config.py)",
    )
    p.add_argument(
        "--gate", action="store_true", default=False,
        help="CI gate mode: exit non-zero if findings exceed thresholds",
    )
    p.add_argument(
        "--fail-on", choices=["high", "medium", "all"], default="high",
        help="Severity level to fail on (default: high). 'medium' fails on medium+high, 'all' fails on any finding.",
    )
    p.add_argument(
        "--max-high", type=int, default=0,
        help="Max allowed high-severity findings before gate fails (default: 0)",
    )
    p.add_argument(
        "--max-medium", type=int, default=None,
        help="Max allowed medium-severity findings before gate fails (default: no limit)",
    )
    p.add_argument(
        "--prev-hash", default=None,
        help="Previous report hash to chain this report onto (tamper-evident audit trail)",
    )
    p.set_defaults(func=cmd_audit)


def cmd_cost(args):
    """Execute the `cost` subcommand."""
    input_path = args.input
    if not os.path.isfile(input_path):
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    events = _load_events(input_path)

    if not events:
        print("Error: no events parsed from input file", file=sys.stderr)
        sys.exit(1)

    # Build cost model
    from .config import CostModel
    cost_model = CostModel(input_price=args.input_price, output_price=args.output_price)

    # Run attribution
    cost_data = attribute_costs(events, cost_model)

    # Run governance
    governance_data = detect_waste(events, cost_model)

    # Compute avoidable ratio
    total_cost = cost_data["total_cost"]
    total_wasted = governance_data["total_est_wasted_cost"]
    avoidable_ratio = round(total_wasted / total_cost, 4) if total_cost > 0 else 0.0

    result = {
        "cost_by_agent": cost_data["cost_by_agent"],
        "total_tokens_in": cost_data["total_tokens_in"],
        "total_tokens_out": cost_data["total_tokens_out"],
        "total_cost": cost_data["total_cost"],
        "cost_model": cost_data["cost_model"],
        "estimates": cost_data["estimates"],
        "findings": governance_data["findings"],
        "total_est_wasted_cost": governance_data["total_est_wasted_cost"],
        "avoidable_cost_ratio": avoidable_ratio,
        "events_loaded": len(events),
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_human(cost_data, governance_data))


def cmd_audit(args):
    """Execute the `audit` subcommand — full six-layer audit."""
    input_path = args.input
    if not os.path.isfile(input_path):
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    events = _load_events(input_path)

    if not events:
        print("Error: no events parsed from input file", file=sys.stderr)
        sys.exit(1)

    from .config import CostModel
    cost_model = CostModel(input_price=args.input_price, output_price=args.output_price)

    # Parse --known-agents and --dangerous-tools from CLI args
    known_agents = None
    if args.known_agents:
        known_agents = [a.strip() for a in args.known_agents.split(",") if a.strip()]
    dangerous_tools = None
    if args.dangerous_tools:
        dangerous_tools = [t.strip() for t in args.dangerous_tools.split(",") if t.strip()]

    # Layer 1: Collaboration Graph
    graph_data = build_graph(events)

    # Layer 2: Decision Audit
    decision_data = audit_decisions(events)

    # Layer 3: Evidence Chain
    all_findings = (
        graph_data.get("findings", [])
        + decision_data.get("findings", [])
    )
    evidence_data = verify_evidence(events, all_findings)

    # Layer 4: Cost (existing)
    cost_attribution = attribute_costs(events, cost_model)
    governance_data = detect_waste(events, cost_model)

    # Layer 5: Shadow Agent Detection
    shadow_findings = detect_shadow_agents(events, known_agents, dangerous_tools)

    # Layer 6: Compliance — Decision Authority
    compliance_data = audit_compliance(events)

    total_cost = cost_attribution["total_cost"]
    total_wasted = governance_data["total_est_wasted_cost"]
    avoidable_ratio = round(total_wasted / total_cost, 4) if total_cost > 0 else 0.0

    result = {
        "events_loaded": len(events),
        "graph": {
            "graph_id": graph_data["graph_id"],
            "nodes": graph_data["nodes"],
            "edges": graph_data["edges"],
            "data_gaps": graph_data["data_gaps"],
            "metrics": graph_data["metrics"],
            "findings": graph_data["findings"],
        },
        "decision": {
            "audit_id": decision_data["audit_id"],
            "decision_chain": decision_data["decision_chain"],
            "findings": decision_data["findings"],
            "summary": decision_data["summary"],
            "approval_bypass_detected": decision_data["approval_bypass_detected"],
        },
        "evidence": {
            "verification_id": evidence_data["verification_id"],
            "claims_checked": evidence_data["claims_checked"],
            "verified": evidence_data["verified"],
            "completeness": evidence_data["completeness"],
            "unreachable": evidence_data["unreachable"],
            "missing_evidence": evidence_data["missing_evidence"],
            "findings": evidence_data["findings"],
            "conclusion": evidence_data["conclusion"],
        },
        "cost": {
            "cost_by_agent": cost_attribution["cost_by_agent"],
            "total_tokens_in": cost_attribution["total_tokens_in"],
            "total_tokens_out": cost_attribution["total_tokens_out"],
            "total_cost": cost_attribution["total_cost"],
            "cost_model": cost_attribution["cost_model"],
            "estimates": cost_attribution["estimates"],
            "findings": governance_data["findings"],
            "total_est_wasted_cost": governance_data["total_est_wasted_cost"],
            "avoidable_cost_ratio": avoidable_ratio,
        },
        "shadow": {
            "summary": (
                f"{len(shadow_findings)} shadow agent findings"
                if shadow_findings
                else "no shadow agent findings"
            ),
            "findings": shadow_findings,
        },
        "compliance": {
            "summary": compliance_data["summary"],
            "findings": compliance_data["findings"],
            "decision_boundary_model": compliance_data["decision_boundary_model"],
        },
    }

    if args.json:
        result["integrity"] = build_integrity_block(result, args.prev_hash)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.format == "html":
        from .report import render_html
        from .integrity import hash_content
        html = render_html(result, input_path)
        integrity = build_integrity_block(result, args.prev_hash, hash_content(html))
        html = embed_integrity_meta(html, integrity)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(html)
            print(f"HTML report written to {args.output}", file=sys.stderr)
        else:
            print(html)
    elif args.format == "json":
        result["integrity"] = build_integrity_block(result, args.prev_hash)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_audit_human(result))

    # CI gate: count findings across all six layers and enforce thresholds
    if args.gate:
        _run_gate(result, args)


def _run_gate(result: dict, args):
    """Enforce CI gate thresholds on findings severity."""
    layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
    all_findings = []
    for key in layer_keys:
        all_findings.extend(result.get(key, {}).get("findings", []))

    high_count = sum(1 for f in all_findings if f.get("severity") == "high")
    medium_count = sum(1 for f in all_findings if f.get("severity") == "medium")

    failures = []

    if args.fail_on in ("high", "medium", "all"):
        if high_count > args.max_high:
            failures.append(f"{high_count} high findings (max allowed: {args.max_high})")

    if args.fail_on in ("medium", "all"):
        if args.max_medium is not None and medium_count > args.max_medium:
            failures.append(f"{medium_count} medium findings (max allowed: {args.max_medium})")

    if args.fail_on == "all":
        low_count = sum(1 for f in all_findings if f.get("severity") == "low")
        info_count = sum(1 for f in all_findings if f.get("severity") == "info")
        total_findings = high_count + medium_count + low_count + info_count
        if total_findings > 0:
            failures.append(f"{total_findings} total findings (any severity)")

    if failures:
        print(f"GATE FAILED: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)
    else:
        print("GATE PASSED", file=sys.stderr)


def build_cmd_diff(subparsers):
    """Register the `diff` subcommand."""
    p = subparsers.add_parser("diff", help="Compare two audit runs (baseline vs current)")
    p.add_argument(
        "--baseline", "-b", required=True,
        help="Path to baseline event file (JSONL, nested JSON, or gateway.log)",
    )
    p.add_argument(
        "--current", "-c", required=True,
        help="Path to current event file (JSONL, nested JSON, or gateway.log)",
    )
    p.add_argument(
        "--format", choices=["json", "html"], default="json",
        help="Output format: 'json' for JSON diff, 'html' for HTML diff report (default: json)",
    )
    p.add_argument(
        "--output", "-o", default=None,
        help="Write output to file (default: stdout)",
    )
    p.set_defaults(func=cmd_diff)


def _run_audit_for_diff(events: list[dict]) -> dict:
    """Run a full six-layer audit on events and return the result dict, for diff comparison."""
    from .config import CostModel
    cost_model = CostModel()

    graph_data = build_graph(events)
    decision_data = audit_decisions(events)
    all_findings = (
        graph_data.get("findings", [])
        + decision_data.get("findings", [])
    )
    evidence_data = verify_evidence(events, all_findings)
    cost_attribution = attribute_costs(events, cost_model)
    governance_data = detect_waste(events, cost_model)
    shadow_findings = detect_shadow_agents(events, None, None)
    compliance_data = audit_compliance(events)

    total_cost = cost_attribution["total_cost"]
    total_wasted = governance_data["total_est_wasted_cost"]
    avoidable_ratio = round(total_wasted / total_cost, 4) if total_cost > 0 else 0.0

    return {
        "events_loaded": len(events),
        "graph": {
            "nodes": graph_data["nodes"],
            "edges": graph_data["edges"],
            "metrics": graph_data["metrics"],
            "findings": graph_data["findings"],
        },
        "decision": {
            "decision_chain": decision_data["decision_chain"],
            "findings": decision_data["findings"],
            "summary": decision_data["summary"],
        },
        "evidence": {
            "claims_checked": evidence_data["claims_checked"],
            "verified": evidence_data["verified"],
            "completeness": evidence_data["completeness"],
            "findings": evidence_data["findings"],
        },
        "cost": {
            "total_cost": cost_attribution["total_cost"],
            "total_tokens_in": cost_attribution["total_tokens_in"],
            "total_tokens_out": cost_attribution["total_tokens_out"],
            "findings": governance_data["findings"],
            "total_est_wasted_cost": governance_data["total_est_wasted_cost"],
            "avoidable_cost_ratio": avoidable_ratio,
        },
        "shadow": {
            "findings": shadow_findings,
        },
        "compliance": {
            "findings": compliance_data["findings"],
        },
    }


def _count_findings_by_severity(findings: list[dict]) -> dict:
    """Count findings by severity."""
    counts = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info")
        if sev in counts:
            counts[sev] += 1
    return counts


def cmd_diff(args):
    """Execute the `diff` subcommand."""
    if not os.path.isfile(args.baseline):
        print(f"Error: baseline file not found: {args.baseline}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.current):
        print(f"Error: current file not found: {args.current}", file=sys.stderr)
        sys.exit(1)

    baseline_events = _load_events(args.baseline)
    current_events = _load_events(args.current)

    if not baseline_events:
        print("Error: no events parsed from baseline file", file=sys.stderr)
        sys.exit(1)
    if not current_events:
        print("Error: no events parsed from current file", file=sys.stderr)
        sys.exit(1)

    baseline_result = _run_audit_for_diff(baseline_events)
    current_result = _run_audit_for_diff(current_events)

    # Collect all findings across 6 layers for each
    layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
    baseline_all_findings = []
    for key in layer_keys:
        baseline_all_findings.extend(baseline_result.get(key, {}).get("findings", []))
    current_all_findings = []
    for key in layer_keys:
        current_all_findings.extend(current_result.get(key, {}).get("findings", []))

    b_severity = _count_findings_by_severity(baseline_all_findings)
    c_severity = _count_findings_by_severity(current_all_findings)

    b_total = sum(b_severity.values())
    c_total = sum(c_severity.values())

    b_closure = baseline_result["graph"]["metrics"].get("closure_rate", 0)
    c_closure = current_result["graph"]["metrics"].get("closure_rate", 0)

    b_cost = baseline_result["cost"]["total_cost"]
    c_cost = current_result["cost"]["total_cost"]
    b_avoidable = baseline_result["cost"]["avoidable_cost_ratio"]
    c_avoidable = current_result["cost"]["avoidable_cost_ratio"]

    output = {
        "baseline": {
            "events_loaded": baseline_result["events_loaded"],
            "total_cost": b_cost,
            "avoidable_cost_ratio": b_avoidable,
            "findings": b_severity,
            "findings_total": b_total,
            "closure_rate": round(b_closure, 4),
        },
        "current": {
            "events_loaded": current_result["events_loaded"],
            "total_cost": c_cost,
            "avoidable_cost_ratio": c_avoidable,
            "findings": c_severity,
            "findings_total": c_total,
            "closure_rate": round(c_closure, 4),
        },
        "deltas": {
            "events_loaded": current_result["events_loaded"] - baseline_result["events_loaded"],
            "total_cost": round(c_cost - b_cost, 6),
            "avoidable_cost_ratio": round(c_avoidable - b_avoidable, 4),
            "findings_total": c_total - b_total,
            "findings_high": c_severity["high"] - b_severity["high"],
            "findings_medium": c_severity["medium"] - b_severity["medium"],
            "findings_low": c_severity["low"] - b_severity["low"],
            "findings_info": c_severity["info"] - b_severity["info"],
            "closure_rate": round(c_closure - b_closure, 4),
        },
    }

    if args.format == "html":
        from .report import render_diff_html
        html = render_diff_html(output, args.baseline, args.current)
        if args.output:
            _write_output(args.output, html)
            print(f"HTML diff report written to {args.output}", file=sys.stderr)
        else:
            print(html)
    else:
        json_str = json.dumps(output, indent=2, ensure_ascii=False)
        if args.output:
            _write_output(args.output, json_str)
            print(f"JSON diff written to {args.output}", file=sys.stderr)
        else:
            print(json_str)


def _write_output(path: str, content: str):
    """Write content to file, creating parent directories if needed."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def build_cmd_demo(subparsers):
    """Register the `demo` subcommand."""
    p = subparsers.add_parser("demo", help="Generate a one-shot HTML demo report from built-in sample data")
    p.add_argument(
        "--output", "-o", default="./agentlens_demo_report.html",
        help="Output path for the HTML demo report (default: ./agentlens_demo_report.html)",
    )
    p.set_defaults(func=cmd_demo)


def cmd_demo(args):
    """Execute the `demo` subcommand."""
    import os as _os
    # Resolve examples directory relative to the package
    pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    demo_input = _os.path.join(pkg_dir, "..", "examples", "multi_agent_task_events_v2.jsonl")
    demo_input = _os.path.abspath(demo_input)

    if not _os.path.isfile(demo_input):
        print(f"Error: demo data file not found: {demo_input}", file=sys.stderr)
        sys.exit(1)

    events = _load_events(demo_input)
    if not events:
        print("Error: no events parsed from demo data file", file=sys.stderr)
        sys.exit(1)

    from .config import CostModel
    from .report import render_html
    cost_model = CostModel()

    # Run full six-layer audit
    graph_data = build_graph(events)
    decision_data = audit_decisions(events)
    all_findings = (
        graph_data.get("findings", [])
        + decision_data.get("findings", [])
    )
    evidence_data = verify_evidence(events, all_findings)
    cost_attribution = attribute_costs(events, cost_model)
    governance_data = detect_waste(events, cost_model)
    shadow_findings = detect_shadow_agents(events, None, None)
    compliance_data = audit_compliance(events)

    total_cost = cost_attribution["total_cost"]
    total_wasted = governance_data["total_est_wasted_cost"]
    avoidable_ratio = round(total_wasted / total_cost, 4) if total_cost > 0 else 0.0

    result = {
        "events_loaded": len(events),
        "graph": {
            "graph_id": graph_data["graph_id"],
            "nodes": graph_data["nodes"],
            "edges": graph_data["edges"],
            "data_gaps": graph_data["data_gaps"],
            "metrics": graph_data["metrics"],
            "findings": graph_data["findings"],
        },
        "decision": {
            "audit_id": decision_data["audit_id"],
            "decision_chain": decision_data["decision_chain"],
            "findings": decision_data["findings"],
            "summary": decision_data["summary"],
            "approval_bypass_detected": decision_data["approval_bypass_detected"],
        },
        "evidence": {
            "verification_id": evidence_data["verification_id"],
            "claims_checked": evidence_data["claims_checked"],
            "verified": evidence_data["verified"],
            "completeness": evidence_data["completeness"],
            "unreachable": evidence_data["unreachable"],
            "missing_evidence": evidence_data["missing_evidence"],
            "findings": evidence_data["findings"],
            "conclusion": evidence_data["conclusion"],
        },
        "cost": {
            "cost_by_agent": cost_attribution["cost_by_agent"],
            "total_tokens_in": cost_attribution["total_tokens_in"],
            "total_tokens_out": cost_attribution["total_tokens_out"],
            "total_cost": cost_attribution["total_cost"],
            "cost_model": cost_attribution["cost_model"],
            "estimates": cost_attribution["estimates"],
            "findings": governance_data["findings"],
            "total_est_wasted_cost": governance_data["total_est_wasted_cost"],
            "avoidable_cost_ratio": avoidable_ratio,
        },
        "shadow": {
            "summary": (
                f"{len(shadow_findings)} shadow agent findings"
                if shadow_findings
                else "no shadow agent findings"
            ),
            "findings": shadow_findings,
        },
        "compliance": {
            "summary": compliance_data["summary"],
            "findings": compliance_data["findings"],
            "decision_boundary_model": compliance_data["decision_boundary_model"],
        },
    }

    html = render_html(result, demo_input)
    from .integrity import hash_content
    integrity = build_integrity_block(result, None, hash_content(html))
    html = embed_integrity_meta(html, integrity)
    _write_output(args.output, html)
    print(f"Demo report generated: {args.output}")


def build_cmd_verify(subparsers):
    """Register the `verify` subcommand."""
    p = subparsers.add_parser("verify", help="Verify a report's tamper-evident integrity")
    p.add_argument("--report", required=True, help="Path to HTML report to verify")
    p.set_defaults(func=cmd_verify)


def cmd_verify(args):
    """Execute the `verify` subcommand."""
    path = args.report
    if not os.path.isfile(path):
        print(f"Error: report file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    res = verify_report(html)
    if res["verified"]:
        print(f"VERIFIED: report integrity OK (sha256 {res['expected']})")
    else:
        print(f"TAMPERED: {res['reason']}", file=sys.stderr)
        print(f"  expected: {res.get('expected')}", file=sys.stderr)
        print(f"  actual:   {res.get('actual')}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="agentlens-audit",
        description="AgentLens CLI - Multi-agent cost governance toolkit",
    )
    from . import __version__

    parser.add_argument(
        "--version", action="version",
        version=f"agentlens-audit {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    build_cmd_cost(subparsers)
    build_cmd_audit(subparsers)
    build_cmd_diff(subparsers)
    build_cmd_demo(subparsers)
    build_cmd_verify(subparsers)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
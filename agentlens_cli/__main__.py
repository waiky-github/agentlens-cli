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
    lines.append("  AgentLens Full Audit Report")
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
    p = subparsers.add_parser("audit", help="Full four-layer audit (graph + decision + evidence + cost)")
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
    """Execute the `audit` subcommand — full four-layer audit."""
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
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.format == "html":
        from .report import render_html
        html = render_html(result, input_path)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(html)
            print(f"HTML report written to {args.output}", file=sys.stderr)
        else:
            print(html)
    elif args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_audit_human(result))


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

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
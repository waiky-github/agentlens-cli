"""CLI entry point for agentlens-audit. Provides the `cost` subcommand."""

import argparse
import json
import os
import sys

from .config import DEFAULT_COST_MODEL
from .parser import parse_jsonl, parse_gateway_log
from .attribution import attribute_costs
from .governance import detect_waste


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


def cmd_cost(args):
    """Execute the `cost` subcommand."""
    input_path = args.input
    if not os.path.isfile(input_path):
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load events
    ext = os.path.splitext(input_path)[1].lower()
    if ext in (".jsonl", ".json"):
        events = list(parse_jsonl(input_path))
    else:
        # Try gateway.log text parsing
        events = list(parse_gateway_log(input_path))

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

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
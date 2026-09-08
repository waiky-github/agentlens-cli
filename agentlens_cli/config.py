"""Pricing configuration for cost attribution."""


class CostModel:
    """Token pricing model. All prices are per 1M tokens."""

    def __init__(self, input_price: float = 2.4, output_price: float = 8.0):
        self.input_price = input_price
        self.output_price = output_price

    def input_cost(self, tokens: int) -> float:
        return (tokens / 1_000_000) * self.input_price

    def output_cost(self, tokens: int) -> float:
        return (tokens / 1_000_000) * self.output_price

    def total_cost(self, tokens_in: int, tokens_out: int) -> float:
        return self.input_cost(tokens_in) + self.output_cost(tokens_out)

    def to_dict(self) -> dict:
        return {
            "input_price_per_1m": self.input_price,
            "output_price_per_1m": self.output_price,
            "currency": "CNY",
            "note": "estimate — configurable pricing model",
        }


# Default instance
DEFAULT_COST_MODEL = CostModel()

# ── Shadow Agent Detection defaults ──────────────────────────────

# Known/registered agents extracted from well-known multi-agent patterns.
# Override with --known-agents a,b,c in the CLI.
DEFAULT_KNOWN_AGENTS = [
    "agent:main",
    "team-leader",
    "admin",
    "collector",
    "graph-builder",
    "decision-auditor",
    "cost-analyst",
    "evidence-verifier",
]

# Dangerous tools that require explicit approval before execution.
# Override with --dangerous-tools x,y,z in the CLI.
DEFAULT_DANGEROUS_TOOLS = [
    "shell",
    "bash",
    "rm",
    "delete",
    "drop",
    "exec",
    "system",
    "sudo",
    "kill",
    "shutdown",
    "reboot",
    "write_file",
    "overwrite",
    "truncate",
]

# Agent role → permitted tools mapping for privilege boundary detection.
# If an agent invokes a tool outside its permitted set, it's a boundary violation.
# An empty value means "all tools allowed" (leader/admin).
AGENT_ROLE_TOOLS = {
    "leader": [],
    "admin": [],
    "collector": ["fetch", "get", "read", "list", "search", "ls", "cat", "grep", "find"],
    "builder": ["build", "compile", "render", "transform", "merge", "compose"],
    "auditor": ["audit", "check", "verify", "validate", "diff", "compare", "scan"],
    "analyst": ["analyze", "cost", "calculate", "aggregate", "query", "report", "stats"],
    "verifier": ["verify", "check", "validate", "hash", "digest", "compare"],
    "worker": ["fetch", "get", "read", "list", "search"],
}
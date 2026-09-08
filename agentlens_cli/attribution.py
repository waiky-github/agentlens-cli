"""Cost attribution: roll up token usage to per-agent and per-task cost."""

from collections import defaultdict
from .config import CostModel, DEFAULT_COST_MODEL


def attribute_costs(events: list[dict], cost_model: CostModel = None) -> dict:
    """Attribute costs from events to agents and tasks.

    Returns a dict with:
      - cost_by_agent: {agent_name: {tokens_in, tokens_out, tool_calls, cost, model_calls}}
      - total_tokens_in, total_tokens_out
      - total_cost
      - cost_model: pricing model info
      - estimates: list of estimation notes
    """
    if cost_model is None:
        cost_model = DEFAULT_COST_MODEL

    agents = defaultdict(lambda: {
        "tokens_in": 0,
        "tokens_out": 0,
        "tool_calls": 0,
        "cost": 0.0,
        "model_calls": 0,
    })

    estimates = []
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0

    for evt in events:
        etype = evt.get("type", "")
        payload = evt.get("payload", {}) or {}

        if etype == "model_call":
            agent = payload.get("agent", "unknown")
            tokens_in = payload.get("tokens_in", 0) or 0
            tokens_out = payload.get("tokens_out", 0) or 0
            cost = cost_model.total_cost(tokens_in, tokens_out)

            agents[agent]["tokens_in"] += tokens_in
            agents[agent]["tokens_out"] += tokens_out
            agents[agent]["cost"] += cost
            agents[agent]["model_calls"] += 1

            total_tokens_in += tokens_in
            total_tokens_out += tokens_out
            total_cost += cost

        elif etype == "tool_invocation":
            agent = payload.get("agent", "unknown")
            agents[agent]["tool_calls"] += 1

    # Round costs
    for agent_data in agents.values():
        agent_data["cost"] = round(agent_data["cost"], 6)
    total_cost = round(total_cost, 6)

    estimates.append("cost is estimated — configurable pricing model, no unit price in event stream")

    return {
        "cost_by_agent": dict(agents),
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "total_cost": total_cost,
        "cost_model": cost_model.to_dict(),
        "estimates": estimates,
    }
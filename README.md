# AgentLens CLI

Multi-agent cost governance toolkit — standalone CLI tool to detect, quantify, and recommend fixes for token waste in AI agent collaborations.

## Install

```bash
cd agentlens-cli
pip install -e .
```

Or run directly without install:

```bash
python -m agentlens_cli cost --input examples/hermes_gateway_events.jsonl
```

## Usage

```bash
# Human-readable report (default)
agentlens-audit cost --input events.jsonl

# JSON output
agentlens-audit cost --input events.jsonl --json

# Custom pricing
agentlens-audit cost --input events.jsonl --json --input-price 1.5 --output-price 5.0

# Parse Hermes gateway.log (best-effort text parsing)
agentlens-audit cost --input ~/.hermes/logs/gateway.log
```

## Input

JSONL event stream compatible with Hermes gateway event schema. Each line is a JSON object with:

- `event_id` — unique event identifier
- `type` — one of `model_call`, `tool_invocation`, `user_message_arrived`, `agent_response_sent`, `session_event`
- `timestamp` — ISO8601 UTC
- `source` — origin identifier
- `payload` — type-specific data (e.g., `tokens_in`, `tokens_out`, `output_chars`, `tool`, `agent`)
- `evidence_ref` — reference to source log line

Also supports direct Hermes `gateway.log` text parsing (best-effort).

## Output

Key fields in JSON output:

| Field | Description |
|-------|-------------|
| `cost_by_agent` | Per-agent token/cost breakdown |
| `total_cost` | Total estimated cost (CNY) |
| `total_tokens_in` / `total_tokens_out` | Total token counts |
| `findings` | Array of waste detection findings |
| `total_est_wasted_cost` | Sum of wasted costs |
| `avoidable_cost_ratio` | Wasted / total cost ratio |

Each finding includes severity, evidence references, quantified waste, and actionable recommendations.

## Waste Detection Rules

Based on cost-governance SKILL.md:

1. **Large-output tool injection** — tool output > 10,000 chars injected into context ungoverned
2. **Repeated high-output tool calls** — same tool re-fetched within 5 minutes
3. **Session-level context bloat** — context grows without deliberate compaction across sessions
4. **Inefficient loops** — rapid repeated calls to same tool (6+ in 2 minutes)
5. **Structural observations** — no per-agent token caps
6. **Cost-model gaps** — unit prices are estimates

## Example Data

`examples/hermes_gateway_events.jsonl` — Real Hermes gateway event stream (~11K events).
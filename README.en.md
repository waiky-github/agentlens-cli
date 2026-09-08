# AgentLens Audit

**Multi-agent collaboration audit CLI — Cost Governance · Decision Audit · Evidence Chain · Shadow Agents · Decision Authority Compliance**

AgentLens Audit makes any multi-agent system (Hermes / CrewAI / AutoGen / LangGraph) **visible, auditable, and reviewable**. One command produces a complete audit report: who split the tasks, why tasks were dispatched the way they were, which tools were called, how much it cost, and whether accountability is traceable when something goes wrong.

Aligned with the core compliance requirements of the CAC's *Opinions on Standardized Application and Innovative Development of Intelligent Agents* (2026-05): verifiable and traceable behavior, shadow-agent control, and tiered decision authority.

## ✨ Seven-Layer Audit

| Layer | Capability | Description |
|:--|:--|:--|
| 🕸️ graph | Collaboration Graph | Full-chain reconstruction task → split → dispatch → execution → aggregation; closure rate, absent-worker detection |
| 🧭 decision | Decision Audit | Who dispatched to whom, why split, whether approval chains are compliant (reproduces AL-AUDIT conclusions) |
| 🔗 evidence | Evidence Chain | Conclusion → reference → retrieval → test, fully traceable, integrity-verified |
| 💰 cost | Cost Governance | Per-agent/task cost attribution + waste detection (large-output injection / repeated calls); 63–76% avoidable cost in real runs |
| 👻 shadow | Shadow Agents | Unregistered agents / unauthorized tool calls / privilege-boundary violations |
| ⚖️ compliance | Decision Authority Compliance | User-only / user-authorized / autonomous trichotomy + informed consent + final veto |
| 📋 regulations | Compliance Clause Mapping | Findings auto-linked to regulation clauses (CAC Opinions / EU AI Act / Personification Measures) |
| 🚪 gate | CI Integration | Non-zero exit code when violations exceed threshold — audit as a lint gate |
| 🔍 watchdog | Continuous Audit / Drift Monitoring | Periodic re-checks against a baseline, alerting on new problem drift; cron-friendly |

## 🚀 Quick Start

```bash
pip install agentlens-audit

# One-command demo report (bundled sample data)
agentlens-audit demo --output report.html

# Full audit of any event stream (JSON output)
agentlens-audit audit --input events.jsonl --json

# HTML audit report
agentlens-audit audit --input events.jsonl --format html --output report.html

# Cost-only analysis
agentlens-audit cost --input events.jsonl --json

# Compare two audits (monthly governance)
agentlens-audit diff --baseline last_month.jsonl --current this_month.jsonl

# CI gate: fail when any high-severity violation exists
agentlens-audit audit --input events.jsonl --gate --fail-on high

# Verify report integrity (tamper-evident hash chain)
agentlens-audit verify --report report.html

# Query regulation mappings / remediation advice
agentlens-audit regs --title approval
agentlens-audit remediations --title shadow
```

## 🔍 Watchdog — Continuous Audit / Drift Monitoring

Auditing is not a one-time act. The `watchdog` subcommand periodically re-checks the current audit result against a baseline to detect drift.

### Establish a baseline (first run)

```bash
agentlens-audit watchdog --input events.jsonl --write-baseline baseline.json
```

### Compare and alert

```bash
agentlens-audit watchdog --input events.jsonl --baseline baseline.json
```

### Exit code semantics

| Code | Meaning |
|:--|:--|
| 0 | No new or increased high-severity findings — healthy |
| 1 | New high-severity finding, or an existing high finding grew in count — alert |
| 2 | Input error (missing file, invalid baseline JSON, etc.) |

### Cron example

```bash
# Run every 24h, append to log
0 0 * * * /usr/local/bin/agentlens-audit watchdog --input /data/events.jsonl --baseline /data/baseline.json >> /var/log/agentlens-watchdog.log 2>&1
```

## 📥 Supported Inputs

- **Hermes**: parse `gateway.log` directly
- **CrewAI / AutoGen / LangGraph**: logs/traces → unified event stream (see `converters/`)
- **Unified event-stream JSONL**: `{type, timestamp, source, payload, evidence_ref, event_id}`

## 📤 Outputs

- `--json`: structured audit result (seven layers, with integrity block)
- `--format html`: self-contained HTML report (no external resources; offline-openable, archivable)
- `diff`: baseline comparison JSON/HTML
- `--gate`: CI exit code

## 🔌 MCP Server

AgentLens Audit can run as an MCP server, usable from any MCP client (Claude / Cursor / Hermes).

### Install

```bash
pip install agentlens-audit[mcp]
```

### Client configuration

**stdio mode (recommended):**

```json
{
  "mcpServers": {
    "agentlens-audit": {
      "command": "python",
      "args": ["-m", "agentlens_cli.mcp_server"]
    }
  }
}
```

**HTTP mode:**

```json
{
  "mcpServers": {
    "agentlens-audit": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

Start the HTTP server:

```bash
python -m agentlens_cli.mcp_server --transport http --port 8765 --host 127.0.0.1
```

### Available tools

| Tool | Description |
|:--|:--|
| `audit` | Full seven-layer audit, returns JSON (with integrity block) |
| `cost_analysis` | Cost analysis (total / avoidable / ratio) |
| `verify_report` | Report integrity verification (tamper-evident hash chain) |
| `list_regulations` | Regulation mapping lookup |

## 🧪 Tests

```bash
python -m pytest tests/ -v   # 120 tests green
```

## 📦 Release

- PyPI: https://pypi.org/project/agentlens-audit/
- GitHub: https://github.com/waiky-github/agentlens-cli
- License: MIT

## 🙏 Credits

The audit methodology originates from AgentLens (GOAI New Intelligence Infrastructure track entry); rule implementations reference its cost-governance / decision-audit / evidence-chain / graph-merge SKILL definitions.

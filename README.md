# AgentLens CLI

Multi-agent governance toolkit — six-layer audit CLI covering collaboration graph, decision audit, evidence chain, cost governance, shadow agent detection, and decision authority compliance.

## Six-Layer Audit

| Layer | Module | Description |
|-------|--------|-------------|
| 1. Collaboration Graph | `graph.py` | Reconstructs task→decompose→dispatch→execute→summary chains. Outputs nodes, edges, task closure rate, absent workers. |
| 2. Decision Audit | `decision.py` | Checks dispatch rationale, L3 approval chains, and detects approval bypass (`APPROVAL_BYPASS_CONFIRMED`). |
| 3. Evidence Chain | `evidence.py` | Verifies every event/claim has a reachable `evidence_ref`. Outputs completeness ratio and missing-evidence list. |
| 4. Cost Layer | `governance.py` + `attribution.py` | Token attribution + waste detection (large-output injection, repeated calls, context bloat, etc.). |
| 5. Shadow Agent Detection | `shadow.py` | Detects unregistered agents (`SHADOW_AGENT_DETECTED`), unauthorized tool calls (`UNAUTHORIZED_TOOL_CALL`), and privilege boundary violations (`PRIVILEGE_BOUNDARY_VIOLATION`). Compliant with 网信办《智能体规范应用与创新发展实施意见》(2026-05). |
| 6. Decision Authority Compliance | `compliance.py` | Enforces Article 6 of 网信办《实施意见》(2026-05): classifies actions into USER_ONLY/USER_AUTHORIZED/AGENT_AUTONOMOUS, detects `USER_ONLY_VIOLATION`, `HIGH_RISK_AUTONOMOUS_DECISION`, `MISSING_USER_AUTHORIZATION`, and `MISSING_INFORMED_CONSENT`. |

## Install

```bash
cd agentlens-cli
pip install -e .
```

Or run directly without install:

```bash
python -m agentlens_cli audit --input examples/hermes_gateway_events.jsonl
```

## Usage

### `audit` — Full Six-Layer Audit

```bash
# Human-readable report (default)
agentlens-audit audit --input events.jsonl

# JSON output
agentlens-audit audit --input events.jsonl --json

# Custom pricing
agentlens-audit audit --input events.jsonl --json --input-price 1.5 --output-price 5.0

# HTML report (self-contained, offline-capable)
agentlens-audit audit --input events.jsonl --format html --output report.html

# Shadow agent detection with custom known agents and dangerous tools
agentlens-audit audit --input events.jsonl --json --known-agents "agent:main,team-leader,collector" --dangerous-tools "shell,rm,exec"

# Works with nested JSON (e.g. approval_bypass.json), JSONL, and gateway.log
agentlens-audit audit --input examples/approval_bypass.json --json
agentlens-audit audit --input examples/multi_agent_task_events_v2.jsonl --json
```

### `cost` — Cost Layer Only (backward compatible)

```bash
agentlens-audit cost --input events.jsonl
agentlens-audit cost --input events.jsonl --json
agentlens-audit cost --input ~/.hermes/logs/gateway.log
```

## 框架接入 (Framework Adapters)

AgentLens CLI 提供框架适配器，将主流多 Agent 框架的执行日志转换为统一事件流 JSONL，直接供 `audit` 子命令消费。

| 框架 | 日志采集方式 | Converter | 用法示例 |
|------|------------|-----------|---------|
| **CrewAI** | 启用 CrewAI verbose 日志，捕获 `[AGENT]`/`[TASK]`/`[TOOL]`/`[LLM]` 结构化输出 | `converters/crewai_converter.py` | `python converters/crewai_converter.py crewai_output.log audit_events.jsonl` |
| **AutoGen** | 启用 AutoGen 结构化日志（JSON Lines），每条消息包含 `type`/`source`/`role`/`tokens` 等字段 | `converters/autogen_converter.py` | `python converters/autogen_converter.py autogen_trace.jsonl audit_events.jsonl` |
| **LangGraph** | 使用 LangGraph 的 tracing 回调，捕获 `node_start`/`node_end`/`llm_call`/`tool_call`/`edge_traverse` 等状态变更 | `converters/langgraph_converter.py` | `python converters/langgraph_converter.py langgraph_trace.jsonl audit_events.jsonl` |

转换后统一使用 `audit` 命令审计：

```bash
python -m agentlens_cli audit --input audit_events.jsonl --json
```

## Input Formats

- **JSONL** — One JSON event per line (standard event stream)
- **Nested JSON** — Single JSON object with `"events"` key containing event array (scenario format)
- **Hermes gateway.log** — Best-effort text parsing of raw Hermes logs

Event types recognized: `task_split`, `task_dispatch`, `task_completion`, `task_failed`, `task_retry`, `approval`, `action_executed`, `conflict_resolved`, `model_call`, `tool_invocation`, `user_message_arrived`, `agent_response_sent`, `session_event`.

## Output

Key fields in JSON output (audit subcommand):

| Field | Description |
|-------|-------------|
| `events_loaded` | Total events parsed |
| `graph.nodes` | Agent/task nodes with roles |
| `graph.edges` | Dispatch/approval/completion edges |
| `graph.metrics.closure_rate` | Task completion ratio (closed / dispatched) |
| `graph.metrics.absent_workers` | Workers dispatched to but never completed |
| `decision.decision_chain` | Ordered decision steps with rationale/approval |
| `decision.approval_bypass_detected` | Boolean: `APPROVAL_BYPASS_CONFIRMED` found |
| `evidence.completeness` | Ratio of events with valid evidence_ref |
| `evidence.missing_evidence` | Events without reachable evidence |
| `cost.total_cost` | Total estimated cost (CNY) |
| `cost.findings` | Waste detection findings |
| `shadow.summary` | Shadow agent detection summary |
| `shadow.findings` | Shadow agent findings: `SHADOW_AGENT_DETECTED`, `UNAUTHORIZED_TOOL_CALL`, `PRIVILEGE_BOUNDARY_VIOLATION` |
| `compliance.summary` | Compliance findings summary |
| `compliance.findings` | Compliance findings: `USER_ONLY_VIOLATION`, `HIGH_RISK_AUTONOMOUS_DECISION`, `MISSING_USER_AUTHORIZATION`, `MISSING_INFORMED_CONSENT` |
| `compliance.decision_boundary_model` | Configured action classification tables (USER_ONLY/USER_AUTHORIZED/AGENT_AUTONOMOUS) |

Each finding follows the structured format: `severity`, `title`, `evidence_refs`, `recommendation`, `est_impact` (where applicable).

## Acceptance Scenarios

### Scenario 1: Approval Bypass Detection

```bash
python -m agentlens_cli audit --input examples/approval_bypass.json --json
```

Expected: `decision.approval_bypass_detected = true`, `APPROVAL_BYPASS_CONFIRMED` finding with severity `high`.

### Scenario 2: Full Closure (5/5 workers)

```bash
python -m agentlens_cli audit --input examples/multi_agent_task_events_v2.jsonl --json
```

Expected: `graph.metrics.closure_rate = 1.0`, `decision.approval_bypass_detected = false`, L3 approval chain compliant.

### Scenario 3: Data Gaps (missing workers)

```bash
python -m agentlens_cli audit --input examples/multi_agent_task_events.jsonl --json
```

Expected: `graph.metrics.closure_rate < 1.0`, `absent_workers` includes graph-builder and decision-auditor.

### Scenario 4: Hermes Gateway (regression)

```bash
python -m agentlens_cli audit --input examples/hermes_gateway_events.jsonl --json
```

Expected: All five layers produce output, JSON valid, exit code 0, ~11K events, ~435 cost findings.

### Scenario 5: Shadow Agent Detection

```bash
python -m agentlens_cli audit --input examples/shadow_agent_events.jsonl --json
```

Expected: `shadow.findings` contains `SHADOW_AGENT_DETECTED` (high), `UNAUTHORIZED_TOOL_CALL` (high), `PRIVILEGE_BOUNDARY_VIOLATION` (medium) — at least 1 of each type.

### Scenario 6: Shadow Agent — Compliance (no false positives)

```bash
python -m agentlens_cli audit --input examples/multi_agent_task_events_v2.jsonl --json
```

Expected: `shadow.findings` is empty (0 findings) — legitimate agents should not trigger shadow detection.

### Scenario 7: Compliance — Decision Authority Violations

```bash
python -m agentlens_cli audit --input examples/compliance_violations.jsonl --json
```

Expected: `compliance.findings` contains `USER_ONLY_VIOLATION` (high), `HIGH_RISK_AUTONOMOUS_DECISION` (high), `MISSING_USER_AUTHORIZATION` (medium), `MISSING_INFORMED_CONSENT` (info) — at least 1 of each type.

### Scenario 8: Compliance — Hermes Gateway (no approval stream)

```bash
python -m agentlens_cli audit --input examples/hermes_gateway_events.jsonl --json
```

Expected: Hermes data has no approval events, so compliance layer should NOT produce `HIGH_RISK_AUTONOMOUS_DECISION` at severity high. It may produce `AUDIT_GAP_NO_APPROVAL_STREAM` at info level.

## Example Data

- `examples/hermes_gateway_events.jsonl` — Real Hermes gateway event stream (~11K events)
- `examples/approval_bypass.json` — High-risk config change without L3 approval (4 events)
- `examples/multi_agent_task_events_v2.jsonl` — Full 5-worker pipeline with retries, conflict resolution, L3 approval (20 events)
- `examples/multi_agent_task_events.jsonl` — Gaps scenario: 3 dispatched, only 1 completed (5 events)
- `examples/shadow_agent_events.jsonl` — Shadow agent detection scenario: unregistered agent, unauthorized shell call, privilege escalation (6 events)
- `examples/compliance_violations.jsonl` — Compliance violation scenario: USER_ONLY violation, L3 autonomous decision, missing authorization, missing consent (5 events)
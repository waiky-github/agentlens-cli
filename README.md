# AgentLens Audit

**多 Agent 协作审计 CLI —— 成本治理 · 决策审计 · 证据链 · 影子智能体 · 决策权限合规**

AgentLens Audit 让任何多 Agent 系统（Hermes / CrewAI / AutoGen / LangGraph）的协作过程**可见、可审、可复盘**。一条命令产出完整审计报告：谁拆的任务、为什么这么派、调了哪些工具、花了多少钱、出了事能否追责。

对齐中国网信办《智能体规范应用与创新发展实施意见》(2026-05) 的核心合规要求：行为可验证可追溯、影子智能体管控、决策权限分层。

## ✨ 功能特性（七层审计）

| 层 | 能力 | 说明 |
|:--|:--|:--|
| 🕸️ graph | 协作图谱 | 任务→拆解→派单→执行→汇总 全链路还原，闭环率、缺席 Worker 检测 |
| 🧭 decision | 决策审计 | 谁派给谁、为什么拆、审批链是否合规（可复现 AL-AUDIT 系列结论） |
| 🔗 evidence | 证据链 | 结论→引用→检索→测试 可回溯，完整性核验 |
| 💰 cost | 成本治理 | 按 Agent/任务成本归因 + 浪费检测（大输出注入/重复调用），实测可避免成本 63-76% |
| 👻 shadow | 影子智能体 | 未登记 Agent / 未授权工具调用 / 权限越界检测 |
| ⚖️ compliance | 决策权限合规 | 用户本人决策/用户授权/自主决策三分法 + 知情权 + 最终否决权 |
| 📋 regulations | 合规条款映射 | 审计发现自动关联法规条款（网信办《实施意见》/ EU AI Act /《拟人化互动办法》/ **OWASP LLM Top 10 2026 + Agentic Top 10 + ACS**） |
| 🏷 annotations | 人工合规标注 | 未映射/需纠正的 finding 支持人工标注（`regs --annotate` + Web UI），人工判定优先于静态表 |
| 🚨 budget | 成本预算告警 | 单次审计总成本/预估浪费超阈值 → 推飞书/webhook/命令（notify 通道）+ 历史记录 |
| 🩺 leakage | 系统提示泄露检测 | OWASP LLM08 Hidden Context Exposure：内容级强检测 + 超大输出元数据弱信号 |
| 🔁 verify | 修复回归验证 | mark-fixed 后连续 3 次审计缺席才 verified，复发即 regressed（防假修复） |
| 🚪 gate | CI 集成 | 违规超阈值 → 非零退出码，审计当 lint 挂 CI |
| 🔍 watchdog | 持续审计 / 漂移监控 | 定期复检，对比基线发现新问题漂移，支持 cron 调度 + 多日漂移趋势历史 |
| 🌐 web | Web 平台 | FastAPI 仪表盘 + 报告查看 + 触发审计 + 修复跟踪 + 合规标注 + 预算告警 + Watchdog 趋势图（Basic Auth） |
| 🔌 mcp | MCP Server | 7 个工具（audit/cost_analysis/verify_report/list_regulations/watchdog_status/remediation_lookup/fix_tracking_status），可接入任意 MCP 客户端 |

## 🚀 快速开始

```bash
pip install agentlens-audit

# 一键生成演示报告（内置样例数据）
agentlens-audit demo --output report.html

# 对任意事件流做完整审计（JSON 输出）
agentlens-audit audit --input events.jsonl --json

# 生成 HTML 审计报告
agentlens-audit audit --input events.jsonl --format html --output report.html

# 成本专项
agentlens-audit cost --input events.jsonl --json

# 两次审计对比（月度治理）
agentlens-audit diff --baseline last_month.jsonl --current this_month.jsonl

# CI 门禁：high 级违规数 > 0 即失败
agentlens-audit audit --input events.jsonl --gate --fail-on high

# 验报告完整性（防篡改哈希链）
agentlens-audit verify --report report.html

# 查询法规映射 / 修复建议
agentlens-audit regs --title approval
agentlens-audit remediations --title shadow
```

## 🔍 Watchdog — 持续审计 / 漂移监控

审计不是一次性行为。Watchdog 子命令用于定期复检，对比当前审计结果与基线，发现新问题漂移。

### 建立基线（首次）

```bash
agentlens-audit watchdog --input events.jsonl --write-baseline baseline.json
```

### 对比报警

```bash
agentlens-audit watchdog --input events.jsonl --baseline baseline.json
```

### 漂移趋势历史（可选）

```bash
# 每次对比后追加一条当日记录（high 总数 / 新增 / 增长 / 成本），供 Web 趋势图使用
agentlens-audit watchdog --input events.jsonl --baseline baseline.json --history drift-history.json
```

### 退出码语义

| 退出码 | 含义 |
|:--|:--|
| 0 | 无新增 high severity finding，审计状态正常 |
| 1 | 存在新增 high severity finding，触发报警 |
| 2 | 输入错误（文件不存在、基线 JSON 非法等） |

### cron 调度示例

```bash
# 每 24 小时跑一次，输出到日志
0 0 * * * /usr/local/bin/agentlens-audit watchdog --input /data/events.jsonl --baseline /data/baseline.json >> /var/log/agentlens-watchdog.log 2>&1
```

## 📥 支持的输入

- **Hermes**：gateway.log 直接解析
- **CrewAI / AutoGen / LangGraph**：日志/追踪 → 统一事件流（见 `converters/`）
- **统一事件流 JSONL**：`{type, timestamp, source, payload, evidence_ref, event_id}`

## 📤 输出

- `--json`：结构化审计结果（七层）
- `--format html`：自包含 HTML 报告（无外链资源，可离线打开、可归档；SHA-256 哈希链防篡改）
- `diff`：基线对比 JSON/HTML
- `verify`：报告完整性验真（篡改 → exit 1）
- `regs`：法规映射查询（`--unknown` 聚合未映射 / `--annotate` 人工标注 / `--annotations` 列出）
- `remediations`：修复建议查询
- `budget`：成本预算告警（超阈值走 notify 通道）
- `--gate`：CI 退出码

## 🌐 Web 服务（0.3.0）

内置 FastAPI Web 平台：仪表盘 KPI + 趋势图、报告列表/详情/对比、触发审计、修复跟踪（标记已修复 + 回归验证）、合规标注、预算告警历史、Watchdog 漂移趋势图。

```bash
pip install agentlens-audit[web]

# 启动（默认 127.0.0.1:8000；生产建议加 Basic Auth 环境变量）
agentlens-audit serve --host 0.0.0.0 --port 8010
```

- 认证：设置 `AGENTLENS_WEB_USERNAME` / `AGENTLENS_WEB_PASSWORD` 环境变量后启用 Basic Auth；未设置则放行（仅限内网）
- 报告目录：`AGENTLENS_REPORT_DIR` 环境变量覆盖（默认 `~/.hermes/agentlens-reports`）
- 关键 API：`/api/reports` / `/api/audit/run` / `/api/findings/*` / `/api/watchdog`(+`/history`) / `/api/budget/alerts` / `/api/annotations`

## 🧪 测试

```bash
python -m pytest tests/ -v   # 246 用例全绿
```

## 📦 发布

- PyPI: https://pypi.org/project/agentlens-audit/
- GitHub: https://github.com/waiky-github/agentlens-cli
- License: MIT

## 🔌 MCP Server

AgentLens Audit 支持作为 MCP server 运行，任何 MCP 客户端（Claude / Cursor / Hermes）均可接入。

### 安装

```bash
pip install agentlens-audit[mcp]
```

### 客户端配置

**stdio 模式（推荐）**：

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

**HTTP 模式**：

```json
{
  "mcpServers": {
    "agentlens-audit": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

启动 HTTP 服务端：

```bash
python -m agentlens_cli.mcp_server --transport http --port 8765 --host 127.0.0.1
```

### 可用工具

| 工具 | 说明 |
|:--|:--|
| `audit` | 完整七层审计，返回 JSON（含 integrity 块） |
| `cost_analysis` | 成本分析（总成本 / 可避免成本 / 比例） |
| `verify_report` | 验报告完整性（防篡改哈希链） |
| `list_regulations` | 法规映射查询 |
| `watchdog_status` | Watchdog 基线状态（基线事件数 / 报告数） |
| `remediation_lookup` | 修复建议查询（按 finding title） |
| `fix_tracking_status` | 修复跟踪状态（verified / verifying / regressed） |

## 🙏 致谢

审计方法论源自 AgentLens（GOAI 新智基座赛道参赛作品），规则实现参考其 cost-governance / decision-audit / evidence-chain / graph-merge 等 SKILL 定义。

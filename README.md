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
| 📋 regulations | 合规条款映射 | 审计发现自动关联法规条款（网信办《实施意见》/ EU AI Act /《拟人化互动办法》） |
| 🚪 gate | CI 集成 | 违规超阈值 → 非零退出码，审计当 lint 挂 CI |

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
```

## 📥 支持的输入

- **Hermes**：gateway.log 直接解析
- **CrewAI / AutoGen / LangGraph**：日志/追踪 → 统一事件流（见 `converters/`）
- **统一事件流 JSONL**：`{type, timestamp, source, payload, evidence_ref, event_id}`

## 📤 输出

- `--json`：结构化审计结果（七层）
- `--format html`：自包含 HTML 报告（无外链资源，可离线打开、可归档）
- `diff`：基线对比 JSON/HTML
- `--gate`：CI 退出码

## 🧪 测试

```bash
python -m pytest tests/ -v   # 60 用例全绿
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

## 🙏 致谢

审计方法论源自 AgentLens（GOAI 新智基座赛道参赛作品），规则实现参考其 cost-governance / decision-audit / evidence-chain / graph-merge 等 SKILL 定义。

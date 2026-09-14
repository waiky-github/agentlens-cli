# AgentLens Audit — 30 分钟上手指南

> 目标：**30 分钟内**从安装到产出一份完整的多 Agent 审计报告。
> 适用人群：正在跑多 Agent 系统（CrewAI / AutoGen / LangGraph / Claude Code / opencode / 自研 Agent）的团队。

---

## 第 1 步：安装（2 分钟）

```bash
pip install agentlens-audit
```

- 纯 Python 标准库实现，**零第三方运行依赖**（Python ≥ 3.9 即可）
- 不需要数据库、不需要 Docker、不需要联网服务

验证安装：

```bash
agentlens-audit --version   # 期望输出 0.3.1
```

## 第 2 步：最快看到效果 — 一键演示报告（3 分钟）

```bash
agentlens-audit demo --output report.html
```

浏览器打开 `report.html`，你会看到：

- **顶部速览**：6 个 KPI 卡（发现总数 / 预估浪费 / 影子智能体 / 审批绕过 / 可避免占比 / 闭环率）+ 3 张图表
- **七层审计结果**：graph 协作图谱 / decision 决策审计 / evidence 证据链 / cost 成本治理 / shadow 影子智能体 / compliance 决策权限合规 / gate CI 门禁
- **合规条款映射**：每个发现自动关联法规条款（网信办《智能体规范应用与创新发展实施意见》+ EU AI Act + OWASP LLM Top 10 2026 + Agentic Top 10 + ACS 2026）
- **修复建议**：每条发现的 action + detail + priority

报告是**自包含 HTML**（无外链资源），可以离线打开、归档、发给同事。

## 第 3 步：审计你自己的系统（15 分钟）

AgentLens Audit 接受四种输入，挑一种最贴近你的：

| 你的系统 | 输入方式 | 命令示例 |
|:--|:--|:--|
| **Hermes** | 直接解析 gateway.log | `agentlens-audit audit --input gateway.log --format html --output report.html` |
| **CrewAI** | 日志 → 统一事件流 | `agentlens-audit audit --input crewai_trace.jsonl --format html --output report.html` |
| **AutoGen / LangGraph** | 日志 → 统一事件流 | 同上（见 `converters/` 转换脚本） |
| **任意框架** | 统一事件流 JSONL | `{type, timestamp, source, payload, evidence_ref, event_id}` |

小贴士：
- 第一次先跑 `--json` 看结构化结果，再跑 `--format html` 出报告
- 事件流不用很规整，缺字段的会自动跳过并计数

### 三个立刻能用的命令

```bash
# 1. 完整审计 + HTML 报告
agentlens-audit audit --input events.jsonl --format html --output report.html

# 2. 成本专项：谁最烧钱、哪里浪费
agentlens-audit cost --input events.jsonl --json

# 3. 查合规映射 / 修复建议
agentlens-audit regs --title approval        # 审批相关发现映射了哪些法规
agentlens-audit remediations --title shadow  # 影子智能体怎么修
```

## 第 4 步：把审计变成流程（10 分钟）

### CI 门禁 — 审计当 lint 挂 CI

```bash
# high 级违规数 > 0 即非零退出，CI 直接拦
agentlens-audit audit --input events.jsonl --gate --fail-on high
```

### 持续监控 — 定期复检，发现新问题漂移

```bash
# 建基线（首次）
agentlens-audit watchdog --input events.jsonl --write-baseline baseline.json

# 定期对比（如每天 cron）
agentlens-audit watchdog --input events.jsonl --baseline baseline.json
# 退出码：0=正常 / 1=有新增 high 问题 / 2=输入错误
```

### Web 仪表盘（可选，团队协作用）

```bash
pip install agentlens-audit[web]
agentlens-audit serve --host 0.0.0.0 --port 8010
```

浏览器打开仪表盘：报告列表 / 对比 / 触发审计 / 修复跟踪（标记已修复 + 连续 3 次验证才 verified）/ 合规标注 / 预算告警 / 漂移趋势图。

### MCP 接入（可选，给 AI 编程工具用）

```bash
pip install agentlens-audit[mcp]
```

7 个 MCP 工具（audit / cost_analysis / verify_report / list_regulations / watchdog_status / remediation_lookup / fix_tracking_status），可接入 Claude Code / Cursor / Hermes 等任意 MCP 客户端。

---

## 常见问题（30 分钟内遇到问题先看这里）

| 问题 | 解决 |
|:--|:--|
| `agentlens-audit` 命令找不到 | 检查 Python 版本 ≥ 3.9；`python -m agentlens_cli --version` 试一下 |
| 报告里全是 unknown 合规映射 | 运行 `agentlens-audit regs --unknown --report report.html` 查看未映射列表；可用 `--annotate` 人工标注 |
| 审计耗时 | 事件流越大越慢；10 万事件约 1-2 分钟（纯本地计算，无网络请求） |
| 报告打不开 | 确认文件是自包含 HTML；直接用浏览器双击打开 |
| 数据安全 | 审计完全本地运行，数据不出机器；报告可离线归档、可验真（`verify --report` 防篡改） |

---

## 下一步

- 完整文档：`README.md`（功能特性 / 全部命令 / Watchdog / 输出格式）
- 真实样例：`docs/example-report.html`（完整审计报告，integrity VERIFIED）
- 有问题：GitHub Issues（模板见 `.github/ISSUE_TEMPLATE/`）

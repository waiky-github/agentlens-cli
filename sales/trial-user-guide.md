# AgentLens Audit 使用说明（30 分钟版）

> 给朋友的一份快速上手文档。有问题直接回我，或者提 GitHub Issue（模板已配好）。

---

## 1. 这是什么

一句话：**把你的多 Agent 系统（CrewAI / AutoGen / LangGraph / Claude Code / 自研 Agent）的协作过程变成一份完整审计报告**——谁拆的任务、为什么这么派、调了哪些工具、花了多少钱、出了事能不能追责。

自带**合规条款映射**：每个审计发现自动关联法规（网信办《智能体规范应用与创新发展实施意见》2026-05 + EU AI Act + OWASP LLM Top 10 2026 + Agentic Top 10 + ACS 2026）。

同类工具大多只做「观测」（看日志），它做「审计」（查问题 + 合规举证），而且**框架中立**、**纯本地运行**（数据不出机器）。

## 2. 安装（2 分钟）

```bash
pip install agentlens-audit
```

- 纯 Python 标准库实现，**零第三方运行依赖**（Python ≥ 3.9 就行）
- 不需要数据库、不需要 Docker、不需要联网服务

验证：

```bash
agentlens-audit --version   # 看到 0.3.0 就对了
```

## 3. 30 秒看效果（demo）

```bash
agentlens-audit demo --output report.html
```

浏览器双击打开 `report.html`，你会看到：

- **顶部速览**：6 个 KPI 卡（发现总数 / 预估浪费 / 影子智能体 / 审批绕过 / 可避免占比 / 闭环率）+ 3 张图表
- **七层审计结果**：协作图谱 / 决策审计 / 证据链 / 成本治理 / 影子智能体 / 决策权限合规 / CI 门禁
- **合规条款映射**：每个发现关联了哪些法规条款
- **修复建议**：每条发现的 action + detail + priority

报告是**自包含 HTML**（无外链资源），能离线打开、能归档、能发给同事。

## 4. 审计你自己的系统（15 分钟）

按你的系统选一种输入：

| 你的系统 | 怎么做 |
|:--|:--|
| **Hermes** | 直接解析 gateway.log：`agentlens-audit audit --input gateway.log --format html --output report.html` |
| **CrewAI / AutoGen / LangGraph** | 日志转统一事件流 JSONL（仓库 `converters/` 有转换脚本），再 audit |
| **任意框架** | 统一事件流 JSONL：`{type, timestamp, source, payload, evidence_ref, event_id}` |

三个高频命令：

```bash
# 完整审计 + HTML 报告
agentlens-audit audit --input events.jsonl --format html --output report.html

# 成本专项：哪个 Agent 最烧钱、哪里浪费
agentlens-audit cost --input events.jsonl --json

# 查合规映射 / 修复建议
agentlens-audit regs --title approval
agentlens-audit remediations --title shadow
```

小贴士：事件流不用很规整，缺字段的会自动跳过并计数；第一次先跑 `--json` 看结构化结果更直观。

## 5. 把审计变成流程（可选，10 分钟）

**CI 门禁**（审计当 lint 挂 CI）：

```bash
# high 级违规数 > 0 就非零退出，CI 直接拦
agentlens-audit audit --input events.jsonl --gate --fail-on high
```

**持续监控**（定期复检，发现新问题漂移）：

```bash
# 首次建基线
agentlens-audit watchdog --input events.jsonl --write-baseline baseline.json
# 之后定期对比（可挂 cron）
agentlens-audit watchdog --input events.jsonl --baseline baseline.json
# 退出码：0=正常 / 1=有新增 high 问题 / 2=输入错误
```

**Web 仪表盘**（团队协作可选）：

```bash
pip install agentlens-audit[web]
agentlens-audit serve --host 0.0.0.0 --port 8010
```

**MCP 接入**（给 AI 编程工具用，可选）：

```bash
pip install agentlens-audit[mcp]
# 7 个工具，可接入 Claude Code / Cursor / Hermes 等 MCP 客户端
```

## 6. 常见问题

| 问题 | 解决 |
|:--|:--|
| 命令找不到 | Python ≥ 3.9；或 `python -m agentlens_cli --version` |
| 报告里合规映射是 unknown | `agentlens-audit regs --unknown --report report.html` 看未映射列表，可人工标注 |
| 审计慢不慢 | 纯本地计算无网络请求，10 万事件约 1-2 分钟 |
| 数据安全 | 完全本地运行，数据不出机器；报告可验真防篡改（`verify --report`） |

## 7. 反馈

- **GitHub Issues**：https://github.com/waiky-github/agentlens-cli/issues （Bug / 功能建议模板已配好）
- 或者直接找【你的名字】——我们正在找种子用户，**你的反馈会直接影响产品方向**

祝玩得开心 🚀

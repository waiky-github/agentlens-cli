# agentlens-audit 产品一页纸

> **版本 0.3.0 | PyPI 已发布 | GitHub: waiky-github/agentlens-cli**

---

## 一句话价值主张

**让多 Agent 系统的每一次协作都可见、可审、可复盘——一条命令，完整审计报告。**

---

## 为什么需要 agentlens-audit？

多 Agent 系统（CrewAI、AutoGen、LangGraph、Hermes 等）在生产环境跑起来后，团队普遍面临三个「黑盒」问题：

| 痛点 | 具体表现 |
|------|---------|
| **协作过程不可见** | 谁拆的任务？为什么派给这个 Agent？中间调了哪些工具？出了事无法回溯，出了问题找不到责任人。 |
| **成本失控** | 重复调用、无效循环、大输出浪费——实测可避免成本浪费 **63-76%**，但没有工具能自动发现。 |
| **合规无据** | 监管要求来了（网信办、EU AI Act、OWASP），但 Agent 决策链路没有审计记录，合规举证靠人工翻日志。 |

---

## 核心卖点：七层审计，一条命令

```
agentlens-audit audit --input events.jsonl --output report.html
```

| 审计层 | 做什么 | 解决什么问题 |
|--------|--------|-------------|
| **Graph 协作图谱** | 任务全链路还原，可视化依赖关系 | "这个任务到底经过了哪些 Agent？" |
| **Decision 决策审计** | 审批链合规检查 | "谁批准的？流程对吗？" |
| **Evidence 证据链** | 结论可回溯，每步有据可查 | "这个输出是怎么来的？" |
| **Cost 成本治理** | 按 Agent 成本归因 + 浪费检测 | "哪个 Agent 最烧钱？哪里浪费了？" |
| **Shadow 影子智能体** | 未登记 Agent / 未授权工具调用 | "有没有我不知道的 Agent 在跑？" |
| **Compliance 决策权限合规** | 用户本人决策/用户授权/自主决策三分法 + 知情权 + 最终否决权 | "Agent 的决策有没有越权？" |
| **Gate CI 门禁** | 违规超阈值非零退出码 | "CI 能不能自动拦住不合规的 Agent 行为？" |

---

## 不只是审计——全套治理能力

| 扩展能力 | 说明 |
|----------|------|
| **Regulations 合规条款映射** | 审计发现自动关联法规：网信办《智能体规范应用与创新发展实施意见》(2026-05) + EU AI Act + 《拟人化互动办法》 + OWASP LLM Top 10 2026 + OWASP Agentic Top 10 (ASI) + ACS 2026 |
| **Annotations 人工合规标注** | 未映射/需纠正的 finding 支持人工标注，人工判定优先于静态表 |
| **Budget 成本预算告警** | 单次审计总成本/预估浪费超阈值 → 推飞书/webhook/命令，含历史记录 |
| **Leakage 系统提示泄露检测** | OWASP LLM08 Hidden Context Exposure，内容级强检测 + 超大输出元数据弱信号 |
| **Verify 修复回归验证** | mark-fixed 后连续 3 次审计缺席才 verified，复发即 regressed（防假修复） |
| **Watchdog 持续审计漂移监控** | 定期复检对比基线，发现新问题漂移，cron 可调度，含多日漂移趋势历史 |
| **Web 平台** | FastAPI 仪表盘 + 报告查看 + 触发审计 + 修复跟踪 + 合规标注 + 预算告警 + 趋势图（Basic Auth 保护） |
| **MCP Server** | 7 个工具，可接入任意 MCP 客户端（Claude Code / Cursor / Hermes） |
| **Integrity 报告防篡改** | SHA-256 文档哈希链，verify 验真，篡改即报错 |
| **Remediation 修复建议** | 每类 finding 配具体修复建议（action + detail + priority） |

---

## 差异化优势

| 对比维度 | agentlens-audit | 同类工具 |
|----------|----------------|---------|
| **定位** | 审计 + 合规 + 治理 | 观测/追踪（不做审计） |
| **框架绑定** | 框架中立，不绑定任何 Agent 框架 | 多数绑定单一框架 |
| **审计深度** | 七层审计 | 无或仅 1-2 层 |
| **法规对齐** | 中国网信办 + 国际 OWASP 双对齐 | 无法规映射 |
| **输入兼容** | 统一事件流 JSONL / Hermes gateway.log / CrewAI / AutoGen / LangGraph | 通常仅支持单一格式 |

---

## 技术亮点

- **零第三方运行依赖**：纯 Python stdlib（≥ 3.9），装完就能跑
- **跨平台**：Linux / macOS / Windows
- **自包含 HTML 输出**：审计报告可离线打开、归档，无外链资源
- **结构化输出**：`--json` 输出可供下游系统消费
- **CI 集成**：`--gate` 非零退出码，直接接入 CI/CD 流水线

---

## 快速上手（3 条命令）

```bash
# 1. 安装
pip install agentlens-audit

# 2. 对事件流做一次完整审计，输出自包含 HTML 报告
agentlens-audit audit --input events.jsonl --output report.html

# 3. CI 门禁模式：违规超阈值直接阻断
agentlens-audit audit --input events.jsonl --gate
```

---

## 验证数据

- **246 个测试全绿**，覆盖七层审计全部逻辑
- 实测可避免成本浪费 **63-76%**（大输出注入 / 重复调用浪费检测）
- 完整审计 11268 事件 → 727 findings 验真通过（VERIFIED），合规映射 0 unknown
- 生产环境每日 03:00 自动审计 + 漂移推飞书已稳定运行

---

## 下一步

- **开源地址**：https://github.com/waiky-github/agentlens-cli
- **PyPI**：`pip install agentlens-audit`
- **版本**：0.3.0
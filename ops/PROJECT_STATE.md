# agentlens-audit 项目现状（PROJECT_STATE.md — 唯一事实源）

> 更新纪律：每次查完现状/做完重要事项后必须更新本文件并 commit。
> 本文件为 agentlens-cli / agentlens-audit（多 Agent 协作审计 CLI）项目的唯一事实源。

## 项目定位
- **agentlens-audit**：多 Agent 协作审计命令行工具（商业化独立项目）
- 源自 AgentLens（GOAI 新智基座赛道参赛作品，未进复赛），将审计方法论固化为确定性 CLI
- 差异化：跨平台/框架中立 + 七层审计 + 政策对齐（网信办《智能体规范应用与创新发展实施意见》2026-05）
- 关联：上游方法论在 `~/goai-competition/06-agentlens/`（只读参考，本仓库不复用其运行代码）

## 发布状态（2026-09-08/09 完成 ✅）
| 平台 | 状态 | 地址 |
|:--|:--|:--|
| **PyPI** | ✅ agentlens-audit **0.2.1**（最新；0.2.0 已废弃），pip install agentlens-audit[mcp] 端到端验证通过 | pypi.org/project/agentlens-audit/ |
| **GitHub** | ✅ 仓库 waiky-github/agentlens-cli（公开），代码经 API 上传在线 | github.com/waiky-github/agentlens-cli |
| GitHub git 历史 | ⚠️ 未 push（github.com:443 被墙，api.github.com 通）→ 待网络恢复/代理后 git push 补历史 | — |

## 功能现状（七层审计 + 扩展）
- 输入：统一事件流 JSONL / Hermes gateway.log / CrewAI / AutoGen / LangGraph（converters/）
- 七层：graph 协作图谱 / decision 决策审计 / evidence 证据链 / cost 成本治理 / shadow 影子智能体 / compliance 决策权限合规 / gate CI 门禁
- 命令：audit（--json / --format html）/ cost / diff（baseline vs current）/ demo / verify（防篡改验真）/ regs（法规映射查询）/ remediations（修复建议查询）/ watchdog（持续审计漂移监控）/ --gate（退出码）
- 扩展功能（2026-09-08/09 全部完成并验真）：
  - **N1 报告防篡改**：integrity.py，SHA-256 文档哈希 + 哈希链，verify 子命令验真（篡改 exit 1）
  - **N3 合规条款映射**：regulations.py，439 findings 映射网信办《实施意见》/EU AI Act/拟人化办法，HTML 第 7 节汇总表
  - **N2 MCP server**：mcp_server.py，FastMCP 4 工具（audit/cost_analysis/verify_report/list_regulations），stdio + streamable-http 双传输，0.2.1[mcp] 全新环境实测注册成功
  - **watchdog 持续审计**：watchdog.py，建基线→定期复检→发现「新增问题漂移」，退出码 0/1/2 报警语义，cron 可调度（含「已有 high 数量增长」漏报修复）
  - **remediation 修复建议**：remediation.py，每类 finding 配具体修复建议（action+detail+priority），439 findings 全覆盖；HTML 每条 finding 加修复建议区块 + 第 8 节修复优先级汇总
- 文档：README（含 verify/regs/remediations/watchdog，测试数 60→120）+ README.en.md（英文对外版）+ docs/example-report.html（真实样例报告，integrity VERIFIED）
- 测试：tests/ pytest **120 用例全绿**（公共 venv /home/agentuser/.hermes/hermes-agent/venv/bin/python -m pytest tests/ -q）

## 关键事实（避免重踩）
- **PyPI 包名 `agentlens-cli` 已被他人占用**（发布 403）→ 改名 `agentlens-audit`（2026-09-08 实测 404 可用后发布）
- **Trae 写的 pyproject build-backend 是编造路径**（setuptools.backends._legacy）→ 构建失败，已修为 `setuptools.build_meta:__legacy__`
- **github.com:443 被墙但 api.github.com 通**（2026-09-08 实测）→ GitHub 仓库创建/文件上传走 API；git push 需等网络恢复或代理
- **PyPI token 复用 CrawlEyes 的 .pypirc**（twine env 方式；单文件 twine upload 成功，dist/* 通配符曾 403——疑似 glob 问题，用单文件/显式路径）
- 服务器无 gh CLI、无 twine（在 crawl/.venv 与 crawl-public/.venv）

## 关键凭证/工具
- PyPI token：`~/.pypirc`（600，username=__token__，password 180 字符，2026-09-08 发布 agentlens-audit 验证可用）
- GitHub PAT：`~/.git-credentials`（waiky-github 40 位，classic PAT，2026-09-08 建仓库+API 上传验证可用）
- twine/build：`/home/agentuser/crawl/.venv/bin/`（twine ✅；build 已装 ✅）

## 环境依赖
- 运行：纯 stdlib（Python ≥3.9），无第三方运行依赖
- 测试：pytest 9.0.2（公共 venv `/home/agentuser/.hermes/hermes-agent/venv/`）
- 构建：crawl/.venv（setuptools/build/twine）

## 待办
- [ ] GitHub git 历史 push（等网络恢复/代理：`git remote add origin https://github.com/waiky-github/agentlens-cli.git && git push -u origin main`，需 http.version HTTP/1.1 已全局设）
- [ ] 版本 0.3.0（watchdog/remediation 已入 0.2.1，视用户/市场反馈迭代）
- [ ] 销售材料（用户已认可方向：先功能后宣传，功能开发完成后再做 BD）

## 里程碑
- 2026-09-08：agentlens-cli 从零到发布（Trae 4 轮任务 + 我验真 + 7 功能批次，10 次 commit）
- 2026-09-08：PyPI agentlens-audit 0.1.0 发布 + GitHub 仓库上线 + 60 测试全绿
- 2026-09-08：N1 报告防篡改（92c17bb）+ N3 合规条款映射（aadfb80，75 测试）+ N2 MCP server（caffd3c，4 工具 stdio/http 双传输）全部完成并验真
- 2026-09-08/09：三项优化 100% 闭环——方向1 发布 0.2.1（含 0.2.0 双 bug 修复 + README.en + 示例报告）/ 方向2 watchdog 漂移监控（含漏报修复，04a87b8）/ 方向3 remediation 修复建议（1503800）；120/120 测试全绿，0.2.1[mcp] 全新环境验证过

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
  - **报告仪表盘**（2026-09-09）：report.py 顶部「一页速览」——6 KPI 卡（发现总数/预估浪费/影子/审批绕过/可避免占比/闭环率）+ 3 张 ECharts 图（严重度分布环形图/Top10 浪费条形图/Agent 成本+Token 双轴图），ECharts CDN + 三重 resize 兜底 + 动画禁用（静态全貌）
  - **Web 服务**（2026-09-09，e3eba58 → 0aeb44c UI 重构）：`agentlens-audit serve --host 0.0.0.0 --port 8010`，FastAPI 完整 API + 操作界面。REST：/api/reports（列表+元信息）/ /api/reports/{date}/html（原始报告）/ POST /api/audit/run（触发审计）/ /api/watchdog（漂移状态）/ **/api/reports/trends**（多报告聚合趋势数据）。页面（Langfuse 式深色主题）：左侧 sidebar + 顶部时间范围选择器 + 仪表盘（6 KPI 带 sparkline + 成本趋势双轴图 + 严重度环形图 + 最新报告摘要 + Watchdog 状态 + 最近审计动态）/ 报告列表（排序/搜索）/ 独立审计页（表单 + 运行状态 + 最近任务）/ 报告详情（iframe 全宽 + 顶部工具条）。pyproject 新增 [web] optional（fastapi+uvicorn）+ Basic Auth 中间件（环境变量注入，未设置则放行）
- 文档：README（含 verify/regs/remediations/watchdog，测试数 60→120）+ README.en.md（英文对外版）+ docs/example-report.html（真实样例报告，integrity VERIFIED）
- 测试：tests/ pytest **142 用例全绿**（公共 venv /home/agentuser/.hermes/hermes-agent/venv/bin/python -m pytest tests/ -q）

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
- 运行：纯 stdlib（Python ≥3.9），无第三方运行依赖；Web 服务需 fastapi+uvicorn（pyproject [web] optional）
- 测试：pytest 9.0.2（公共 venv `/home/agentuser/.hermes/hermes-agent/venv/`）
- 构建：crawl/.venv（setuptools/build/twine）
- 持久 venv：`/home/agentuser/agentlens-venv`（agentlens-audit 本地源码 --no-deps 安装，含 P2 修复 + dashboard + web，2026-09-09 重装）

## 持久化部署（2026-09-09 全部 active）
| systemd user unit | 作用 | 状态 |
|:--|:--|:--|
| agentlens-audit.timer（→agentlens-audit.service） | 每天 03:00 增量审计近 1 天 gateway 日志（5 个 profile 合并）→ HTML 报告 + watchdog 基线；漂移退出码 1 + **推飞书**（hermes send） | enabled + active |
| agentlens-web.service | `serve --host 0.0.0.0 --port 8010`，Web 仪表盘 + 报告查看 + 触发审计 API；**Basic Auth**（admin + 随机密码，凭据文件 ~/.hermes/agentlens-web-cred 600，EnvironmentFile 注入） | enabled + active |
- 报告目录：`~/.hermes/agentlens-reports/`（audit-YYYYMMDD.html + baseline.json）
- 转换器：scripts/convert_gateway_log.py（丢弃 msg 原文、用户 ID→user:unknown）；调度：scripts/run_daily_audit.sh（DAYS=1，漂移分支 hermes send -t feishu）
- 端口：liuyao 8000 / agentlens-web 8010 / agentlens-mcp 8765 / hermes-stats 3001

## 待办
- [ ] GitHub git 历史 push（等网络恢复/代理：`git remote add origin https://github.com/waiky-github/agentlens-cli.git && git push -u origin main`，需 http.version HTTP/1.1 已全局设）
- [ ] 版本 0.3.0（watchdog/remediation 已入 0.2.1，Web 服务待发版；视用户/市场反馈迭代）
- [ ] 销售材料（用户已认可方向：先功能后宣传，功能开发完成后再做 BD）
- [ ] Web 服务版本号/README 更新（serve 子命令 + [web] 安装说明）
- [ ] 将最新分层报告重新生成进报告目录（~/.hermes/agentlens-reports/audit-YYYYMMDD.html），替换旧版未分层报告，让正式服务详情页展示分层导航

## 里程碑
- 2026-09-08：agentlens-cli 从零到发布（Trae 4 轮任务 + 我验真 + 7 功能批次，10 次 commit）
- 2026-09-08：PyPI agentlens-audit 0.1.0 发布 + GitHub 仓库上线 + 60 测试全绿
- 2026-09-08：N1 报告防篡改（92c17bb）+ N3 合规条款映射（aadfb80，75 测试）+ N2 MCP server（caffd3c，4 工具 stdio/http 双传输）全部完成并验真
- 2026-09-08/09：三项优化 100% 闭环——方向1 发布 0.2.1（含 0.2.0 双 bug 修复 + README.en + 示例报告）/ 方向2 watchdog 漂移监控（含漏报修复，04a87b8）/ 方向3 remediation 修复建议（1503800）；120/120 测试全绿，0.2.1[mcp] 全新环境验证过
- 2026-09-09：自治理闭环（21feb09）——P0 阈值调低（tool_output 50000→20000）+ P2 影子误报清零（user:* 前缀豁免）+ 工具调用节流纪律；持久化部署（每天 03:00 审计 + 漂移推飞书）
- 2026-09-09：报告仪表盘 + Web 服务（e3eba58）——ECharts 一页速览 + serve 完整 API/操作界面，139/139 测试全绿，systemd agentlens-web 常驻 8010 端口

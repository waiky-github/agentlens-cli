# agentlens-audit 项目现状（PROJECT_STATE.md — 唯一事实源）

> 更新纪律：每次查完现状/做完重要事项后必须更新本文件并 commit。
> 本文件为 agentlens-cli / agentlens-audit（多 Agent 协作审计 CLI）项目的唯一事实源。

## 项目定位
- **agentlens-audit**：多 Agent 协作审计命令行工具（商业化独立项目）
- 源自 AgentLens（GOAI 新智基座赛道参赛作品，未进复赛），将审计方法论固化为确定性 CLI
- 差异化：跨平台/框架中立 + 七层审计 + 政策对齐（网信办《智能体规范应用与创新发展实施意见》2026-05）
- 关联：上游方法论在 `~/goai-competition/06-agentlens/`（只读参考，本仓库不复用其运行代码）

## 发布状态（2026-09-08 完成 ✅）
| 平台 | 状态 | 地址 |
|:--|:--|:--|
| **PyPI** | ✅ agentlens-audit 0.1.0（whl + tar.gz，pip install 验证通过，命令可用） | pypi.org/project/agentlens-audit/ |
| **GitHub** | ✅ 仓库 waiky-github/agentlens-cli（公开），33 文件经 API 上传在线 | github.com/waiky-github/agentlens-cli |
| GitHub git 历史 | ⚠️ 未 push（github.com:443 被墙，api.github.com 通）→ 待网络恢复/代理后 git push 补历史 | — |

## 功能现状（七层审计）
- 输入：统一事件流 JSONL / Hermes gateway.log / CrewAI / AutoGen / LangGraph（converters/）
- 七层：graph 协作图谱 / decision 决策审计 / evidence 证据链 / cost 成本治理 / shadow 影子智能体 / compliance 决策权限合规 / gate CI 门禁
- 命令：audit（--json / --format html）/ cost / diff（baseline vs current）/ demo / --gate（退出码）
- 测试：tests/ pytest 60 用例全绿（公共 venv python -m pytest tests/ -v）

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
- [ ] README 英文版（可选，对外分发用）
- [ ] F6 合规条款映射（延后，发政策解读文时一起做）
- [ ] 版本 0.2.0（视反馈迭代）

## 里程碑
- 2026-09-08：agentlens-cli 从零到发布（Trae 4 轮任务 + 我验真 + 7 功能批次，10 次 commit）
- 2026-09-08：PyPI agentlens-audit 0.1.0 发布 + GitHub 仓库上线 + 60 测试全绿

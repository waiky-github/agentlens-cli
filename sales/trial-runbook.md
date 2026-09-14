# AgentLens 种子用户试用 · 邀请人操作手册

> 这份是给**你（邀请人）**看的流程手册。素材已全部备好，照着走就行。
> 朋友拿到手看的是 `trial-user-guide.md`，你不用改任何东西，直接发。

---

## 0. 素材清单（都在仓库 sales/ 和 docs/ 下）

| 素材 | 文件 | 什么时候用 |
|:--|:--|:--|
| 邀请文案 A/B | `sales/trial-invite.md` | 发邀请时，复制改占位 |
| 朋友使用说明（30 分钟版） | `sales/trial-user-guide.md` | 朋友答应后，直接发这个文件 |
| 完整上手指南 | `docs/QUICKSTART.md` | 朋友想深入研究时再看 |
| 反馈问卷 | `sales/trial-feedback-form.md` | 试用完收集结构化反馈 |
| Issues 模板 | `.github/ISSUE_TEMPLATE/` | 让朋友提 bug / 功能建议 |
| 真实样例报告 | `docs/example-report.html` | 邀请时甩给朋友先感受效果 |

---

## 第 1 步：挑目标（30 秒）

- ✅ 适合的人：正在跑多 Agent 的团队或个人（CrewAI / AutoGen / LangGraph / Claude Code / opencode / 自研 Agent）
- ✅ 最容易出价值的：**真的在生产/项目里跑 Agent 的人**，不是围观群众
- 🎯 建议从 1-2 个真实跑 Agent 的朋友开始，别广撒网——种子期要的是深度反馈不是数量

候选池（你定）：你的 Agent 圈子 / Trae 朋友 / 社区。

---

## 第 2 步：发邀请（3 分钟）

1. 打开 `sales/trial-invite.md`
2. 复制 **文案 A**（熟人/私聊）或 **文案 B**（正式渠道/群公告）
3. 替换 4 个占位：【团队名】【微信号】【你的名字】【联系方式】
4. 附上 2 个链接：
   - GitHub：`https://github.com/waiky-github/agentlens-cli`
   - 样例报告：仓库 `docs/example-report.html`（也可把文件直接发给他，自包含 HTML 双击就能开）

> 如果朋友问「是什么」→ 一句话版：一条命令把 Agent 系统的协作过程变成审计报告，谁拆任务、为什么这么派、花了多少钱、出事了能不能追责，还自动关联合规条款。

---

## 第 3 步：朋友上手（朋友自己花 30 分钟，你不用陪）

朋友答应后，直接把 `sales/trial-user-guide.md` 发给他，里面是完整流程，核心就 3 条命令：

```bash
pip install agentlens-audit        # 安装（零第三方依赖）
agentlens-audit demo --output report.html   # 30 秒看演示报告
agentlens-audit audit --input 你的日志/事件流 --format html --output report.html   # 审自己的系统
```

- 朋友卡住 → 让他先看 guide 第 6 节常见问题；还卡住就直接微信问你/你转我
- 朋友没现成事件流 → 让他跑 `demo` 也够感受了；或者发我们的真实案例报告

---

## 第 4 步：收集反馈

三种方式按朋友习惯选：

1. **直接聊**（朋友场景最自然）—— 重点问一个问题：「报告里哪条对你最有价值 / 哪条最没用？」
2. **GitHub Issues** —— 让朋友提 bug / 功能建议（模板已配好）
3. **反馈问卷** —— 试用 30-60 分钟后填 `sales/trial-feedback-form.md`，5 分钟，结构化 15 题

> 种子期最想收集的 3 类信息：① 报告里哪层/哪条发现最有价值 ② 哪里看不懂/没用 ③ 你会真金白银用在哪（CI / 定期审计 / 成本治理 / 合规举证）

---

## 第 5 步：反馈回来后，我这边跟进

你收到任何反馈（微信截图 / 问卷 / Issue 链接）→ 直接丢到飞书给我，我负责：

1. 记录到 `ops/PROJECT_STATE.md` 待办（带来源标注）
2. 评估价值 → 排进迭代优先级
3. 修完/做完 → 通知对应试用者，形成闭环
4. 收集满 3 家以上反馈后，汇总成「种子用户反馈报告」给你

---

## 你只需要做 3 件事（最小行动）

1. 📋 把候选名单给我（或你直接发邀请，都行）
2. 📤 把 `trial-user-guide.md` 发给答应试的朋友
3. 🔁 把朋友反馈转给我

---

## 朋友高频问题速答

| 朋友问 | 你答 |
|:--|:--|
| 收费吗 | 开源免费，种子用户永久免费；后续企业版功能才收费，种子用户有优惠 |
| 和 LangSmith/Langfuse 啥区别 | 它们做观测（看），我们做审计（查 + 合规举证）；它们绑定各自框架，我们框架中立；它们没有法规映射 |
| 数据安全 | 完全本地运行，数据不出机器，报告可离线可验真防篡改 |
| 装不上 / 命令找不到 | Python ≥ 3.9；或 `python -m agentlens_cli --version` |
| 我没有标准事件流 | 先跑 `demo`；或用仓库 `converters/` 把你的框架日志转成 JSONL |
| 报告里合规全是 unknown | `agentlens-audit regs --unknown --report report.html` 看未映射列表，可人工标注 |

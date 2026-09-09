# Hermes 自审计治理方案（agentlens-audit 自举治理）

> 日期：2026-09-09
> 数据：examples/hermes_gateway_events.jsonl（11268 行真实 Hermes 网关日志，2026-05 时段）
> 工具：agentlens-audit 0.2.1 七层审计
> 状态：**待用户拍板后执行**（A 方案——先出方案再动手）

---

## 一、审计结果总览

| 指标 | 数值 |
|:--|:--|
| 总发现 | 439 条 |
| 估算总成本 | 846.27 CNY |
| 成本层 | 435 条（189 high / 244 med / 1 low / 1 info） |
| 影子智能体 | 4 条（3 high / 1 info） |

**Top 问题类型：**
1. `large-output tool injection ungoverned` × 203（62 high + 141 med）——工具输出无上限注入上下文
2. `session-level context bloat: no deliberate compaction` × 127（全 high）——会话不压缩
3. `repeated calls to same high-output tool` × 95（全 med）——同工具重复调用
4. `SHADOW_AGENT_DETECTED` × 3（high）——未注册 agent

---

## 二、关键校准：哪些已被当前配置治理，哪些仍可治

### ⚠️ 先决事实（2026-09-09 实测）

审计数据是 **2026-05 的日志**，而 **Hermes 当前配置已经有一部分治理**：

| 配置项 | 当前值 | 是否覆盖审计问题 |
|:--|:--|:--|
| `compression.enabled` | true（全部 4 个 profile） | ✅ 已开：上下文压缩已启用（threshold 0.5 / target_ratio 0.2 / protect_last_n 20） |
| `tool_output.max_bytes` | 50000 | ✅ 有上限：工具输出 50KB 截断 |
| `tool_output.max_lines` | 2000 | ✅ 有上限 |
| `file_read_max_chars` | 100000 | ✅ 有上限：read_file 100KB |

**结论：问题 1（大输出）和问题 2（上下文膨胀）在配置层面已有兜底，但阈值可能仍偏高**（详见下）。

---

## 三、治理项清单（按优先级）

### 🔴 P0-1：工具输出阈值偏高 —— 建议调低

**现状**：`tool_output.max_bytes = 50000`（50KB）。审计阈值 `LARGE_OUTPUT_THRESHOLD = 10000` chars（约 2.5K token）。
**问题**：50KB 上限仍 > 审计认定的 10K 字符浪费线；skill_view/session_search 一次可返回数万字符。
**治理动作**：
- 主 config + 4 个 profile：`tool_output.max_bytes` 50000 → **20000**（约 5K token）
- `file_read_max_chars` 100000 → **50000**
- 保留 max_lines 2000（防截断破坏结构）
**预期收益**：单次大输出注入 token 减半以上；203 条发现中的注入字符量直接下降
**风险**：低（只在输出层截断，不影响工具本身功能；长文件改用分段读）

### 🟡 P0-2：会话压缩阈值 —— 确认已生效即可

**现状**：`compression.threshold = 0.5`（上下文用 50% 触发压缩），target_ratio 0.2。
**问题**：审计报「无刻意压缩」是 5 月状态；当前已开。需要**验证压缩真的在工作**（看 gateway 日志有无 compression 事件）。
**治理动作**：
- 验证：`grep -i "compress" ~/.hermes/logs/gateway.log | tail -20`，确认近期有压缩发生
- 若长期无压缩事件：threshold 0.5 → 0.4（更早触发），或检查 compression provider 是否可用
**预期收益**：127 条 high 的根源（上下文膨胀）被兜住
**风险**：低（压缩已有默认配置，只是调参/验证）

### 🟢 P1：重复调用治理 —— 使用习惯，无需改配置

**现状**：`repeated calls to same high-output tool` × 95（skill_view 165 次、skills_list 13 次等）。
**根因**：同一会话内反复读同一 skill / 反复列技能，无缓存复用。
**治理动作**：不改配置，靠**使用纪律** + skill 更新：
- 同一会话内 skill_view 同一文件只读 1 次，后续靠记忆
- skills_list 结果记住，不重复拉
- 相关 skill（如 commit-pre-flight / hermes-agent）补充「勿重复加载」提醒
**预期收益**：减少约 100 次冗余工具调用，token 节省可观
**风险**：无（纯行为调整）

### ⚪ P2：影子智能体 —— 已确认非真实威胁

**现状**：`SHADOW_AGENT_DETECTED` × 3，agent 名 `user:unknown`。
**根因**：网关日志中来自未注册来源的消息（外部飞书用户等），非恶意影子 agent。
**治理动作**：无需治理。如需降低噪音，可在审计时把已知外部来源加入 known_agents 白名单。
**预期收益**：审计报告噪音减少
**风险**：无

---

## 四、执行计划（拍板后执行）

| 步骤 | 动作 | 验证 |
|:--|:--|:--|
| 1 | 主 config + 4 profile 调 `tool_output.max_bytes` 50000→20000、`file_read_max_chars` 100000→50000 | `hermes config` 确认生效 |
| 2 | 验证 compression 工作（grep gateway.log），必要时 threshold 0.5→0.4 | grep 有压缩事件 |
| 3 | 重启 gateway 使配置生效 | `hermes gateway restart` + 健康检查 |
| 4 | 重跑 agentlens 审计，对比前后发现数/成本 | 新报告 vs 旧报告 delta |
| 5 | skill 补充「勿重复加载」提醒（可选） | — |

**执行前提**：涉及修改 Hermes 全局配置 + 重启 gateway——等你点头，且改前会备份 config.yaml。

---

## 五、为什么这值得做

1. **dogfooding**：用自己的工具治理自己，验证工具在真实场景的可用性（正好补销售案例：从"审出问题"到"治理见效"的完整闭环）
2. **省钱**：估算 846 CNY / 5 周，治理后大输出注入减半，长期节省可观
3. **可量化**：治理前后两次审计报告对比，就是"工具价值"的最佳证据——比任何宣传都硬

---

*关联：agentlens-cli/ops/PROJECT_STATE.md · commercialization-strategy skill · 客户画像与获客清单 v2*

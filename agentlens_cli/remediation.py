"""修复建议映射：为每条审计发现提供可执行的修复指引。

每条发现不只是「有问题」，还应告诉用户「怎么修」。
本模块仿照 regulations.py 的结构，为 finding title 配修复建议。
"""

# ── Finding title → remediation list mapping ──────────────────────────

REMEDIATIONS: dict[str, list[dict]] = {
    # ── Shadow layer ──
    "SHADOW_AGENT_DETECTED": [
        {
            "action": "将未登记 Agent 加入白名单并注册身份",
            "detail": "在 config.py 的 KNOWN_AGENTS 中补充该 Agent 标识；若为恶意 Agent，立即封禁并排查其操作历史",
            "priority": "high",
        },
        {
            "action": "在网关层增加 Agent 身份校验",
            "detail": "在 Hermes Gateway 路由层对每个 Agent 请求校验来源身份，未注册者拒绝连接",
            "priority": "high",
        },
    ],
    "UNAUTHORIZED_TOOL_CALL": [
        {
            "action": "对高输出工具调用加审批流",
            "detail": "在网关层对危险工具（如 Bash/Write/Execute）增加调用前审批拦截，审批通过后方可执行",
            "priority": "high",
        },
        {
            "action": "配置危险工具白名单并限制调用频率",
            "detail": "在 config.py 的 DANGEROUS_TOOLS 中补充该工具名，设置单次调用输出上限（如 100KB）",
            "priority": "high",
        },
    ],
    "PRIVILEGE_BOUNDARY_VIOLATION": [
        {
            "action": "为每个 Agent 角色定义最小权限集",
            "detail": "在网关层配置基于角色的工具调用权限矩阵，Worker 不应调用审批类工具，Leader 不应直接执行终端命令",
            "priority": "high",
        },
        {
            "action": "启用权限边界运行时校验",
            "detail": "在每次工具调用前校验 Agent 角色与工具权限是否匹配，不匹配则拒绝并记录告警",
            "priority": "high",
        },
    ],
    "AUDIT_GAP_NO_APPROVAL_STREAM": [
        {
            "action": "补全审批流日志记录",
            "detail": "在网关层确保每次工具调用/任务派发/决策执行均写入 approval 事件，包含审批人、时间、结果",
            "priority": "high",
        },
        {
            "action": "启用审计日志完整性校验",
            "detail": "在每次审计前自动检查审批流覆盖度，缺失率 > 5% 时触发告警",
            "priority": "medium",
        },
    ],

    # ── Compliance layer ──
    "USER_ONLY_VIOLATION": [
        {
            "action": "在决策执行前增加用户确认步骤",
            "detail": "对标记为 USER_ONLY 的决策域，Agent 不得直接执行，必须向用户发起确认请求并等待明确授权",
            "priority": "high",
        },
        {
            "action": "在决策边界模型中标注 USER_ONLY 域",
            "detail": "在 compliance.py 的 DECISION_BOUNDARY_MODEL 中明确标注哪些决策域为用户专属，Agent 不可涉足",
            "priority": "high",
        },
    ],
    "HIGH_RISK_AUTONOMOUS_DECISION": [
        {
            "action": "为 L3 高风险决策增加强制审批流",
            "detail": "在网关层拦截所有 L3 决策，要求用户明确授权（含授权理由和时间戳），未经授权不得执行",
            "priority": "high",
        },
        {
            "action": "设置 L3 决策执行延迟窗口",
            "detail": "L3 决策执行前设置 30 秒冷却期，期间用户可撤销；超时未确认则自动拒绝",
            "priority": "medium",
        },
    ],
    "MISSING_USER_AUTHORIZATION": [
        {
            "action": "补全缺失的用户授权记录",
            "detail": "回溯该决策对应的授权事件，确保 event stream 中 user_authorization 事件存在且内容完整",
            "priority": "high",
        },
        {
            "action": "在网关层强制要求授权事件",
            "detail": "所有需用户授权的决策，在事件流中必须有对应的 user_authorization 事件，否则审计层拒绝通过",
            "priority": "high",
        },
    ],
    "MISSING_INFORMED_CONSENT": [
        {
            "action": "在 Agent 自主决策后向用户发送披露通知",
            "detail": "每次 Agent 做出自主决策后，通过网关层向用户推送通知，包含：决策内容、依据、可撤销链接",
            "priority": "high",
        },
        {
            "action": "在事件流中增加 informed_consent 事件类型",
            "detail": "确保每次自主决策对应一条 informed_consent 事件，记录通知时间、用户是否已读",
            "priority": "medium",
        },
    ],

    # ── Decision layer ──
    "APPROVAL_BYPASS_CONFIRMED": [
        {
            "action": "立即封堵审批绕过路径",
            "detail": "排查网关层审批流代码，确认绕过原因（如开关未启用、条件判断遗漏），修复后发布上线",
            "priority": "high",
        },
        {
            "action": "回滚已绕过的危险操作",
            "detail": "对审批绕过期间执行的操作逐条复核，必要时回滚；如涉及数据修改，通知安全团队",
            "priority": "high",
        },
        {
            "action": "增加审批绕过自动检测告警",
            "detail": "在网关层添加实时监控：检测到无审批事件却执行了需审批的操作时，立即告警并阻断",
            "priority": "high",
        },
    ],
    "task_dispatch missing rationale": [
        {
            "action": "在任务派发事件中补全 rationale 字段",
            "detail": "修改 task_dispatch 事件生成逻辑，确保每条派发都包含 rationale 字段，说明派发原因和依据",
            "priority": "medium",
        },
        {
            "action": "在网关层校验派发事件完整性",
            "detail": "网关层在派发任务前校验事件是否包含 rationale，缺失则拒绝派发并返回错误",
            "priority": "medium",
        },
    ],
    "task_split missing rationale": [
        {
            "action": "在任务拆分事件中补全 rationale 字段",
            "detail": "修改 task_split 事件生成逻辑，确保每条拆分都包含 rationale 字段，说明拆分逻辑和依据",
            "priority": "medium",
        },
        {
            "action": "在网关层校验拆分事件完整性",
            "detail": "网关层在拆分任务前校验事件是否包含 rationale，缺失则拒绝拆分并返回错误",
            "priority": "medium",
        },
    ],

    # ── Governance / Cost layer ──
    "large-output tool injection ungoverned": [
        {
            "action": "设置工具输出截断上限",
            "detail": "在网关层对每个工具调用设置输出截断上限（如 50KB），超出部分丢弃并记录 warning 事件",
            "priority": "medium",
        },
        {
            "action": "对大输出工具增加内容安全校验",
            "detail": "在工具输出注入上下文前，对输出内容做安全扫描（如敏感信息检测、注入攻击检测）",
            "priority": "high",
        },
    ],
    "session-level context bloat: no deliberate compaction": [
        {
            "action": "启用会话级上下文压缩策略",
            "detail": "在网关层配置上下文压缩策略：当会话 token 超过阈值（如 64K）时自动触发压缩，保留关键信息",
            "priority": "medium",
        },
        {
            "action": "设置单会话 token 上限",
            "detail": "在网关层设置单会话 token 硬上限（如 128K），超限时拒绝新请求并提示用户重置会话",
            "priority": "medium",
        },
    ],
    "no per-agent token caps observed": [
        {
            "action": "为每个 Agent 设置 token 使用上限",
            "detail": "在 config.py 中为每个 Agent 类型配置每日/每会话 token 上限，网关层实时监控并超限告警",
            "priority": "medium",
        },
        {
            "action": "启用 token 消耗实时看板",
            "detail": "在网关层暴露 token 消耗监控接口，供运维团队实时查看各 Agent 消耗趋势",
            "priority": "low",
        },
    ],
    "cost-model gaps": [
        {
            "action": "在事件流中补充单价信息",
            "detail": "在事件流中增加 pricing 事件，记录各模型当前输入/输出单价，消除成本估算偏差",
            "priority": "low",
        },
        {
            "action": "定期校验成本模型与实际账单",
            "detail": "每周对比审计估算成本与实际 API 账单，偏差超过 10% 时更新成本模型参数",
            "priority": "low",
        },
    ],

    # ── Graph layer ──
    "unclosed tasks detected": [
        {
            "action": "人工或自动关闭遗留任务",
            "detail": "逐条排查未关闭任务：若任务已完成，补发 task_completion 事件；若任务已废弃，补发 task_cancelled 事件",
            "priority": "medium",
        },
        {
            "action": "设置任务超时自动关闭机制",
            "detail": "在网关层为每个任务设置超时时间（如 30 分钟），超时未完成自动标记为 cancelled 并记录原因",
            "priority": "low",
        },
    ],
    "absent workers": [
        {
            "action": "排查缺席 Worker 原因并重新派发",
            "detail": "检查缺席 Worker 的在线状态和日志，若已离线则重新派发任务给可用 Worker；若为异常退出则修复后重试",
            "priority": "medium",
        },
        {
            "action": "增加 Worker 心跳检测",
            "detail": "在网关层增加 Worker 心跳检测机制，连续 3 次心跳丢失则标记为不可用并自动转移任务",
            "priority": "medium",
        },
    ],
    "data gaps in collaboration graph": [
        {
            "action": "补全协作图谱缺失数据",
            "detail": "排查缺失的事件类型（如 task_dispatch 无对应 task_completion），补充缺失事件或标注已知缺口",
            "priority": "medium",
        },
        {
            "action": "在网关层增加事件完整性校验",
            "detail": "在事件写入时校验事件关联完整性（如 task_dispatch 必须有对应 task_id），不完整则拒绝写入",
            "priority": "medium",
        },
    ],

    # ── Evidence layer ──
    "events missing evidence_ref": [
        {
            "action": "补全事件的 evidence_ref 字段",
            "detail": "逐条排查缺失 evidence_ref 的事件，补充证据引用；若无法补充，标注为不可验证并记录原因",
            "priority": "medium",
        },
        {
            "action": "在事件生成层强制校验 evidence_ref",
            "detail": "在网关层事件写入时校验 evidence_ref 字段非空，否则拒绝写入并返回错误",
            "priority": "medium",
        },
    ],
    "finding evidence_refs not resolvable": [
        {
            "action": "修复不可解析的证据引用",
            "detail": "排查 evidence_ref 指向的 event_id 是否真实存在；若不存在，补充事件或修正引用",
            "priority": "medium",
        },
        {
            "action": "在 finding 生成时校验 evidence_ref 可解析",
            "detail": "在审计层生成 finding 时，自动校验 evidence_refs 中的所有 event_id 均可在事件流中找到",
            "priority": "medium",
        },
    ],
    "SYSTEM_PROMPT_LEAKAGE_SUSPECTED": [
        {
            "action": "将系统提示视为敏感配置而非访问控制",
            "detail": "系统提示中不要放置无法泄露的机密信息；机密信息移入访问控制系统，输出层做脱敏检查",
            "priority": "high",
        },
        {
            "action": "对疑似泄露的系统提示做内容审查与触发源排查",
            "detail": "排查该输出对应的输入上下文（工具结果/检索文档）是否包含注入内容；修复注入源并限制 agent 输出中引用系统提示",
            "priority": "high",
        },
    ],
    "LARGE_OUTPUT_CONTEXT_EXPOSURE_SUSPECTED": [
        {
            "action": "设置 agent 单次输出上限并告警",
            "detail": "为 agent 响应设置字符上限（如 8000），超限自动截断并记录；检查超大输出是否整段带出上下文",
            "priority": "medium",
        },
        {
            "action": "排查超大输出来源",
            "detail": "确认是正常长文回答还是上下文泄露（系统提示/会话历史被带出）；对输出类工具设置输出截断",
            "priority": "medium",
        },
    ],
}

# ── Dynamic pattern matching (prefix-based) ───────────────────────────

DYNAMIC_REMEDIATIONS: list[tuple[str, list[dict]]] = [
    (
        "repeated calls to same high-output tool:",
        [
            {
                "action": "对重复调用同一高输出工具增加频率限制",
                "detail": "在网关层设置同一工具单次会话调用上限（如 10 次/分钟），超限后自动截断并记录告警",
                "priority": "medium",
            },
            {
                "action": "启用工具调用结果缓存",
                "detail": "对相同参数的工具调用在会话内缓存结果，避免重复调用浪费资源",
                "priority": "low",
            },
        ],
    ),
    (
        "inefficient loop: rapid repeated calls to",
        [
            {
                "action": "对低效循环调用增加速率限制",
                "detail": "在网关层检测同一工具在短时间内的重复调用模式，超过阈值（如 5 次/秒）则限流并告警",
                "priority": "medium",
            },
            {
                "action": "优化 Agent 调用逻辑，合并批量请求",
                "detail": "检查 Agent 的 prompt 和策略配置，引导其使用批量调用接口替代逐条调用，减少往返次数",
                "priority": "low",
            },
        ],
    ),
]

# ── Default fallback ──────────────────────────────────────────────────

_DEFAULT_REMEDIATION = [
    {
        "action": "人工复核",
        "detail": "该问题无预设修复建议，需结合具体事件流人工分析",
        "priority": "medium",
    }
]


def _lookup_remediations(title: str) -> list[dict]:
    """查找 finding title 对应的修复建议。精确匹配 → 动态前缀 → 兜底通用建议。"""
    # Exact match first
    if title in REMEDIATIONS:
        return REMEDIATIONS[title]

    # Dynamic pattern match
    for prefix, rems in DYNAMIC_REMEDIATIONS:
        if title.startswith(prefix):
            return rems

    # Default fallback
    return _DEFAULT_REMEDIATION


def map_finding(finding: dict) -> dict:
    """为单个 finding 添加 remediation 字段（list[dict]），原地修改并返回。"""
    title = finding.get("title", "")
    finding["remediation"] = _lookup_remediations(title)
    return finding


def map_all_layers(result: dict) -> dict:
    """遍历 graph/decision/evidence/cost/shadow/compliance 六层所有 findings，添加 remediation 字段。

    原地修改 result 并返回。
    """
    layer_keys = ["graph", "decision", "evidence", "cost", "shadow", "compliance"]
    for key in layer_keys:
        layer = result.get(key)
        if not isinstance(layer, dict):
            continue
        findings = layer.get("findings", [])
        for f in findings:
            map_finding(f)
    return result


def list_remediations(title_filter: str = None) -> list[dict]:
    """列出全部修复建议映射，可选按 title 关键词过滤。

    返回 list[dict]，每项含 {title, remediations}。
    """
    result = []
    # Static mappings
    for title, rems in sorted(REMEDIATIONS.items()):
        if title_filter and title_filter.lower() not in title.lower():
            continue
        result.append({"title": title, "remediations": rems})

    # Dynamic mappings
    for prefix, rems in DYNAMIC_REMEDIATIONS:
        if title_filter and title_filter.lower() not in prefix.lower():
            continue
        result.append({"title": f"{prefix}*", "remediations": rems})

    return result
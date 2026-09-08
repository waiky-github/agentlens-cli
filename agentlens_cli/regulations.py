"""Regulation reference mapping: maps each audit finding title to applicable regulatory clauses.

Primary regulation: 网信办《智能体规范应用与创新发展实施意见》(2026-05-08)
Secondary regulation: EU AI Act (2024/1689)
Supplementary: 《人工智能拟人化互动服务管理暂行办法》(2026-07-15)
"""

# ── Regulation definitions ──────────────────────────────────────────

REGULATION_NAMES = {
    "impl_opinions": "网信办《智能体规范应用与创新发展实施意见》(2026-05-08)",
    "eu_ai_act": "EU AI Act (2024/1689)",
    "personification": "《人工智能拟人化互动服务管理暂行办法》(2026-07-15)",
}

# ── Finding title → regulation references mapping ───────────────────

REGULATIONS: dict[str, list[dict]] = {
    # ── Shadow layer ──
    "SHADOW_AGENT_DETECTED": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "影子智能体",
            "clause": "内部发现与管控 — 要求对未授权部署/使用 AI 智能体进行内部发现和管控",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Recital 99/100",
            "clause": "多 Agent 链中每个执行高风险功能的 Agent 都受义务约束；未登记 Agent 应被识别",
        },
    ],
    "UNAUTHORIZED_TOOL_CALL": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "内生安全",
            "clause": "权限管控、工具调用安全 — 危险工具调用需经明确授权，不得绕过审批",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 14",
            "clause": "human oversight — 高风险 AI 系统须有适当的人类监督机制，包括工具调用授权",
        },
    ],
    "PRIVILEGE_BOUNDARY_VIOLATION": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "内生安全",
            "clause": "权限管控 — 智能体不得执行超出其角色允许范围的操作，权限边界必须明确",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 14",
            "clause": "human oversight — 系统应确保操作权限与角色匹配，防止越权",
        },
    ],
    "AUDIT_GAP_NO_APPROVAL_STREAM": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "操作留痕 — 智能体行为可验证、可追溯；审批流缺失导致审计无法完成",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 高风险 AI 系统须自动记录事件日志，审批流属于必要日志范畴",
        },
    ],

    # ── Compliance layer ──
    "USER_ONLY_VIOLATION": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "第 6 条",
            "clause": "决策权限分层 — 仅限用户本人决策的事项，智能体不得代为执行；用户最终决策权不可让渡",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 14",
            "clause": "human oversight — 某些决策必须保留给人类，不得由 AI 系统自主做出",
        },
    ],
    "HIGH_RISK_AUTONOMOUS_DECISION": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "第 6 条",
            "clause": "需用户授权决策 — 高风险（L3）决策须有用户明确授权记录，不得由智能体自主执行",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 14",
            "clause": "human oversight — 高风险 AI 系统输出须经人类验证后方可执行",
        },
    ],
    "MISSING_USER_AUTHORIZATION": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "第 6 条",
            "clause": "需用户授权决策 — 执行不得超出授权范围；授权记录缺失即违规",
        },
    ],
    "MISSING_INFORMED_CONSENT": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "第 6 条",
            "clause": "用户知情权 — 智能体自主决策应向用户披露，满足知情同意要求",
        },
        {
            "regulation": REGULATION_NAMES["personification"],
            "article": "互动留痕",
            "clause": "互动留痕、内容安全 — 智能体自主行为应留有披露记录",
        },
    ],

    # ── Decision layer ──
    "APPROVAL_BYPASS_CONFIRMED": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "第 6 条",
            "clause": "执行不得超出授权范围 — 审批绕过直接违反权限分层要求，属于严重合规违规",
        },
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "操作留痕 — 审批绕过导致行为无法追溯，破坏可验证性",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 14",
            "clause": "human oversight — 绕过人类监督机制构成合规违规",
        },
    ],
    "L3 approval chain compliant": [
        # Positive finding — no violation, but note the regulation it satisfies
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "第 6 条",
            "clause": "需用户授权决策 — 该审批链已满足 L3 授权要求（合规）",
        },
    ],
    "task_dispatch missing rationale": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "可验证、可追溯 — 任务派发缺少理由说明，影响审计可追溯性",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 日志应包含足够信息以追溯决策依据",
        },
    ],
    "task_split missing rationale": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "可验证、可追溯 — 任务拆分缺少理由说明，影响审计可追溯性",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 日志应包含足够信息以追溯决策依据",
        },
    ],

    # ── Governance / Cost layer ──
    "large-output tool injection ungoverned": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "内生安全",
            "clause": "工具调用安全 — 大输出注入未治理可能导致上下文污染和安全隐患",
        },
        {
            "regulation": REGULATION_NAMES["personification"],
            "article": "互动留痕",
            "clause": "内容安全 — 工具输出未截断可能引入不安全内容",
        },
    ],
    "session-level context bloat: no deliberate compaction": [
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 上下文膨胀可能导致日志记录不完整或成本失控",
        },
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "内生安全",
            "clause": "权限管控 — 未受控的上下文增长可能影响系统行为可预测性",
        },
    ],
    "no per-agent token caps observed": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "内生安全",
            "clause": "权限管控 — 应设置各 Agent 的资源使用上限，防止资源滥用",
        },
    ],
    "cost-model gaps: no unit price in event stream — prices are estimates": [
        {
            "regulation": "unknown",
            "article": "",
            "note": "manual review required — 成本估算准确性不直接对应法规条款，属于审计最佳实践",
        },
    ],

    # ── Graph layer ──
    "unclosed tasks detected": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "可追溯 — 未关闭任务导致协作链路不完整，无法完整追溯行为",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 任务生命周期应完整记录，未关闭任务表示日志不完整",
        },
    ],
    "absent workers: dispatched but no completion": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "可追溯 — Worker 缺席导致协作链路断裂，无法完整追溯行为",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 任务派发与完成应成对记录",
        },
    ],
    "data gaps in collaboration graph": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "可验证、可追溯 — 协作图谱存在数据缺口，影响完整审计",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 日志记录应完整，数据缺口违反日志完整性要求",
        },
    ],

    # ── Evidence layer ──
    "events missing evidence_ref": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "操作留痕 — 事件缺少证据引用，无法满足可验证要求",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 自动日志记录应包含可追溯的证据引用",
        },
    ],
    "finding evidence_refs not resolvable": [
        {
            "regulation": REGULATION_NAMES["impl_opinions"],
            "article": "行为管控",
            "clause": "可验证、可追溯 — 发现项的证据引用无法解析，审计结论不可验证",
        },
        {
            "regulation": REGULATION_NAMES["eu_ai_act"],
            "article": "Art. 12",
            "clause": "logging — 日志引用应可解析，指向真实事件",
        },
    ],
}

# Regex patterns for dynamic titles (matched by prefix)
DYNAMIC_REGULATIONS: list[tuple[str, list[dict]]] = [
    # "repeated calls to same high-output tool: {tool_name}"
    (
        "repeated calls to same high-output tool:",
        [
            {
                "regulation": REGULATION_NAMES["impl_opinions"],
                "article": "内生安全",
                "clause": "工具调用安全 — 重复调用同一高输出工具未治理，存在资源浪费和安全隐患",
            },
        ],
    ),
    # "inefficient loop: rapid repeated calls to {tool_name}"
    (
        "inefficient loop: rapid repeated calls to",
        [
            {
                "regulation": REGULATION_NAMES["impl_opinions"],
                "article": "内生安全",
                "clause": "工具调用安全 — 低效循环调用未治理，存在资源浪费和安全隐患",
            },
        ],
    ),
]


def _lookup_regulations(title: str) -> list[dict]:
    """Look up regulation references for a finding title. Falls back to dynamic patterns."""
    # Exact match first
    if title in REGULATIONS:
        return REGULATIONS[title]

    # Dynamic pattern match
    for prefix, refs in DYNAMIC_REGULATIONS:
        if title.startswith(prefix):
            return refs

    # Default: unknown
    return [{"regulation": "unknown", "article": "", "note": "manual review required"}]


def map_finding(finding: dict) -> dict:
    """Add regulation_refs to a single finding dict in-place. Returns the same dict."""
    title = finding.get("title", "")
    finding["regulation_refs"] = _lookup_regulations(title)
    return finding


def map_all_layers(result: dict) -> dict:
    """Add regulation_refs to all findings across all seven layers in-place. Returns the same dict.

    Layers: graph, decision, evidence, cost, shadow, compliance
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


def list_regulations(title_filter: str = None) -> list[dict]:
    """List all regulation mappings, optionally filtered by title substring.

    Returns a list of {title, refs} dicts.
    """
    result = []
    # Static mappings
    for title, refs in sorted(REGULATIONS.items()):
        if title_filter and title_filter.lower() not in title.lower():
            continue
        result.append({"title": title, "refs": refs})

    # Dynamic mappings
    for prefix, refs in DYNAMIC_REGULATIONS:
        if title_filter and title_filter.lower() not in prefix.lower():
            continue
        result.append({"title": f"{prefix}*", "refs": refs})

    return result
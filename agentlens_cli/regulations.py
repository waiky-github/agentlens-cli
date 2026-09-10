"""Regulation reference mapping: maps each audit finding title to applicable regulatory clauses.

Primary regulation: 网信办《智能体规范应用与创新发展实施意见》(2026-05-08)
Secondary regulation: EU AI Act (2024/1689)
Supplementary: 《人工智能拟人化互动服务管理暂行办法》(2026-07-15)
International security frameworks (added 2026-09-10):
OWASP Top 10 for LLM Applications 2026 (announced 2026-09-02)
OWASP Top 10 for Agentic Applications 2026 (ASI01-ASI10)
OWASP Agent Control Standard (ACS 2026)

Manual annotations (added 2026-09-10): unknown findings 的人工标注覆盖。
annotations 文件（默认 ~/.hermes/agentlens-reports/annotations.json，env AGENTLENS_ANNOTATIONS 覆盖）
在 _lookup_regulations 中**优先于**静态表生效，用于把审计时未匹配的 finding title 归入人工判定条款。
"""

import json
import os
from pathlib import Path

# ── Regulation definitions ──────────────────────────────────────────

REGULATION_NAMES = {
    "impl_opinions": "网信办《智能体规范应用与创新发展实施意见》(2026-05-08)",
    "eu_ai_act": "EU AI Act (2024/1689)",
    "personification": "《人工智能拟人化互动服务管理暂行办法》(2026-07-15)",
    "owasp_llm_2026": "OWASP Top 10 for LLM Applications 2026",
    "owasp_agentic": "OWASP Top 10 for Agentic Applications 2026 (ASI)",
    "acs": "OWASP Agent Control Standard (ACS 2026)",
}

# ── OWASP LLM Top 10 2026 (announced 2026-09-02, generalanalysis/owasp 2026 guide) ──
# Note: 2026 编号与 2025 不同——System Prompt Leakage 已改名 Hidden Context Exposure 并移至 LLM08；
# Excessive Agency 升至第 3，Improper Output Handling 降至第 10。

OWASP_LLM_2026 = {
    "LLM01": "Prompt Injection — 不可信文本/文件/工具结果/记忆与指令共享上下文，模型遵循后产生后果",
    "LLM02": "Sensitive Information Disclosure — 机密数据进入模型上下文或输出，流向用户/日志/供应商/下游",
    "LLM03": "Excessive Agency — 工具/函数/权限/自主步骤超出任务实际所需",
    "LLM04": "Supply Chain — 模型/适配器/数据集/库/托管服务的来源、完整性、评估历史与更新路径需可验证",
    "LLM05": "Data and Model Poisoning — 训练/微调/反馈/评估/检索输入可被篡改且难以检测",
    "LLM06": "Unbounded Consumption — 请求/token/递归/扇出/模型提取/花费缺少每用户、每租户、每工作流限制",
    "LLM07": "Misinformation — 无证据支持或编造的声明影响人或自动化决策",
    "LLM08": "Hidden Context Exposure — 隐藏上下文含机密或安全逻辑，泄露会增强攻击者能力（原 System Prompt Leakage）",
    "LLM09": "Vector and Embedding Weaknesses — 检索/索引投毒/嵌入反演可跨授权边界泄露",
    "LLM10": "Improper Output Handling — 模型输出被解析器/渲染器/解释器/API 未经验证与编码即消费",
}

# ── OWASP Top 10 for Agentic Applications 2026 (ASI01-ASI10, Black Hat Europe 2025 发布) ──

OWASP_AGENTIC = {
    "ASI01": "Agent Goal Hijack — 恶意内容改变 agent 的目标或决策路径",
    "ASI02": "Tool Misuse and Exploitation — agent 被操纵误用合法工具",
    "ASI03": "Identity and Privilege Abuse — 继承/缓存的凭证被利用（含影子 agent 继承合法凭证）",
    "ASI04": "Agentic Supply Chain Vulnerabilities — 被篡改的工具/模型/提示模板影响执行",
    "ASI05": "Unexpected Code Execution — agent 生成或运行攻击者控制的代码",
    "ASI06": "Memory and Context Poisoning — 记忆或 RAG 存储持久性损坏后被信任",
    "ASI07": "Insecure Inter-Agent Communication — agent 间消息被伪造/重放/篡改",
    "ASI08": "Cascading Agent Failures — 小错误跨 agent 传播并放大",
    "ASI09": "Human-Agent Trust Exploitation — 用户过度信任有说服力的 agent 而批准危害",
    "ASI10": "Rogue Agents — 被攻陷或错位的 agent 看似合法地作恶",
}

# ── OWASP reference helpers ─────────────────────────────────────────


def _owasp_ref(framework_key: str, code: str) -> dict:
    """Build a single OWASP/ACS reference dict."""
    if framework_key == "owasp_llm_2026":
        return {"regulation": REGULATION_NAMES["owasp_llm_2026"], "article": code, "clause": OWASP_LLM_2026[code]}
    if framework_key == "owasp_agentic":
        return {"regulation": REGULATION_NAMES["owasp_agentic"], "article": code, "clause": OWASP_AGENTIC[code]}
    return {"regulation": REGULATION_NAMES["acs"], "article": "ACS", "clause": code}


# 精确 title → OWASP 映射（关键 finding 覆盖 layer fallback 的默认推断）
OWASP_TITLE_OVERRIDES: dict[str, list[dict]] = {
    "SHADOW_AGENT_DETECTED": [
        _owasp_ref("owasp_agentic", "ASI10"),
        _owasp_ref("owasp_agentic", "ASI03"),
    ],
    "UNAUTHORIZED_TOOL_CALL": [
        _owasp_ref("owasp_agentic", "ASI02"),
        _owasp_ref("owasp_agentic", "ASI03"),
    ],
    "PRIVILEGE_BOUNDARY_VIOLATION": [
        _owasp_ref("owasp_agentic", "ASI03"),
        _owasp_ref("owasp_llm_2026", "LLM03"),
    ],
    "AUDIT_GAP_NO_APPROVAL_STREAM": [
        _owasp_ref("owasp_llm_2026", "LLM10"),
        _owasp_ref("owasp_agentic", "ASI09"),
        _owasp_ref("acs", "控制面要求 — 关键操作需人类审批门（approval gate）并留痕"),
    ],
    "USER_ONLY_VIOLATION": [
        _owasp_ref("owasp_llm_2026", "LLM03"),
        _owasp_ref("owasp_agentic", "ASI09"),
    ],
    "HIGH_RISK_AUTONOMOUS_DECISION": [
        _owasp_ref("owasp_llm_2026", "LLM03"),
        _owasp_ref("owasp_agentic", "ASI09"),
        _owasp_ref("acs", "控制面要求 — 高风险自主决策须有人类审批门"),
    ],
    "MISSING_USER_AUTHORIZATION": [
        _owasp_ref("owasp_llm_2026", "LLM03"),
        _owasp_ref("owasp_agentic", "ASI09"),
    ],
    "MISSING_INFORMED_CONSENT": [
        _owasp_ref("owasp_agentic", "ASI09"),
    ],
    "APPROVAL_BYPASS_CONFIRMED": [
        _owasp_ref("owasp_llm_2026", "LLM03"),
        _owasp_ref("owasp_agentic", "ASI09"),
        _owasp_ref("acs", "控制面要求 — 审批门（approval gate）被绕过即控制面失效"),
    ],
    "large-output tool injection ungoverned": [
        _owasp_ref("owasp_llm_2026", "LLM01"),
    ],
    "no per-agent token caps observed": [
        _owasp_ref("owasp_llm_2026", "LLM06"),
    ],
    "session-level context bloat: no deliberate compaction": [
        _owasp_ref("owasp_llm_2026", "LLM06"),
    ],
    "events missing evidence_ref": [
        _owasp_ref("owasp_llm_2026", "LLM07"),
    ],
    "finding evidence_refs not resolvable": [
        _owasp_ref("owasp_llm_2026", "LLM07"),
    ],
    "unclosed tasks detected": [
        _owasp_ref("owasp_agentic", "ASI08"),
    ],
    "absent workers: dispatched but no completion": [
        _owasp_ref("owasp_agentic", "ASI08"),
    ],
    "data gaps in collaboration graph": [
        _owasp_ref("owasp_agentic", "ASI08"),
        _owasp_ref("owasp_agentic", "ASI07"),
    ],
    "task_dispatch missing rationale": [
        _owasp_ref("owasp_llm_2026", "LLM07"),
        _owasp_ref("owasp_agentic", "ASI08"),
    ],
    "task_split missing rationale": [
        _owasp_ref("owasp_llm_2026", "LLM07"),
        _owasp_ref("owasp_agentic", "ASI08"),
    ],
    "SYSTEM_PROMPT_LEAKAGE_SUSPECTED": [
        _owasp_ref("owasp_llm_2026", "LLM08"),
        _owasp_ref("owasp_agentic", "ASI06"),
    ],
    "LARGE_OUTPUT_CONTEXT_EXPOSURE_SUSPECTED": [
        _owasp_ref("owasp_llm_2026", "LLM08"),
        _owasp_ref("owasp_llm_2026", "LLM06"),
    ],
}

# 审计层 → OWASP 默认映射（finding 无精确 override 时按层兜底）
OWASP_LAYER_FALLBACK: dict[str, list[dict]] = {
    "shadow": [
        _owasp_ref("owasp_agentic", "ASI10"),
        _owasp_ref("owasp_agentic", "ASI03"),
        _owasp_ref("owasp_llm_2026", "LLM03"),
    ],
    "compliance": [
        _owasp_ref("owasp_llm_2026", "LLM03"),
        _owasp_ref("owasp_agentic", "ASI09"),
        _owasp_ref("owasp_llm_2026", "LLM10"),
        _owasp_ref("acs", "控制面要求 — 决策权限分层需人类审批门留痕"),
    ],
    "decision": [
        _owasp_ref("owasp_llm_2026", "LLM03"),
        _owasp_ref("owasp_agentic", "ASI09"),
        _owasp_ref("owasp_llm_2026", "LLM01"),
    ],
    "evidence": [
        _owasp_ref("owasp_llm_2026", "LLM07"),
        _owasp_ref("owasp_llm_2026", "LLM10"),
        _owasp_ref("owasp_agentic", "ASI08"),
    ],
    "cost": [
        _owasp_ref("owasp_llm_2026", "LLM06"),
        _owasp_ref("owasp_agentic", "ASI02"),
    ],
    "graph": [
        _owasp_ref("owasp_agentic", "ASI07"),
        _owasp_ref("owasp_agentic", "ASI08"),
        _owasp_ref("owasp_agentic", "ASI06"),
    ],
    "gate": [
        _owasp_ref("owasp_llm_2026", "LLM10"),
        _owasp_ref("acs", "控制面要求 — CI 门禁即发布前控制面检查"),
    ],
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


def _annotations_path() -> Path:
    """Resolve the manual annotations file path.

    Resolution order: AGENTLENS_ANNOTATIONS > AGENTLENS_REPORT_DIR/annotations.json
    > ~/.hermes/agentlens-reports/annotations.json (same convention as web/notify/budget).
    """
    env = os.environ.get("AGENTLENS_ANNOTATIONS")
    if env:
        return Path(env)
    report_dir = os.environ.get(
        "AGENTLENS_REPORT_DIR",
        os.path.expanduser("~/.hermes/agentlens-reports"),
    )
    return Path(report_dir) / "annotations.json"


_annotations_cache: dict[str, list[dict]] | None = None


def _load_annotations() -> dict[str, list[dict]]:
    """Load manual annotations (title -> list of refs). Cached after first read."""
    global _annotations_cache
    if _annotations_cache is not None:
        return _annotations_cache
    path = _annotations_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _annotations_cache = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            _annotations_cache = {}
    else:
        _annotations_cache = {}
    return _annotations_cache


def _invalidate_annotations_cache() -> None:
    global _annotations_cache
    _annotations_cache = None


def add_annotation(
    title: str,
    regulation: str,
    article: str = "",
    note: str = "manual annotation",
) -> dict:
    """Add or update a manual regulation annotation for a finding title.

    Writes to the annotations file (incremental; existing entries preserved).
    Returns the ref list now mapped to the title.
    """
    annotations = _load_annotations()
    ref = {"regulation": regulation, "article": article, "note": note}
    annotations[title] = [ref]
    path = _annotations_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8")
    _invalidate_annotations_cache()
    return [ref]


def list_annotations() -> dict:
    """Return all manual annotations (title -> refs)."""
    return dict(_load_annotations())


def _lookup_regulations(title: str) -> list[dict]:
    """Look up regulation references for a finding title. Falls back to dynamic patterns."""
    # Manual annotations take precedence (human judgement overrides automation)
    annotated = _load_annotations().get(title)
    if annotated:
        return annotated

    # Exact match first
    if title in REGULATIONS:
        return REGULATIONS[title]

    # Dynamic pattern match
    for prefix, refs in DYNAMIC_REGULATIONS:
        if title.startswith(prefix):
            return refs

    # Default: unknown
    return [{"regulation": "unknown", "article": "", "note": "manual review required"}]


def map_finding(finding: dict, layer: str = None) -> dict:
    """Add regulation_refs to a single finding dict in-place. Returns the same dict.

    layer 用于 OWASP/ACS 框架级映射的兜底推断：
    - 精确 title override 优先
    - 无 override 但 layer 已知（map_all_layers 总传）→ 按审计层关联风险类别兜底
    - 完全未知（无 override 且 layer 未知）→ 保持 manual review，不硬塞
    """
    title = str(finding.get("title") or "")
    refs = list(_lookup_regulations(title))  # 复制，避免污染静态表/annotations 共享引用

    owasp_refs = OWASP_TITLE_OVERRIDES.get(title)
    if owasp_refs is None and layer in OWASP_LAYER_FALLBACK:
        owasp_refs = OWASP_LAYER_FALLBACK[layer]

    if owasp_refs:
        if OWASP_TITLE_OVERRIDES.get(title) is not None:
            # 精确 title override 提供完整合规语义：移除主映射的 unknown 打底，
            # 避免「有 OWASP 精确覆盖却仍报未映射」的噪音（人工标注的非 unknown 条目保留）
            refs = [r for r in refs if r.get("regulation") != "unknown"]
        existing_keys = {
            (r.get("regulation"), r.get("article"), r.get("clause"), r.get("note", ""))
            for r in refs
        }
        for r in owasp_refs:
            key = (r.get("regulation"), r.get("article"), r.get("clause"), r.get("note", ""))
            if key not in existing_keys:
                refs.append(r)
                existing_keys.add(key)

    finding["regulation_refs"] = refs
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
            map_finding(f, layer=key)
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
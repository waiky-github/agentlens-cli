"""Pricing configuration for cost attribution."""


class CostModel:
    """Token pricing model. All prices are per 1M tokens."""

    def __init__(self, input_price: float = 2.4, output_price: float = 8.0):
        self.input_price = input_price
        self.output_price = output_price

    def input_cost(self, tokens: int) -> float:
        return (tokens / 1_000_000) * self.input_price

    def output_cost(self, tokens: int) -> float:
        return (tokens / 1_000_000) * self.output_price

    def total_cost(self, tokens_in: int, tokens_out: int) -> float:
        return self.input_cost(tokens_in) + self.output_cost(tokens_out)

    def to_dict(self) -> dict:
        return {
            "input_price_per_1m": self.input_price,
            "output_price_per_1m": self.output_price,
            "currency": "CNY",
            "note": "estimate — configurable pricing model",
        }


# Default instance
DEFAULT_COST_MODEL = CostModel()

# ── Shadow Agent Detection defaults ──────────────────────────────

# Known/registered agents extracted from well-known multi-agent patterns.
# Override with --known-agents a,b,c in the CLI.
DEFAULT_KNOWN_AGENTS = [
    "agent:main",
    "team-leader",
    "admin",
    "collector",
    "graph-builder",
    "decision-auditor",
    "cost-analyst",
    "evidence-verifier",
    # 系统内部来源：日志流自身标识（source: hermes:gateway:log），非 agent。
    # 2026-09-09 端到端验证补充：检出 hermes:gateway:log 被误判为影子 agent，
    # 实为事件流的 source 字段，不是运行中的智能体，加入白名单。
    # 注：外部消息用户（user:unknown / user:ou_xxx 飞书 open_id）已由
    # shadow.py 的 EXTERNAL_USER_PREFIXES 前缀规则统一豁免，不在此硬编码。
    "hermes:gateway:log",
]

# Dangerous tools that require explicit approval before execution.
# Override with --dangerous-tools x,y,z in the CLI.
DEFAULT_DANGEROUS_TOOLS = [
    "shell",
    "bash",
    "rm",
    "delete",
    "drop",
    "exec",
    "system",
    "sudo",
    "kill",
    "shutdown",
    "reboot",
    "write_file",
    "overwrite",
    "truncate",
]

# ── Compliance: Decision Authority Classification (《实施意见》第6条) ──

# USER_ONLY: actions that are exclusively the user's decision authority.
# Agent execution of these actions is a violation regardless of approval.
USER_ONLY_ACTIONS = [
    "delete_production_data",
    "drop_production_table",
    "transfer_funds",
    "approve_public_release",
    "authorize_payment",
    "sign_legal_document",
    "grant_system_access",
    "revoke_user_access",
    "close_account",
    "terminate_service",
    "accept_legal_terms",
    "bind_contract",
]

# USER_AUTHORIZED: actions that require explicit user authorization/approval
# before the agent may execute them.
USER_AUTHORIZED_ACTIONS = [
    "write_production_db",
    "modify_production_config",
    "deploy",
    "send_external_message",
    "send_email",
    "publish_content",
    "create_user_account",
    "modify_user_permissions",
    "execute_shell",
    "run_script",
    "install_package",
    "update_dependency",
    "apply_high_risk_config",
    "apply_config",
    "restart_service",
    "scale_resource",
    "modify_firewall",
    "access_production_data",
    "export_data",
    "import_data",
]

# AGENT_AUTONOMOUS: actions the agent may perform autonomously.
# These still require informed consent disclosure.
AGENT_AUTONOMOUS_ACTIONS = [
    "search",
    "read",
    "list",
    "summarize",
    "analyze",
    "calculate",
    "compare",
    "fetch",
    "get",
    "query",
    "lookup",
    "format",
    "transform",
    "parse",
    "validate",
    "hash",
    "check",
    "scan",
    "audit",
    "verify",
    "diff",
    "report",
    "stats",
    "build",
    "compile",
    "compose",
    "merge",
    "render",
    "aggregate",
    "collect",
    "grep",
    "find",
    "ls",
    "cat",
    "head",
    "tail",
    "sort",
    "filter",
    "count",
    "measure",
    "test",
    "lint",
    "format_code",
    "review",
    "suggest",
    "explain",
    "describe",
    "show",
    "display",
    "print",
    "log",
    "trace",
    "monitor",
    "watch",
    "observe",
    "notify",
    "schedule",
    "enqueue",
    "dispatch",
    "route",
    "relay",
    "forward",
    "copy",
    "clone",
    "backup",
    "archive",
    "compress",
    "extract",
    "split",
    "join",
    "concat",
    "truncate_text",
    "preview",
    "sample",
    "peek",
    "reflect",
    "introspect",
    "diagnose",
    "profile",
    "benchmark",
    "evaluate",
    "score",
    "rank",
    "classify",
    "categorize",
    "tag",
    "label",
    "annotate",
    "highlight",
    "extract",
    "infer",
    "predict",
    "recommend",
    "estimate",
    "forecast",
    "simulate",
    "model",
    "train",
    "fine_tune",
    "embed",
    "tokenize",
    "encode",
    "decode",
    "translate",
    "transcribe",
    "synthesize",
    "generate_text",
    "generate_code",
    "generate_image",
    "generate_report",
    "generate_summary",
    "generate_plan",
    "generate_diff",
    "generate_patch",
    "generate_config",
    "generate_template",
    "generate_schema",
    "generate_test",
    "generate_mock",
    "generate_fixture",
    "generate_seed",
    "generate_doc",
    "generate_diagram",
    "generate_chart",
    "generate_graph",
    "generate_table",
    "generate_list",
    "generate_index",
    "generate_tree",
    "generate_map",
    "trigger_emergency_failover",
    "force_apply_high_risk_config",
]

# Risk level mapping: action/tool → L1 (low), L2 (medium), L3 (high)
# L3: production write, delete, funds, external data, legal/financial
# L2: internal write, config changes, deploy, permissions
# L1: read, search, summarize, analyze
ACTION_RISK_LEVELS = {
    # L3 — high risk
    "delete_production_data": "L3",
    "drop_production_table": "L3",
    "transfer_funds": "L3",
    "approve_public_release": "L3",
    "authorize_payment": "L3",
    "sign_legal_document": "L3",
    "close_account": "L3",
    "terminate_service": "L3",
    "accept_legal_terms": "L3",
    "bind_contract": "L3",
    "grant_system_access": "L3",
    "revoke_user_access": "L3",
    # L2 — medium risk
    "write_production_db": "L2",
    "modify_production_config": "L2",
    "deploy": "L2",
    "send_external_message": "L2",
    "send_email": "L2",
    "publish_content": "L2",
    "create_user_account": "L2",
    "modify_user_permissions": "L2",
    "execute_shell": "L2",
    "run_script": "L2",
    "install_package": "L2",
    "update_dependency": "L2",
    "apply_high_risk_config": "L2",
    "apply_config": "L2",
    "restart_service": "L2",
    "scale_resource": "L2",
    "modify_firewall": "L2",
    "access_production_data": "L2",
    "export_data": "L2",
    "import_data": "L2",
    # L3 autonomous high-risk: not in USER_ONLY or USER_AUTHORIZED
    "force_apply_high_risk_config": "L3",
    "trigger_emergency_failover": "L3",
    # L2 AGENT_AUTONOMOUS actions (need informed consent disclosure)
    "train": "L2",
    "fine_tune": "L2",
    "backup": "L2",
    "archive": "L2",
    "predict": "L2",
    "forecast": "L2",
    "simulate": "L2",
    "model": "L2",
    "recommend": "L2",
    "notify": "L2",
}

# Agent role → permitted tools mapping for privilege boundary detection.
# If an agent invokes a tool outside its permitted set, it's a boundary violation.
# An empty value means "all tools allowed" (leader/admin).
AGENT_ROLE_TOOLS = {
    "leader": [],
    "admin": [],
    "collector": ["fetch", "get", "read", "list", "search", "ls", "cat", "grep", "find"],
    "builder": ["build", "compile", "render", "transform", "merge", "compose"],
    "auditor": ["audit", "check", "verify", "validate", "diff", "compare", "scan"],
    "analyst": ["analyze", "cost", "calculate", "aggregate", "query", "report", "stats"],
    "verifier": ["verify", "check", "validate", "hash", "digest", "compare"],
    "worker": ["fetch", "get", "read", "list", "search"],
}
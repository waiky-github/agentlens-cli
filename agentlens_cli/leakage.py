"""Hidden context exposure / system prompt leakage detection.

OWASP LLM Top 10 2026 **LLM08 — Hidden Context Exposure**（原 System Prompt Leakage）：
模型输出中泄露隐藏上下文（系统提示、安全规则、机密配置）会增强攻击者能力。

设计约束（2026-09-10）：
- Hermes gateway 事件流默认脱敏（agent 响应正文不落盘，用户 09-09 纪律）→
  内容级检测只对「事件 payload 带 content 字段」的流生效（如 CrewAI/AutoGen/LangGraph
  原生事件流或用户显式保留正文的流）。
- 脱敏流默认只有元数据弱信号：超大输出（可能整段带出隐藏上下文）→ info 级，不误报。
- 内容级命中 → high（关联 OWASP LLM08 + ASI06 Memory Poisoning 映射见 regulations.py）。
"""

from __future__ import annotations

# 强标记：系统提示典型片段，单命中即可判定疑似泄露
STRONG_LEAK_MARKERS = (
    "system_prompt",
    "system prompt",
    "system_instruction",
    "系统提示词",
    "系统提示",
    "you are an ai",
    "you are a helpful",
    "你的职责是",
    "你的任务是",
    "作为ai助手",
    "作为 ai 助手",
    "do not reveal",
    "do not disclose",
    "不要泄露",
    "不可泄露",
    "不得告知",
)

# 弱标记：通用词，需多个同时命中才判定（防正常对话误报）
WEAK_LEAK_MARKERS = (
    "you are the",
    "system message",
    "系统指令",
    "你是一个",
    "ignore previous instructions",
    "忽略之前的指令",
)

# 内容长度下限：过短的引用不算泄露（如用户问「什么是 system prompt」）
MIN_CONTENT_LEN = 40

DEFAULT_LARGE_OUTPUT_CHARS = 8000  # 单次 agent 输出超过此值 → 元数据级弱信号


def _hit_markers(content: str) -> list[str]:
    """Return matched leak markers (strong single-hit or weak >=2)."""
    lowered = content.lower()
    strong = [m for m in STRONG_LEAK_MARKERS if m in lowered]
    if strong:
        return strong
    weak = [m for m in WEAK_LEAK_MARKERS if m in lowered]
    if len(weak) >= 2:
        return weak
    return []


def audit_system_prompt_leakage(
    events: list[dict],
    content_key: str = "content",
    large_output_threshold: int = DEFAULT_LARGE_OUTPUT_CHARS,
) -> list[dict]:
    """Detect hidden-context exposure signals across events.

    Returns a list of findings (dicts with severity/title/evidence_refs/...).

    - SYSTEM_PROMPT_LEAKAGE_SUSPECTED (high): 事件 payload 含 content 且命中泄露标记
    - LARGE_OUTPUT_CONTEXT_EXPOSURE_SUSPECTED (info): 无 content 可查时，单次输出
      超过阈值（脱敏流唯一可得的弱信号，仅供参考不误报）
    """
    findings: list[dict] = []
    seen: set[tuple] = set()

    for evt in events:
        etype = evt.get("type", "")
        payload = evt.get("payload", {}) or {}
        event_id = evt.get("event_id", "")

        # ── 内容级检测（需事件流保留正文）──
        content = payload.get(content_key)
        if isinstance(content, str) and len(content) >= MIN_CONTENT_LEN:
            hits = _hit_markers(content)
            if hits:
                key = ("LEAK", event_id or (etype, content[:50]))
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "severity": "high",
                        "title": "SYSTEM_PROMPT_LEAKAGE_SUSPECTED",
                        "evidence_refs": [event_id] if event_id else [],
                        "recommendation": (
                            "system prompt / 隐藏上下文疑似被输出到响应；将系统提示视为敏感配置而非访问控制，"
                            "机密信息移入访问控制系统中，并对高敏感输出增加审查"
                        ),
                        "detail": (
                            f"event {event_id or etype} 输出疑似包含系统提示/隐藏上下文片段，"
                            f"命中标记: {', '.join(hits[:4])}（OWASP LLM08 Hidden Context Exposure）"
                        ),
                    })

        # ── 元数据级弱信号：超大输出（脱敏流唯一可查）──
        chars = payload.get("chars")
        if chars is None:
            chars = payload.get("output_chars")
        if isinstance(chars, (int, float)) and chars > large_output_threshold:
            key = ("LARGE", event_id or (etype, chars))
            if key not in seen:
                seen.add(key)
                findings.append({
                    "severity": "info",
                    "title": "LARGE_OUTPUT_CONTEXT_EXPOSURE_SUSPECTED",
                    "evidence_refs": [event_id] if event_id else [],
                    "recommendation": (
                        "单次输出超过阈值，可能整段带出隐藏上下文或会话内容；"
                        "建议检查该输出并考虑输出上限/截断控制"
                    ),
                    "detail": (
                        f"event {event_id or etype} 输出 {int(chars)} 字符超过阈值 "
                        f"{large_output_threshold}（脱敏模式下仅元数据信号，供人工排查）"
                    ),
                })

    return findings

#!/usr/bin/env python3
"""Hermes gateway.log → agentlens 事件流转换器（当前格式 + 脱敏）。

解决两个问题：
1. 当前 Hermes gateway.log 格式（2026-08 起）与 agentlens parser 内置的
   旧版正则不匹配（旧版匹配 agent.tool_executor / agent.conversation_loop /
   Inbound dm message received 等，当前日志是 gateway.run / gateway.platforms 风格）
2. 日志含用户消息原文（inbound message: msg='...'），直接进审计报告会泄露
   隐私——本转换器只保留长度/元信息，丢弃消息正文。

用法：
    python3 convert_gateway_log.py <gateway.log> [--output events.jsonl] [--days N]
    --days N  只保留最近 N 天的事件（默认全部）

输出：JSONL，每行一个脱敏事件，类型与 agentlens 期望一致：
    user_message_arrived / agent_response_sent / model_call / tool_invocation / session_event
"""
import json
import re
import sys
from datetime import datetime, timezone

# ── 日志行格式（2026-08 起的 Hermes gateway 风格） ──────────────────
# 2026-08-25 20:33:14,122 INFO gateway.run: inbound message: platform=feishu user=aaafe264 chat=oc_xxx msg='...'
# 2026-08-25 20:33:41,332 INFO gateway.run: response ready: platform=feishu chat=oc_xxx time=27.2s api_calls=3 response=190
# 2026-08-25 20:33:41,340 INFO gateway.platforms.base: [Feishu] Sending response (190 chars) to oc_xxx
# 2026-08-25 20:33:13,707 INFO gateway.platforms.feishu: [Feishu] Flushing text batch agent:main:feishu:dm:oc_xxx (12 chars)
# 2026-08-25 20:33:14,122 INFO gateway.run: response ready: ... api_calls=3 response=190
# 2026-09-08 17:41:34,226 INFO gateway.run: Session hygiene: 503 messages, ~305,429 tokens ...
# 2026-09-04 16:02:04,088 INFO [20260904_103908_e05a81c2] gateway.run: Session split detected: A → B (compression)
# 2026-08-25 21:36:15,815 INFO gateway.run: Agent cache idle-TTL evict: session=agent:main:feishu:dm:oc_xxx (idle=3755s)

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_INBOUND_RE = re.compile(
    r"inbound message: platform=(\S+) user=(\S+) chat=(\S+) msg='(.*)'$"
)
_RESPONSE_READY_RE = re.compile(
    r"response ready: platform=(\S+) chat=(\S+) time=([\d.]+)s api_calls=(\d+) response=(\d+)"
)
_SENDING_RESP_RE = re.compile(
    r"\[Feishu\] Sending response \((\d+) chars\) to (\S+)"
)
_FLUSH_BATCH_RE = re.compile(
    r"Flushing text batch (\S+) \((\d+) chars"
)
_SESSION_SPLIT_RE = re.compile(
    r"Session split detected: (\S+) → (\S+) \(compression\)"
)
_SESSION_HYGIENE_RE = re.compile(
    r"Session hygiene: (\d+) messages, ~([\d,]+) tokens .*auto-compressing"
)
_AGENT_CACHE_RE = re.compile(
    r"Agent cache idle-TTL evict: session=(\S+) \(idle=(\d+)s\)"
)
# 工具调用 / 模型调用（agent 侧日志风格，可能也在 gateway.log 里）
_TOOL_CALL_RE = re.compile(
    r"agent:main invoked tool (\S+) \(([\d.]+)s"
)
_MODEL_CALL_RE = re.compile(
    r"agent:main API call #\d+ (\S+) in=(\d+) out=(\d+) latency=[\d.]+s"
)


def _parse_ts(line: str):
    m = _TS_RE.match(line)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _mask_msg(raw: str) -> dict:
    """消息正文只保留长度/摘要元信息，绝不外泄内容。"""
    return {
        "text_length": len(raw),
        "chars": len(raw),
        "preview_len": min(len(raw), 5),  # 仅记录量级，不存内容
    }


def convert(path: str, days: int = None) -> list:
    events = []
    now = datetime.now(timezone.utc)
    seen = set()
    evt_n = 0

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            ts = _parse_ts(line)
            if ts is None:
                continue
            if days:
                try:
                    dt = datetime.fromisoformat(ts)
                    if (now - dt).days > days:
                        continue
                except ValueError:
                    pass

            evt = None
            # 用户消息（脱敏：正文只留长度）
            m = _INBOUND_RE.search(line)
            if m:
                evt = {
                    "type": "user_message_arrived",
                    "payload": {
                        "channel": m.group(1),
                        # 用户 ID 统一脱敏为 user:unknown——内部观测不需要区分
                        # 具体用户，且避免真实 open_id / user id 进审计报告
                        # （个人信息保护，2026-09-09 持久化部署确立）
                        "from": "user:unknown",
                        "chat_id": m.group(3),
                        **_mask_msg(m.group(4)),
                    },
                }
            # Agent 响应就绪
            m = _RESPONSE_READY_RE.search(line)
            if m and not evt:
                evt = {
                    "type": "agent_response_sent",
                    "payload": {
                        "channel": m.group(1),
                        "chat_id": m.group(2),
                        "latency_s": float(m.group(3)),
                        "api_calls": int(m.group(4)),
                        "response_chars": int(m.group(5)),
                    },
                }
            # 发送响应（字符数）
            m = _SENDING_RESP_RE.search(line)
            if m and not evt:
                evt = {
                    "type": "agent_response_sent",
                    "payload": {"chars": int(m.group(1)), "chat_id": m.group(2)},
                }
            # 文本批 flush
            m = _FLUSH_BATCH_RE.search(line)
            if m and not evt:
                evt = {
                    "type": "agent_response_sent",
                    "payload": {"session": m.group(1), "chars": int(m.group(2))},
                }
            # 会话压缩
            m = _SESSION_SPLIT_RE.search(line)
            if m and not evt:
                evt = {
                    "type": "session_event",
                    "payload": {
                        "action": "session_split",
                        "from_session": m.group(1),
                        "to_session": m.group(2),
                        "reason": "compression",
                    },
                }
            # 会话卫生（自动压缩）
            m = _SESSION_HYGIENE_RE.search(line)
            if m and not evt:
                evt = {
                    "type": "session_event",
                    "payload": {
                        "action": "auto_compress",
                        "messages": int(m.group(1)),
                        "tokens": int(m.group(2).replace(",", "")),
                    },
                }
            # Agent 缓存淘汰
            m = _AGENT_CACHE_RE.search(line)
            if m and not evt:
                evt = {
                    "type": "session_event",
                    "payload": {
                        "action": "agent_cache_evict",
                        "session": m.group(1),
                        "idle_s": int(m.group(2)),
                    },
                }
            # 工具调用
            m = _TOOL_CALL_RE.search(line)
            if m and not evt:
                evt = {
                    "type": "tool_invocation",
                    "payload": {
                        "tool": m.group(1),
                        "duration_seconds": float(m.group(2)),
                    },
                }
            # 模型调用
            m = _MODEL_CALL_RE.search(line)
            if m and not evt:
                evt = {
                    "type": "model_call",
                    "payload": {
                        "model": m.group(1),
                        "tokens_in": int(m.group(2)),
                        "tokens_out": int(m.group(3)),
                    },
                }

            if evt is None:
                continue

            evt_n += 1
            evt["event_id"] = f"hermes-evt-{evt_n:04d}"
            evt["timestamp"] = ts
            evt["source"] = "hermes:gateway:log"
            # 去重（同秒同类型同 payload）
            dedup_key = (ts, evt["type"], json.dumps(evt["payload"], sort_keys=True))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            events.append(evt)

    return events


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    out = None
    days = None
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--output" and i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--days" and i + 1 < len(sys.argv):
            days = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    events = convert(src, days)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"converted {len(events)} events → {out}")
    else:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()

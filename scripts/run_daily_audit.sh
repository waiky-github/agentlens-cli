#!/usr/bin/env bash
# agentlens 每日审计 + watchdog 漂移监控（systemd timer / cron 调度）
#
# 职责：
#   1. 转换全部 Hermes gateway.log（主 + 4 profile）→ 脱敏事件流
#   2. 合并 → agentlens audit 生成 HTML 报告（落盘 reports/）
#   3. watchdog 对比基线 → 有漂移则输出报警摘要（stdout，供 cron 推送）
#
# 退出码：0 = 无漂移（静默） / 1 = 有新增 high / 2 = 审计失败
set -uo pipefail

VENV=/home/agentuser/agentlens-venv
AUDIT="$VENV/bin/agentlens-audit"
PYTHON="$VENV/bin/python"
CONVERT=/home/agentuser/agentlens-cli/scripts/convert_gateway_log.py
LOG_DIR=/home/agentuser/.hermes/logs
REPORT_DIR=/home/agentuser/.hermes/agentlens-reports
BASELINE="$REPORT_DIR/baseline.json"
TODAY=$(date +%Y%m%d)
DAYS=1   # 只审最近 1 天（增量）

mkdir -p "$REPORT_DIR"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

# ── 1. 转换主 + 4 profile 的 gateway.log ──────────────────────────
EVENT_FILES=()
i=0
for log in "$LOG_DIR/gateway.log" \
           /home/agentuser/.hermes/profiles/*/logs/gateway.log; do
    [ -f "$log" ] || continue
    i=$((i+1))
    out="$WORKDIR/events_$i.jsonl"
    "$PYTHON" "$CONVERT" "$log" --days "$DAYS" --output "$out" >/dev/null 2>&1
    if [ -s "$out" ]; then
        EVENT_FILES+=("$out")
    fi
done

if [ "${#EVENT_FILES[@]}" -eq 0 ]; then
    echo "❌ agentlens 每日审计：无 gateway.log 可转换"
    exit 2
fi

# ── 2. 合并所有事件流 ────────────────────────────────────────────
MERGED="$WORKDIR/all_events.jsonl"
cat "${EVENT_FILES[@]}" > "$MERGED"
EVENT_COUNT=$(wc -l < "$MERGED")

# ── 3. 跑审计，生成 HTML 报告 ────────────────────────────────────
REPORT="$REPORT_DIR/audit-$TODAY.html"
if ! "$AUDIT" audit --input "$MERGED" --format html --output "$REPORT" >/dev/null 2>&1; then
    echo "❌ agentlens 每日审计：audit 失败（事件数 $EVENT_COUNT）"
    exit 2
fi

# ── 4. watchdog 漂移检测 ─────────────────────────────────────────
if [ ! -f "$BASELINE" ]; then
    # 首次运行：建基线，不报警
    "$AUDIT" watchdog --input "$MERGED" --write-baseline "$BASELINE" >/dev/null 2>&1
    echo "✅ agentlens 每日审计：首次基线已建立（$EVENT_COUNT 事件，报告 $REPORT）"
    exit 0
fi

WATCH_OUT=$("$AUDIT" watchdog --input "$MERGED" --baseline "$BASELINE" --history "$REPORT_DIR/drift-history.json" 2>&1)
WATCH_RC=$?

# 更新基线为今天（滚动基线：漂移对比的是昨天）
"$AUDIT" watchdog --input "$MERGED" --write-baseline "$BASELINE" >/dev/null 2>&1

if [ $WATCH_RC -ne 0 ]; then
    # 有漂移 → 输出报警摘要 + 推通知渠道
    SUMMARY=$(echo "$WATCH_OUT" | grep -E "delta|新增|增长|high" | head -10)
    ALERT="$WORKDIR/drift_alert.txt"
    SUBJECT="agentlens 漂移报警 $(date +%Y-%m-%d)"
    {
        echo "⚠️ agentlens 每日审计：检测到高风险漂移"
        echo "时间：$(date '+%Y-%m-%d %H:%M')"
        echo "事件数：$EVENT_COUNT"
        echo ""
        echo "摘要："
        echo "$SUMMARY"
        echo ""
        echo "报告：$REPORT"
    } > "$ALERT"
    # P2-3: 使用 notify 模块发送通知（若无配置则回退到 hermes send -t feishu）
    "$PYTHON" -m agentlens_cli notify "$SUBJECT" "$(cat "$ALERT")" >/dev/null 2>&1 || \
        hermes send -t feishu -s "$SUBJECT" -f "$ALERT" >/dev/null 2>&1 || true
    cat "$ALERT"
    exit 1
fi

# 无漂移 → 静默（cron no_agent 模式：空 stdout 不推送）
exit 0

#!/bin/bash
# ============================================================
# Sakura Backup cron wrapper
# Usage: cron-backup.sh <source_path> <name> <password>
# - run.sh backup を実行
# - 結果（成功・失敗）を Slack に通知
# - バックアップの exit code をそのまま返す
# ============================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="/home/ec2-user/anaconda3/envs/311/bin/python"

if [ $# -ne 3 ]; then
    echo "Usage: $0 <source_path> <name> <password>" >&2
    exit 1
fi

SOURCE="$1"
NAME="$2"
PASSWORD="$3"

START_AT="$(date '+%Y-%m-%d %H:%M:%S %Z')"

# --- Run backup ---
# load_env.sh の run_python は systemd 配下で conda activate が
# positional 引数を誤って取り込む問題があるため、conda 環境の python を直接呼ぶ
set +e
BACKUP_OUTPUT=$(cd "$SCRIPT_DIR" && "$PYTHON_BIN" sakura_backup.py backup \
    --source "$SOURCE" \
    --name "$NAME" \
    --password "$PASSWORD" \
    --quiet 2>&1)
RC=$?
set -e

END_AT="$(date '+%Y-%m-%d %H:%M:%S %Z')"
HOST="$(hostname)"

if [ $RC -eq 0 ]; then
    STATUS_LINE="✅ 成功"
else
    STATUS_LINE="❌ 失敗 (exit=$RC)"
fi

MSG="【Sakura Backup】${STATUS_LINE}
host:   ${HOST}
source: ${SOURCE}
name:   ${NAME}
start:  ${START_AT}
end:    ${END_AT}
---
${BACKUP_OUTPUT}"

# --- Slack notify (failure of slack must not affect backup exit code) ---
# load_env.sh / run_python は systemd 配下で conda activate バグを踏むため
# 直接 conda env の python で send_slack.py を呼ぶ。エラーは journal に残す。
SLACK_OUT=$(echo "$MSG" | "$PYTHON_BIN" /home/ec2-user/.claude/skills/slack-notify/send_slack.py 2>&1) || true
echo "[slack-notify] $SLACK_OUT"

# Echo result to journal too
echo "$MSG"

exit $RC

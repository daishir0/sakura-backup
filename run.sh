#!/bin/bash
cd "$(dirname "$0")"
source ~/.claude/lib/load_env.sh
run_python sakura_backup.py "$@"

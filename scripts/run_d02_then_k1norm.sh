#!/usr/bin/env bash
# D02 k1 fix 잔여 → 끝나면 normalize k1. race 회피 위해 직렬.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

wait_for_pid() { while kill -0 "$1" 2>/dev/null; do sleep 30; done; }

nohup python3 -u scripts/fix_glm_defects.py D02 --workers 2 --breaker 30 > logs/fix_d02_k1.log 2>&1 &
D02_PID=$!
echo "[chain] D02 PID=$D02_PID — 대기"
wait_for_pid "$D02_PID"
echo "[chain] D02 종료. normalize k1 시작."

nohup python3 -u scripts/normalize_concepts.py k1 > logs/norm_k1.log 2>&1 &
K1_PID=$!
echo "[chain] k1 PID=$K1_PID — 대기"
wait_for_pid "$K1_PID"
echo "[chain] k1 종료. 전체 완료."

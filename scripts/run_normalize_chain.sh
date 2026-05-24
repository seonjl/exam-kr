#!/usr/bin/env bash
# c1 → kt → nd 순차 normalize. 각 단계는 직전 단계의 정상 종료를 기다린다.
# k1 은 D02 fix 와 race 회피 위해 이 chain 에서 제외.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

wait_for_pid() {
    local pid="$1"
    while kill -0 "$pid" 2>/dev/null; do sleep 30; done
}

# 진행 중인 c1 normalize PID 찾기 (없으면 새로 시작)
C1_PID=$(pgrep -f "normalize_concepts.py c1" | head -1 || true)
if [ -z "$C1_PID" ]; then
    echo "[chain] c1 not running, 새로 시작"
    nohup python3 -u scripts/normalize_concepts.py c1 > logs/norm_c1.log 2>&1 &
    C1_PID=$!
fi
echo "[chain] c1 PID=$C1_PID — 대기"
wait_for_pid "$C1_PID"
echo "[chain] c1 종료. kt 시작."

nohup python3 -u scripts/normalize_concepts.py kt > logs/norm_kt.log 2>&1 &
KT_PID=$!
echo "[chain] kt PID=$KT_PID — 대기"
wait_for_pid "$KT_PID"
echo "[chain] kt 종료. nd 시작."

nohup python3 -u scripts/normalize_concepts.py nd > logs/norm_nd.log 2>&1 &
ND_PID=$!
echo "[chain] nd PID=$ND_PID — 대기"
wait_for_pid "$ND_PID"
echo "[chain] nd 종료. chain 완료."

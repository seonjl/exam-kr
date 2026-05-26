#!/usr/bin/env bash
# Concept body 생성 — 8 자격증 전부 동시 (최대 병렬), 모델 fallback chain 사용.
# 각 호출이 자동으로 glm-4.6 → glm-4.5 → glm-4.5-air → glm-4.5-flash 순서로 시도.
# 가장 좋은 모델 우선, 실패 시 자동 downgrade. 마지막 모델은 거의 항상 가능.
# idempotent — 중단/재시작 안전.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

export GLM_MODEL_CHAIN="${GLM_MODEL_CHAIN:-glm-4.6,glm-4.5,glm-4.5-air,glm-4.5-flash}"

LOG=logs/body_chain.log
log() { echo "[$(date +%m-%d_%H:%M:%S)] $*" | tee -a "$LOG"; }

log "GLM_MODEL_CHAIN=$GLM_MODEL_CHAIN"

pids=()
for ex in s2 g1 c1 g2 k1 nd sa kt; do
    nohup .venv/bin/python3 -u scripts/extract_concept_body.py "$ex" --workers 2 \
        > "logs/body_${ex}.log" 2>&1 &
    pid=$!
    pids+=("$pid")
    log "started $ex PID=$pid (workers=2)"
done
log "all 8 launched (16 concurrent calls × 4 models)"
for pid in "${pids[@]}"; do wait "$pid"; done
log "=== ALL DONE ==="

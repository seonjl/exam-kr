#!/usr/bin/env bash
# Concept body 생성 — 3 자격증씩 batch 직렬 (GLM rate limit 회피).
# 각 batch 내에서는 workers=1 (총 3 concurrent calls). 모델: glm-4.5-flash.
# idempotent — 중단/재시작 안전.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

export GLM_MODEL="${GLM_MODEL:-glm-4.5-flash}"

# 작은 것부터 처리 → 일찍 끝나는 batch 가 다음 batch 슬롯 확보
BATCH1=(s2 g1 c1)
BATCH2=(g2 k1 nd)
BATCH3=(sa kt)

LOG=logs/body_batched.log
log() { echo "[$(date +%m-%d_%H:%M:%S)] $*" | tee -a "$LOG"; }

run_batch() {
    local pids=()
    for ex in "$@"; do
        nohup .venv/bin/python3 -u scripts/extract_concept_body.py "$ex" --workers 1 \
            > "logs/body_${ex}.log" 2>&1 &
        local pid=$!
        pids+=("$pid")
        log "started $ex PID=$pid"
    done
    for pid in "${pids[@]}"; do wait "$pid"; done
    log "batch done: $*"
}

log "=== BATCH 1: ${BATCH1[*]} ==="
run_batch "${BATCH1[@]}"
log "=== BATCH 2: ${BATCH2[*]} ==="
run_batch "${BATCH2[@]}"
log "=== BATCH 3: ${BATCH3[*]} ==="
run_batch "${BATCH3[@]}"
log "=== ALL DONE ==="

#!/usr/bin/env bash
# Concept body 생성 — 8 자격증을 4 GLM 모델에 분산 (모델별 rate limit 회피).
# 각 자격증 workers=1, 모델당 2 자격증 = 모델당 ≤2 concurrent.
# 총 8 concurrent calls.
# idempotent — 중단/재시작 안전.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

LOG=logs/body_multimodel.log
log() { echo "[$(date +%m-%d_%H:%M:%S)] $*" | tee -a "$LOG"; }

# 자격증 → 모델 매핑 (큰 자격증을 다른 모델로 분산)
declare -A MODEL=(
    [s2]=glm-4.5-flash   # 133 todo (거의 끝남)
    [g1]=glm-4.5-flash   # 1226
    [c1]=glm-4.5-air     # 2322
    [g2]=glm-4.5-air     # 2618
    [k1]=glm-4.5         # 3284
    [nd]=glm-4.5         # 3808
    [sa]=glm-4.6         # 4285
    [kt]=glm-4.6         # 4391
)

pids=()
for ex in s2 g1 c1 g2 k1 nd sa kt; do
    m="${MODEL[$ex]}"
    GLM_MODEL="$m" nohup .venv/bin/python3 -u scripts/extract_concept_body.py "$ex" --workers 1 \
        > "logs/body_${ex}.log" 2>&1 &
    pid=$!
    pids+=("$pid")
    log "started $ex (model=$m) PID=$pid"
done
log "all 8 launched, waiting..."
for pid in "${pids[@]}"; do wait "$pid"; done
log "=== ALL DONE ==="

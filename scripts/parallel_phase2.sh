#!/usr/bin/env bash
# Phase 2 (normalize) 병렬 실행. 2개씩 묶어 시간 단축.
# 자격증당 normalize_concepts.py 호출 → idempotent.
# 호출 사이 cap 회복 대기 자동.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

LOG=logs/parallel_phase2.log
log() { echo "[$(date +%m-%d_%H:%M:%S)] $*" | tee -a "$LOG"; }

remaining_norm() {
    local ex=$1
    python3 -c "
import json
from pathlib import Path
n=0
for f in sorted(Path('data/$ex').glob('${ex}_*.json')):
    d=json.loads(f.read_text(encoding='utf-8'))
    for q in d.get('questions', []):
        if q.get('concepts') and not q.get('concept_ids'): n+=1
print(n)
"
}

# 자격증 단위 normalize, 최대 6회 재시도. cap 발동 시 30분 대기.
run_norm() {
    local ex=$1
    local logf="logs/norm_${ex}.log"
    local prev rem attempt=1
    rem=$(remaining_norm "$ex")
    [ "$rem" -eq 0 ] && { log "$ex OK (norm_left=0)"; return 0; }
    log "$ex 시작 (잔여=$rem)"
    prev=$rem
    while [ "$attempt" -le 6 ]; do
        python3 -u scripts/normalize_concepts.py "$ex" >> "$logf" 2>&1
        rem=$(remaining_norm "$ex")
        log "$ex try=$attempt 잔여=$rem"
        [ "$rem" -eq 0 ] && return 0
        if [ "$rem" -ge "$prev" ]; then
            log "  $ex 진전 없음 → 30분 대기"
            sleep 1800
        fi
        prev=$rem
        attempt=$((attempt+1))
    done
    log "$ex ⚠ 잔여 $rem (포기)"
    return 1
}

# Pair 1: sa + kt 병렬 (각각 가장 무거움)
log "=== Pair 1: sa || kt 병렬 시작 ==="
( run_norm sa ) &
PID_SA=$!
( run_norm kt ) &
PID_KT=$!
wait "$PID_SA"
log "sa 종료"
wait "$PID_KT"
log "kt 종료"
log "=== Pair 1 완료 ==="

# Pair 2: k1 + nd 병렬
log "=== Pair 2: k1 || nd 병렬 시작 ==="
( run_norm k1 ) &
PID_K1=$!
( run_norm nd ) &
PID_ND=$!
wait "$PID_K1"
log "k1 종료"
wait "$PID_ND"
log "nd 종료"
log "=== Pair 2 완료 ==="

# c1 단독 (5문항만 잔여라 빠름)
log "=== c1 ==="
run_norm c1

# 최종 요약
log "=== 최종 요약 ==="
python3 - <<'PY' | tee -a "$LOG"
import json
from pathlib import Path
print(f"{'ex':3} {'tot':>5} {'enr%':>6} {'con%':>6} {'nor%':>6}")
ok = True
for ex in ['s2','g1','g2','iz','sa','c1','k1','kt','nd']:
    tot=enr=con=nor=0
    for f in sorted(Path(f'data/{ex}').glob(f'{ex}_*.json')):
        d=json.loads(f.read_text(encoding='utf-8'))
        for q in d.get('questions', []):
            tot+=1
            if q.get('explanation_detailed'): enr+=1
            if q.get('concepts'): con+=1
            if q.get('concept_ids'): nor+=1
    print(f"{ex:3} {tot:5d} {100*enr/tot:5.1f}  {100*con/tot:5.1f}  {100*nor/tot:5.1f}")
    if con < tot or nor < tot: ok = False
print()
print("ALL 100%" if ok else "INCOMPLETE")
PY

log "=== parallel_phase2.sh 종료 ==="

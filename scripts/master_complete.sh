#!/usr/bin/env bash
# 모든 자격증 enrich/extract_concepts/normalize 가 100% 될 때까지 자동 반복.
# cap 발동 시 30분 대기 후 재시도. 모델은 스크립트 내부 sonnet+haiku fallback.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

LOG=logs/master_complete.log
EXAMS=(s2 g1 g2 iz sa c1 k1 kt nd)

log() { echo "[$(date +%m-%d_%H:%M:%S)] $*" | tee -a "$LOG"; }

wait_for_pid() { while kill -0 "$1" 2>/dev/null; do sleep 60; done; }

remaining_extract() {
    local ex=$1
    python3 -c "
import json
from pathlib import Path
n=0
for f in sorted(Path('data/$ex').glob('${ex}_*.json')):
    d=json.loads(f.read_text(encoding='utf-8'))
    for q in d.get('questions', []):
        if not q.get('concepts'): n+=1
print(n)
"
}

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

# Phase 0: 기존 chain (D02→normalize k1) 대기
CHAIN_PID=$(pgrep -f "run_d02_then_k1norm.sh" | head -1 || true)
if [ -n "$CHAIN_PID" ]; then
    log "기존 D02→k1norm chain (PID=$CHAIN_PID) 대기"
    wait_for_pid "$CHAIN_PID"
    log "기존 chain 종료"
fi

# Phase 1: extract_concepts 잔여 채우기
log "=== Phase 1: extract_concepts ==="
for ex in "${EXAMS[@]}"; do
    rem=$(remaining_extract "$ex")
    if [ "$rem" -eq 0 ]; then
        log "extract $ex OK (100%)"
        continue
    fi
    log "extract $ex 잔여=$rem → 처리 시작"
    attempt=1
    prev=$rem
    while [ "$attempt" -le 8 ]; do
        python3 -u scripts/extract_concepts.py "$ex" --workers 2 --breaker 30 \
            >> "logs/extract_${ex}.log" 2>&1
        new=$(remaining_extract "$ex")
        log "extract $ex try=$attempt 잔여=$new"
        [ "$new" -eq 0 ] && break
        if [ "$new" -ge "$prev" ]; then
            log "  진전 없음 → 30분 대기 (cap 회복)"
            sleep 1800
        fi
        prev=$new
        attempt=$((attempt+1))
    done
    final=$(remaining_extract "$ex")
    [ "$final" -gt 0 ] && log "  ⚠ extract $ex 잔여 $final (포기)"
done

# Phase 2: normalize 잔여
log "=== Phase 2: normalize_concepts ==="
for ex in "${EXAMS[@]}"; do
    rem=$(remaining_norm "$ex")
    if [ "$rem" -eq 0 ]; then
        log "normalize $ex OK"
        continue
    fi
    log "normalize $ex 잔여=$rem → 실행"
    attempt=1
    prev=$rem
    while [ "$attempt" -le 6 ]; do
        python3 -u scripts/normalize_concepts.py "$ex" \
            >> "logs/norm_${ex}.log" 2>&1
        new=$(remaining_norm "$ex")
        log "normalize $ex try=$attempt 잔여=$new"
        [ "$new" -eq 0 ] && break
        if [ "$new" -ge "$prev" ]; then
            log "  진전 없음 → 30분 대기"
            sleep 1800
        fi
        prev=$new
        attempt=$((attempt+1))
    done
    final=$(remaining_norm "$ex")
    [ "$final" -gt 0 ] && log "  ⚠ normalize $ex 잔여 $final (포기)"
done

# Phase 3: 최종 요약
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

log "=== master_complete.sh 종료 ==="

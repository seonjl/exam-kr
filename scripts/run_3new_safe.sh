#!/usr/bin/env bash
# 신규 자격증 3종 직렬 파이프라인 (c2/nw/pi).
# 백엔드: claude -p (구독 세션, API 키 불필요). enrich 는 sonnet, extract/normalize 는
# 스크립트 내장 haiku. workers=3, breaker=50. 모든 단계 idempotent — 기존 진행분 자동 스킵.

set -uo pipefail
WORKERS=${WORKERS:-3}
BREAKER=${BREAKER:-50}
MODEL=${MODEL:-sonnet}
EXAMS=${EXAMS:-"c2 nw pi"}

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "=== NEW3 LAUNCHER START @ $(date) (claude -p, enrich=$MODEL workers=$WORKERS breaker=$BREAKER) ==="

# enrich 단계 (claude -p --model sonnet, timeout 시 haiku 자동 폴백)
for db in $EXAMS; do
  echo "=== enrich $db @ $(date) ==="
  python3 -u scripts/enrich.py "$db" --workers "$WORKERS" --breaker "$BREAKER" --model "$MODEL"
  rc=$?
  echo "=== enrich $db rc=$rc @ $(date) ==="
  if [ $rc -ne 0 ]; then
    echo "WARN enrich $db non-zero rc — 1회 재시도"
    sleep 30
    python3 -u scripts/enrich.py "$db" --workers "$WORKERS" --breaker "$BREAKER" --model "$MODEL" || true
  fi
done

# extract_concepts 단계
for db in $EXAMS; do
  echo "=== concepts $db @ $(date) ==="
  python3 -u scripts/extract_concepts.py "$db" --workers "$WORKERS" --breaker "$BREAKER"
  rc=$?
  echo "=== concepts $db rc=$rc @ $(date) ==="
  if [ $rc -ne 0 ]; then
    echo "WARN concepts $db non-zero rc — 1회 재시도"
    sleep 30
    python3 -u scripts/extract_concepts.py "$db" --workers "$WORKERS" --breaker "$BREAKER" || true
  fi
done

# normalize 단계
for db in $EXAMS; do
  echo "=== normalize $db @ $(date) ==="
  python3 -u scripts/normalize_concepts.py "$db"
  echo "=== normalize $db DONE @ $(date) ==="
done

echo "=== NEW3 LAUNCHER DONE @ $(date) ==="

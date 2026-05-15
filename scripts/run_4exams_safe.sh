#!/usr/bin/env bash
# 안전 모드 단일 launcher: workers=2, breaker=50, 직렬 실행
# 다른 enrich/concept 프로세스가 동시에 돌지 않는다고 가정.
# 모든 단계 idempotent.

set -uo pipefail
WORKERS=${WORKERS:-2}
BREAKER=${BREAKER:-50}
EXAMS="c1 k1 kt nd"

echo "=== SAFE LAUNCHER START @ $(date) (workers=$WORKERS breaker=$BREAKER) ==="

# enrich 단계
for db in $EXAMS; do
  echo "=== enrich $db @ $(date) ==="
  python3 -u scripts/enrich.py "$db" --workers "$WORKERS" --breaker "$BREAKER"
  rc=$?
  echo "=== enrich $db rc=$rc @ $(date) ==="
  if [ $rc -ne 0 ]; then
    echo "WARN enrich $db non-zero rc — 한번 더 재시도"
    sleep 30
    python3 -u scripts/enrich.py "$db" --workers "$WORKERS" --breaker "$BREAKER" || true
  fi
done

# extract_concepts 단계
for db in $EXAMS; do
  echo "=== concepts $db @ $(date) ==="
  python3 -u scripts/extract_concepts.py "$db" --workers "$WORKERS" --breaker "$BREAKER"
  rc=$?
  echo "=== concepts $db rc=$rc @ $(date) ==="
  if [ $rc -ne 0 ]; then
    echo "WARN concepts $db non-zero rc — 한번 더 재시도"
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

echo "=== SAFE LAUNCHER DONE @ $(date) ==="

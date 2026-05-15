#!/usr/bin/env bash
# 기존에 돌고 있는 fetch_4exams.log 가 끝나기를 기다린 후
# enrich → extract_concepts → normalize 를 직렬로 수행한다.
# 모든 단계는 idempotent — 중간 중단/재시작 안전.

set -uo pipefail
WORKERS=${WORKERS:-4}
EXAMS="c1 k1 kt nd"
LOGDIR="logs"
mkdir -p "$LOGDIR"

# 1. fetch 완료 대기
echo "=== wait for fetch_4exams to finish @ $(date) ==="
while ! grep -q "ALL FETCH DONE" "$LOGDIR/fetch_4exams.log" 2>/dev/null; do
  sleep 30
done
echo "=== fetch 완료 감지 @ $(date) ==="

# fetch 완료 후 누락 회차 보충 (network blip 등으로 일부 빠진 경우 idempotent로 채움)
export FETCH_BASE_URL="${FETCH_BASE_URL:-https://www.comcbt.com/cbt}"
echo "=== FETCH SAFETY-NET PASS @ $(date) ==="
for db in $EXAMS; do
  echo "--- safety fetch-all $db @ $(date) ---"
  python3 -u scripts/fetch.py "$db" fetch-all || true
  python3 -u scripts/fetch.py "$db" manifest || true
done
echo "=== FETCH SAFETY-NET DONE @ $(date) ==="

echo "=== ENRICH PHASE @ $(date) ==="
for db in $EXAMS; do
  echo "=== enrich $db @ $(date) ==="
  python3 -u scripts/enrich.py "$db" --workers "$WORKERS"
  echo "=== enrich $db DONE @ $(date) ==="
done

echo "=== EXTRACT_CONCEPTS PHASE @ $(date) ==="
for db in $EXAMS; do
  echo "=== concepts $db @ $(date) ==="
  python3 -u scripts/extract_concepts.py "$db" --workers "$WORKERS"
  echo "=== concepts $db DONE @ $(date) ==="
done

echo "=== NORMALIZE PHASE @ $(date) ==="
for db in $EXAMS; do
  echo "=== normalize $db @ $(date) ==="
  python3 -u scripts/normalize_concepts.py "$db"
  echo "=== normalize $db DONE @ $(date) ==="
done

echo "=== ALL CHAIN DONE @ $(date) ==="

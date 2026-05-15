#!/usr/bin/env bash
# chain 종료 후 idempotent sweep — 누락 회차 보충 + enrich/concept/normalize 한번 더
# c1 catchup 으로 새로 들어온 회차들도 모두 AI 처리되도록 보장
set -uo pipefail
WORKERS=${WORKERS:-4}
EXAMS="c1 k1 kt nd"

# chain 완료 대기
while ! grep -q "ALL CHAIN DONE" logs/chain_4exams.log 2>/dev/null; do
  sleep 30
done
echo "=== POST-CHAIN SWEEP @ $(date) ==="

export FETCH_BASE_URL="${FETCH_BASE_URL:-https://www.comcbt.com/cbt}"

# 1. fetch 한번 더 (네트워크 blip 회복용 idempotent)
for db in $EXAMS; do
  echo "--- safety fetch-all $db @ $(date) ---"
  python3 -u scripts/fetch.py "$db" fetch-all || true
  python3 -u scripts/fetch.py "$db" manifest || true
done

# 2. enrich/concepts 누락 sweep (idempotent — 이미 처리된 문항 스킵)
for db in $EXAMS; do
  echo "--- enrich sweep $db @ $(date) ---"
  python3 -u scripts/enrich.py "$db" --workers "$WORKERS" || true
done
for db in $EXAMS; do
  echo "--- concepts sweep $db @ $(date) ---"
  python3 -u scripts/extract_concepts.py "$db" --workers "$WORKERS" || true
done
for db in $EXAMS; do
  echo "--- normalize sweep $db @ $(date) ---"
  python3 -u scripts/normalize_concepts.py "$db" || true
done

echo "=== ALL POSTCHAIN SWEEP DONE @ $(date) ==="

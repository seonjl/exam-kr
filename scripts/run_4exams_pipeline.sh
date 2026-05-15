#!/usr/bin/env bash
# 4종 (c1/k1/kt/nd) AI 파이프라인 직렬 실행
# fetch는 이미 다른 프로세스에서 진행 중일 수 있음 — 이 스크립트는 fetch 완료를 가정하고 enrich → extract → normalize 순으로 진행한다.
#
# 사용:
#   bash scripts/run_4exams_pipeline.sh enrich    # enrich.py 4종 직렬
#   bash scripts/run_4exams_pipeline.sh concepts  # extract_concepts.py 4종
#   bash scripts/run_4exams_pipeline.sh normalize # normalize_concepts.py 4종
#   bash scripts/run_4exams_pipeline.sh all       # enrich → concepts → normalize 전체
#
# 모든 단계는 idempotent (이미 처리된 문항/회차는 자동 스킵).

set -uo pipefail
WORKERS=${WORKERS:-4}
EXAMS="c1 k1 kt nd"
LOGDIR="logs"
mkdir -p "$LOGDIR"

run_enrich() {
  for db in $EXAMS; do
    echo "=== enrich $db @ $(date) ==="
    python3 -u scripts/enrich.py "$db" --workers "$WORKERS"
    echo "=== enrich $db DONE @ $(date) ==="
  done
}

run_concepts() {
  for db in $EXAMS; do
    echo "=== extract_concepts $db @ $(date) ==="
    python3 -u scripts/extract_concepts.py "$db" --workers "$WORKERS"
    echo "=== extract_concepts $db DONE @ $(date) ==="
  done
}

run_normalize() {
  for db in $EXAMS; do
    echo "=== normalize $db @ $(date) ==="
    python3 -u scripts/normalize_concepts.py "$db"
    echo "=== normalize $db DONE @ $(date) ==="
  done
}

case "${1:-}" in
  enrich) run_enrich ;;
  concepts) run_concepts ;;
  normalize) run_normalize ;;
  all)
    run_enrich
    run_concepts
    run_normalize
    echo "=== ALL PIPELINE DONE @ $(date) ==="
    ;;
  *) echo "usage: $0 {enrich|concepts|normalize|all}"; exit 1 ;;
esac

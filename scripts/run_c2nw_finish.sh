#!/usr/bin/env bash
# c2/nw 파이프라인 마무리 — extract 잔량 + normalize (claude -p haiku).
# GLM 크래시로 중단된 normalize 를 haiku 로 재실행. 모든 단계 idempotent.
set -uo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

for ex in c2 nw; do
  echo "=== [$ex] extract 잔량 @ $(date) ==="
  python3 -u scripts/extract_concepts.py "$ex" --workers 3 --breaker 50
  echo "=== [$ex] normalize @ $(date) ==="
  python3 -u scripts/normalize_concepts.py "$ex"
  echo "=== [$ex] DONE @ $(date) ==="
done
echo "=== c2/nw FINISH DONE @ $(date) ==="

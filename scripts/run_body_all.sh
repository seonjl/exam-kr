#!/usr/bin/env bash
# 8 자격증 concept body 병렬 생성. Haiku, workers=2 per exam.
# 각 자격증마다 idempotent — 중단/재시작 안전.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

EXAMS=(s2 g1 c1 k1 g2 nd sa kt)

for ex in "${EXAMS[@]}"; do
    nohup python3 -u scripts/extract_concept_body.py "$ex" --workers 2 \
        > "logs/body_${ex}.log" 2>&1 &
    echo "started $ex PID=$!"
done
wait
echo "=== ALL EXAMS DONE ==="

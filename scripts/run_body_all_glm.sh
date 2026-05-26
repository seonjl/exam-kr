#!/usr/bin/env bash
# 9 자격증 concept body 병렬 생성. GLM-5.1, workers=2 per exam.
# 각 자격증마다 idempotent — 중단/재시작 안전.
set -u
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python3}"
export GLM_MODEL="${GLM_MODEL:-glm-5.1}"

EXAMS=(s2 g1 g2 iz sa c1 k1 kt nd)
PIDS=()

for ex in "${EXAMS[@]}"; do
    "$PYTHON" -u scripts/extract_concept_body.py "$ex" --workers 2 \
        >> "logs/body_${ex}.log" 2>&1 &
    PIDS+=($!)
    echo "started $ex PID=${PIDS[-1]}"
done

echo "=== ALL STARTED (PIDs: ${PIDS[*]}) ==="
for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null
done
echo "=== ALL BODY DONE ==="

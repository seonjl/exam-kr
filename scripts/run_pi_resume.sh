#!/usr/bin/env bash
# pi 파이프라인 재개 supervisor.
# GLM 5시간 사용량 캡(429) 회복을 기다리며 enrich 를 완주시키고,
# 이어서 extract_concepts(workers=3)·normalize_concepts (claude -p haiku) 실행.
# 모든 단계 idempotent — 중단 후 재실행 안전.
set -uo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export GLM_MODEL="${GLM_MODEL:-glm-5.2}"
export GLM_PACE_INTERVAL="${GLM_PACE_INTERVAL:-1.5}"
LOG=logs/pipe_pi.log

remaining() {
  python3 - <<'PY'
import json, glob
n = 0
for f in glob.glob('data/pi/pi_*.json'):
    if 'sessions' in f:
        continue
    d = json.load(open(f, encoding='utf-8'))
    for q in d.get('questions', []):
        if not q.get('explanation_detailed'):
            n += 1
print(n)
PY
}

echo "===== [pi] RESUME supervisor 시작 @ $(date) =====" >> "$LOG"
while true; do
  left=$(remaining)
  echo "===== [pi] enrich 잔여 $left @ $(date) =====" >> "$LOG"
  [ "$left" -eq 0 ] && break
  # 캡 상태면 breaker=10 이 빠르게 끊어줌 → 30분 후 재시도
  python3 -u scripts/enrich.py pi --workers 1 --breaker 10 >> "$LOG" 2>&1
  left2=$(remaining)
  [ "$left2" -eq 0 ] && break
  echo "===== [pi] 중단 (잔여 $left2) — 30분 후 재시도 @ $(date) =====" >> "$LOG"
  sleep 1800
done
echo "===== [pi] enrich DONE @ $(date) =====" >> "$LOG"

python3 -u scripts/extract_concepts.py pi --workers 3 --breaker 50 >> "$LOG" 2>&1
echo "===== [pi] extract rc=$? @ $(date) =====" >> "$LOG"
python3 -u scripts/normalize_concepts.py pi >> "$LOG" 2>&1
echo "===== [pi] ALL DONE @ $(date) =====" >> "$LOG"

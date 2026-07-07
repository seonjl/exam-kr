#!/usr/bin/env bash
# pi extract 잔여분 완주 supervisor — claude 캡 회복 대기하며 반복,
# 완료 후 normalize 재실행(캐시 재개). idempotent.
set -uo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
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
        if not q.get('concepts'):
            n += 1
print(n)
PY
}

echo "===== [pi] FINISH supervisor 시작 @ $(date) =====" >> "$LOG"
while true; do
  left=$(remaining)
  echo "===== [pi] concepts 잔여 $left @ $(date) =====" >> "$LOG"
  [ "$left" -eq 0 ] && break
  python3 -u scripts/extract_concepts.py pi --workers 3 --breaker 20 >> "$LOG" 2>&1
  left2=$(remaining)
  [ "$left2" -eq 0 ] && break
  echo "===== [pi] extract 중단 (잔여 $left2) — 30분 후 재시도 @ $(date) =====" >> "$LOG"
  sleep 1800
done
echo "===== [pi] extract FINISH DONE @ $(date) =====" >> "$LOG"
python3 -u scripts/normalize_concepts.py pi >> "$LOG" 2>&1
echo "===== [pi] normalize rc=$? FINISH ALL DONE @ $(date) =====" >> "$LOG"

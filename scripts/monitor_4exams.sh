#!/bin/bash
# 4-exams 파이프라인 monitor: 한 줄 요약 + false-DONE 자동 복구.
# 출력 STATUS: ALL_DONE / RESTARTED / BREAKER_CLI_DOWN / RUNNING.

set -uo pipefail
cd "$(dirname "$0")/.."

PROGRESS=$(python3 -c "
import json, glob
parts = []
for db in ['c1','k1','kt','nd']:
    total=e=c=0
    for f in glob.glob(f'data/{db}/{db}_*.json'):
        d = json.load(open(f))
        for q in d['questions']:
            total += 1
            if q.get('explanation_detailed'): e += 1
            if q.get('concepts'): c += 1
    parts.append(f'{db} e={100*e/total:.1f} c={100*c/total:.1f}')
print(' | '.join(parts))
")

PROC=$(ps -eo args= | grep -E 'scripts/(enrich|extract_concepts|normalize_concepts|run_4exams_safe)' | grep -v grep | head -1 | awk '{print $2" "$3}')
PROC=${PROC:-none}

LAST_PHASE=$(grep -E "===.*(rc=| DONE @)" logs/safe_4exams.log | tail -1 | sed -E 's/=== //; s/ ===$//')

ALL_DONE=0
all_100=$(echo "$PROGRESS" | grep -oE 'e=100\.0 c=100\.0' | wc -l)
if [ "$all_100" = "4" ] && \
   [ -f data/concepts/c1/index.json ] && [ -f data/concepts/k1/index.json ] && \
   [ -f data/concepts/kt/index.json ] && [ -f data/concepts/nd/index.json ]; then
   ALL_DONE=1
fi

STATUS=RUNNING
RESTART_PID=
if [ "$ALL_DONE" = "1" ]; then
    STATUS=ALL_DONE
elif [ "$PROC" = "none" ]; then
    if timeout 30 claude -p "1+1=" 2>/dev/null | grep -q "^2$"; then
        nohup bash scripts/run_4exams_safe.sh >> logs/safe_4exams.log 2>&1 &
        RESTART_PID=$!
        STATUS=RESTARTED
    else
        STATUS=BREAKER_CLI_DOWN
    fi
fi

echo "progress: $PROGRESS"
echo "process: $PROC"
echo "last_phase: $LAST_PHASE"
if [ -n "$RESTART_PID" ]; then
    echo "STATUS: $STATUS pid=$RESTART_PID"
else
    echo "STATUS: $STATUS"
fi

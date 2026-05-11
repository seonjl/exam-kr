"""A2.known agree_with_ai 케이스에 academic_answer 필드 추가.

공식 답(answer)은 그대로 유지. academic_answer 는 학술/법령적으로 옳은 답을 기록.
이 필드는 웹앱에서 노출 정책에 따라 표시 여부 결정 가능.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"

results = json.loads((OUT / "known_verified.json").read_text("utf-8"))
agree_ai = [r for r in results if r.get("verdict") == "agree_with_ai"]
applied = 0
for r in agree_ai:
    exam = r["exam"]
    fl, num = r["qid"].split("#")
    p = DATA / exam / f"{fl}.json"
    doc = json.loads(p.read_text("utf-8"))
    for q in doc["questions"]:
        if q["number"] != int(num):
            continue
        if q.get("academic_answer"):
            print(f"  skip {r['qid']} (already set)")
            break
        q["academic_answer"] = {
            "answer": r["pass1"],
            "reason": r.get("pass1_reason"),
            "confidence_pass1": r.get("pass1_conf"),
            "confidence_pass2": r.get("pass2_conf"),
            "source": "audit_known_verify",
            "at": NOW,
            "note": "출처 답키(answer 필드)는 보존. 학술/법령적 정답은 academic_answer.answer.",
        }
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
        applied += 1
        print(f"  added academic_answer {r['qid']}: 공식={r['answer_field']} 학술={r['pass1']}")
        break
print(f"\n총 academic_answer 추가: {applied}")

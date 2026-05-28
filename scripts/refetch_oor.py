#!/usr/bin/env python3
"""정답 범위 초과 회차 refetch (비파괴).

기존 AI 필드(explanation_detailed, concepts, concept_ids, explanation_audit)는
그대로 보존하고 choices/answer/explanation 등 원본 필드만 갱신.

사용법:
  python3 scripts/refetch_oor.py [--apply]
  
  --apply 없으면 dry-run (변경 예정만 출력).
"""

import json, glob, sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from fetch import fetch_cbtbank_session

AI_FIELDS = [
    "explanation_detailed", "concepts", "concept_ids",
    "explanation_audit", "known_defect",
]


def find_oor_sessions():
    """정답 > 보기수인 회차 찾기."""
    result = {}
    for exam in ["g1", "g2"]:
        files = sorted(glob.glob(f"data/{exam}/{exam}_*.json"))
        for f in files:
            with open(f) as fh:
                data = json.load(fh)
            oor = sum(
                1 for q in data["questions"]
                if q.get("answer") and q.get("choices")
                and q["answer"] > len(q["choices"])
            )
            if oor > 0:
                result.setdefault(exam, []).append({
                    "date": data["date"],
                    "label": data.get("label", ""),
                    "path": f,
                    "oor_count": oor,
                    "total": len(data["questions"]),
                })
    return result


def merge(old_data, new_data):
    """새 fetch 결과에서 원본 필드만 가져오고 AI 필드는 기존 유지."""
    old_by_num = {q["number"]: q for q in old_data["questions"]}
    merged_questions = []

    for new_q in new_data["questions"]:
        num = new_q["number"]
        if num in old_by_num:
            old_q = old_by_num[num]
            # AI 필드 보존
            preserved = {k: old_q[k] for k in AI_FIELDS if k in old_q}
            # 새 원본 필드 + 보존된 AI 필드
            merged = {**new_q, **preserved}
            merged_questions.append(merged)
        else:
            merged_questions.append(new_q)

    return {
        **new_data,
        "questions": merged_questions,
        "count": len(merged_questions),
    }


def main():
    apply = "--apply" in sys.argv
    sessions = find_oor_sessions()

    total_sessions = sum(len(v) for v in sessions.values())
    total_oor = sum(s["oor_count"] for v in sessions.values() for s in v)
    print(f"정답 범위 초과: {total_sessions}회차, {total_oor}문항", flush=True)

    if not apply:
        print("\n[dry-run] --apply 로 실제 실행")
        for exam, items in sessions.items():
            for s in items:
                print(f"  {exam} {s['date']}: {s['oor_count']}/{s['total']}문항")
        return

    for exam, items in sessions.items():
        for s in items:
            print(f"\n--- {exam} {s['date']} ({s['oor_count']}개 초과) ---", flush=True)
            # 기존 데이터 백업
            with open(s["path"]) as fh:
                old_data = json.load(fh)

            # refetch (cbtbank)
            try:
                new_data = fetch_cbtbank_session(exam, s["date"])
            except Exception as e:
                print(f"  ✗ fetch 실패: {e}", flush=True)
                continue

            # 병합
            merged = merge(old_data, new_data)

            # 초과 해소 확인
            remaining = sum(
                1 for q in merged["questions"]
                if q.get("answer") and q.get("choices")
                and q["answer"] > len(q["choices"])
            )
            fixed = s["oor_count"] - remaining

            # AI 필드 보존 확인
            ai_ok = sum(
                1 for q in merged["questions"]
                if q.get("explanation_detailed")
            )

            # 저장
            with open(s["path"], "w", encoding="utf-8") as fh:
                json.dump(merged, fh, ensure_ascii=False, indent=2)

            print(f"  ✓ {fixed}개 수정, {remaining}개 잔존, AI필드 {ai_ok}/{len(merged['questions'])} 보존", flush=True)

    print("\n완료.")


if __name__ == "__main__":
    main()

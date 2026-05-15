"""iz_refetch_patch.json 의 변경사항을 data/iz/iz_<date>.json 에 적용한다.

비파괴: 변경 전 값은 q['<field>_pre_refetch'] 또는 q['refetch_log'] 에 보존.

흐름:
  1. data/audit/iz_refetch_patch.json 로드
  2. 각 qid 에 대해 변경 필드만 적용 (question, choices, answer, question_images, pass_rate)
  3. 변경 전 값을 q['refetch_log'] 에 push (timestamp, field, old, new)
  4. AI 생성 콘텐츠 (explanation_detailed, concepts, concept_ids, explanation_audit) 가
     무효해질 가능성이 있으므로 q['refetch_invalidates_ai'] = True 마킹.
     사용자가 enrich/extract_concepts 단계를 다시 돌리기 전까지는 그대로 둔다.
  5. known_defect 마킹 (missing_visual 등) 이 있고 question_images 가 채워졌다면 자동 해제 안 함
     (이미지 URL 만 채웠다고 결함이 해결되는 건 아니므로 보수적으로 유지).

사용:
  python3 scripts/audit_iz_apply_refetch.py --dry-run
  python3 scripts/audit_iz_apply_refetch.py --apply
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IZ = DATA / "iz"
OUT = DATA / "audit"
PATCH = OUT / "iz_refetch_patch.json"
APPLY_LOG = OUT / "iz_refetch_apply.log.json"

TRACKED = ["question", "choices", "answer", "question_images", "pass_rate"]


def split_qid(qid: str) -> tuple[str, int]:
    file_stem, num = qid.split("#")
    date = file_stem.split("_")[-1]
    return date, int(num)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.apply):
        raise SystemExit("--dry-run 또는 --apply 필요")

    patches = json.loads(PATCH.read_text("utf-8"))
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S")

    by_date: dict[str, list[tuple[int, dict]]] = {}
    for qid, p in patches.items():
        date, num = split_qid(qid)
        by_date.setdefault(date, []).append((num, p))

    summary = []
    for date, items in by_date.items():
        path = IZ / f"iz_{date}.json"
        data = json.loads(path.read_text("utf-8"))
        qmap = {q["number"]: q for q in data["questions"]}
        changed_in_file = 0
        for num, patch in items:
            q = qmap.get(num)
            if not q:
                summary.append({"qid": f"iz_{date}#{num}", "skip": "not found"})
                continue
            log_entries = []
            for field in TRACKED:
                if field not in patch:
                    continue
                old = q.get(field)
                new = patch[field]
                if old == new:
                    continue
                log_entries.append({
                    "at": now, "field": field, "old": old, "new": new,
                })
                if args.apply:
                    q[field] = new
            if log_entries:
                if args.apply:
                    q.setdefault("refetch_log", []).extend(log_entries)
                    q["refetch_invalidates_ai"] = True
                changed_in_file += 1
                summary.append({
                    "qid": f"iz_{date}#{num}",
                    "fields": [e["field"] for e in log_entries],
                })
        if args.apply and changed_in_file:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            print(f"[applied] {path.name}: {changed_in_file} questions updated")
        elif changed_in_file:
            print(f"[dry-run] {path.name}: would update {changed_in_file} questions")

    APPLY_LOG.write_text(json.dumps({
        "at": now, "applied": args.apply, "summary": summary,
    }, ensure_ascii=False, indent=2), "utf-8")
    print(f"→ {APPLY_LOG} ({len(summary)} entries)")


if __name__ == "__main__":
    main()

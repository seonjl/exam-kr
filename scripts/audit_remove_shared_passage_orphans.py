#!/usr/bin/env python3
"""cbtbank 출처 자격증의 공통지문 짝 문항 비파괴 제거 (p5, g9 …).

사용: python3 audit_remove_shared_passage_orphans.py p5

cbtbank 는 두 문항이 한 지문을 공유하는 쌍에서 지문을 가진 첫 문항을 싣지 않아(과목당 40→38),
남은 짝 문항("위 글의 …", "(19번 공통지문 문제)")은 지문 없이 풀 수 없다.
해당 문항을 세션 파일에서 빼서 data/audit/{exam}_removed_shared_passage.json 에 보존하고
(원 number 는 source_number), 세션 번호를 다시 매긴 뒤 manifest 를 갱신한다. idempotent.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch as _f  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PAT = re.compile(r"공통지문|^위\s*(글|<표>|<그림>|의 글)|^윗글")

def main() -> None:
    exam = sys.argv[1]
    OUT = DATA / "audit" / f"{exam}_removed_shared_passage.json"
    removed = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    sessions = []
    for p in sorted((DATA / exam).glob(f"{exam}_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        keep, gone = [], []
        for q in d["questions"]:
            if q.get("subject") != "헌법" and PAT.search(q.get("question") or ""):
                gone.append(q)
            else:
                keep.append(q)
        if gone:
            for q in gone:
                q["source_number"] = q["number"]
                q["session"] = d["date"]
                q["reason"] = "공통지문(출처 미제공) — cbtbank 가 지문을 가진 짝 문항을 싣지 않음"
                removed.append(q)
            for i, q in enumerate(keep, 1):
                q["number"] = i
            d["questions"] = keep
            d["count"] = len(keep)
            p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        sessions.append((d["date"], d["label"]))
        print(f"{p.name}: 제거 {len(gone)} → {len(keep)}문항")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(removed, ensure_ascii=False, indent=2), encoding="utf-8")
    _f._write_manifest(exam, sessions)
    _f._write_top_manifest()
    print(f"보존 파일: {OUT} ({len(removed)}문항)")

if __name__ == "__main__":
    main()

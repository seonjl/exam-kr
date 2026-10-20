#!/usr/bin/env python3
"""이미지 전사본(question_extras / choices[].extras)이 있는 문항의 AI 해설을 비파괴 초기화해 재생성 대상으로 만든다.

배경: enrich/extract 프롬프트가 전사본을 포함하지 않던 시기(2026-10-19 이전)에 생성된 해설은
지문·보기 내용을 보지 못한 채 쓰였다. 기존 값은 explanation_detailed_pre_extras 에 보존.

사용: python3 audit_clear_extras_explanations.py sw jc j1 j2 c2 pi nw [--dry]
"""
from __future__ import annotations
import json, sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

def main() -> None:
    dry = "--dry" in sys.argv
    exams = [a for a in sys.argv[1:] if not a.startswith("--")]
    for ex in exams:
        n = 0
        for p in sorted((DATA / ex).glob(f"{ex}_*.json")):
            d = json.loads(p.read_text(encoding="utf-8")); changed = False
            for q in d["questions"]:
                has = bool(q.get("question_extras")) or any(c.get("extras") for c in q.get("choices") or [])
                if not has or "explanation_detailed_pre_extras" in q:
                    continue
                q["explanation_detailed_pre_extras"] = q.pop("explanation_detailed", None)
                for k in ("concepts", "concept_ids", "explanation_audit"):
                    q.pop(k, None)
                n += 1; changed = True
            if changed and not dry:
                p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{ex}: {'(dry) ' if dry else ''}초기화 {n}문항")

if __name__ == "__main__":
    main()

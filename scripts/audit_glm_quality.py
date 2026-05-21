"""GLM이 채운 concepts / explanation_detailed / explanation_audit 의 결함을 카테고리로
자동 탐지하여 audit/glm_defects.json 으로 떨군다.

검사 카테고리:
  D01_missing_section          : explanation_detailed 가 '핵심 개념'/'정답 분석'/'오답 분석' 중 누락
  D02_5choice_e_missing        : 5선지 문항인데 explanation 오답분석에 ⑤ 미언급
  D03_audit_low_score          : explanation_audit.score 0 또는 1
  D04_abstract_concepts        : concepts 가 추상 분야명 (예: '정보', '회로', '문법')
  D05_concept_too_long         : concept 항목 80자 초과 (잘렸을 가능성)
  D06_explanation_short        : explanation_detailed 200자 미만 (불충분)
  D07_explanation_truncated    : 끝에 '...' 또는 절단 의심
  D08_concept_count_zero       : concepts 가 빈 배열
  D09_garbled_text             : 한자/특수문자 깨짐 의심 패턴 ('\\uXXXX' 텍스트화 등)
  D10_choice_text_in_concept   : concept 가 보기 텍스트 그대로 복사된 경우 (단순 매칭)

각 문항마다 hit 한 모든 카테고리 키를 모음. 카테고리별 카운트 + 자격증별 분포 출력.

사용법:
  python3 scripts/audit_glm_quality.py                # 전체
  python3 scripts/audit_glm_quality.py c1 k1          # 특정 자격증만
  python3 scripts/audit_glm_quality.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

ABSTRACT_SINGLE = {
    # 한국어 분야명 — concepts 의 추상성 판정 단어
    "정보", "회로", "법칙", "공식", "이론", "개념", "원리", "분야", "과학",
    "현상", "구조", "방법", "체계", "역사", "기술", "절차", "역할",
    "프로그래밍", "통계학", "회로이론", "수학", "물리", "한국사",
}

SECTION_TITLES = ["핵심 개념", "정답 분석", "오답 분석"]


def has_section(text: str, title: str) -> bool:
    """평문 안에 섹션 제목이 한 줄로 등장하는지."""
    if not text:
        return False
    return bool(re.search(rf"(^|\n)\s*{re.escape(title)}\s*\n", text))


# ⑤를 다루는 패턴 — '⑤', '5번', '⑤번' 중 하나 이상이 explanation 오답 분석 영역에 있어야 함
RE_FIFTH = re.compile(r"[⑤]|5\s*번")


GARBLED_PATTERNS = [
    re.compile(r"\\u[0-9a-fA-F]{4}"),  # 실패한 escape
    re.compile(r"\?\?\?"),
    re.compile(r"\(보기 누락\)"),
]


def scan_question(q: dict, exam: str, n_choices: int) -> set[str]:
    """문항 1개 결함 카테고리 키 set 반환."""
    flags: set[str] = set()
    detailed = (q.get("explanation_detailed") or "").strip()
    concepts = q.get("concepts") or []
    audit = q.get("explanation_audit") or {}
    choices = q.get("choices") or []

    # D01: 섹션 누락
    if detailed:
        missing = [t for t in SECTION_TITLES if not has_section(detailed, t)]
        if missing:
            flags.add("D01_missing_section")
    else:
        # 해설 자체가 없으면 형식 위반은 아니지만 일단 skip (다른 검사도 의미 없음)
        return flags

    # D02: 5선지 ⑤ 누락
    if n_choices >= 5 and detailed:
        # "오답 분석" 섹션 텍스트만 추출 시도 (없으면 전체)
        m = re.search(r"오답\s*분석\s*\n([\s\S]+?)(?:\n\s*$|$)", detailed)
        ob = m.group(1) if m else detailed
        if not RE_FIFTH.search(ob):
            flags.add("D02_5choice_e_missing")

    # D03: 낮은 audit score
    score = audit.get("score")
    if isinstance(score, int) and score <= 1:
        flags.add("D03_audit_low_score")

    # D04: 추상 분야명 concept
    if any(c.strip() in ABSTRACT_SINGLE for c in concepts):
        flags.add("D04_abstract_concepts")

    # D05: concept 너무 김
    if any(len(c) > 80 for c in concepts):
        flags.add("D05_concept_too_long")

    # D06: 해설 짧음
    if 0 < len(detailed) < 200:
        flags.add("D06_explanation_short")

    # D07: truncation 의심
    if detailed.rstrip().endswith(("...", "…")):
        flags.add("D07_explanation_truncated")

    # D08: concepts 빈 배열 (정상은 1~3개)
    if isinstance(concepts, list) and len(concepts) == 0 and q.get("concepts") is not None:
        flags.add("D08_concept_count_zero")

    # D09: 깨짐 패턴
    for pat in GARBLED_PATTERNS:
        if pat.search(detailed):
            flags.add("D09_garbled_text")
            break

    # D10: 보기 텍스트와 concept 가 완전 일치
    choice_texts = {(c.get("text") or "").strip() for c in choices if (c.get("text") or "").strip()}
    if any(c.strip() in choice_texts and len(c) > 10 for c in concepts):
        flags.add("D10_choice_text_in_concept")

    return flags


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exams", nargs="*", help="자격증 코드 (생략 시 전체)")
    ap.add_argument("--json", default="data/audit/glm_defects.json", help="결과 JSON 경로")
    ap.add_argument("--samples", type=int, default=5, help="카테고리별 샘플 개수")
    args = ap.parse_args()

    target_exams = args.exams or ["s2", "g1", "g2", "iz", "c1", "sa", "kt", "nd", "k1"]
    cat_counts: Counter = Counter()
    cat_by_exam: dict = defaultdict(Counter)
    cat_samples: dict = defaultdict(list)
    total_q = 0
    total_with_concepts = 0

    for exam in target_exams:
        for f in sorted((DATA / exam).glob(f"{exam}_*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            for q in d.get("questions", []):
                total_q += 1
                n_choices = len(q.get("choices") or [])
                if q.get("concepts"):
                    total_with_concepts += 1
                flags = scan_question(q, exam, n_choices)
                for k in flags:
                    cat_counts[k] += 1
                    cat_by_exam[k][exam] += 1
                    if len(cat_samples[k]) < args.samples:
                        cat_samples[k].append({
                            "exam": exam, "session": f.stem.split("_", 1)[-1],
                            "number": q.get("number"),
                            "concepts": q.get("concepts"),
                            "audit": q.get("explanation_audit"),
                            "expl_len": len(q.get("explanation_detailed") or ""),
                            "n_choices": n_choices,
                            "answer": q.get("answer"),
                        })

    out_path = ROOT / args.json
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {"total": total_q, "with_concepts": total_with_concepts,
                    "scanned_exams": target_exams},
        "counts": dict(cat_counts.most_common()),
        "by_exam": {k: dict(v) for k, v in cat_by_exam.items()},
        "samples": dict(cat_samples),
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== GLM 결과 결함 스캔 ===")
    print(f"전체 문항: {total_q}  concepts 있음: {total_with_concepts}")
    print(f"\n카테고리별 hit 수:")
    for k, v in cat_counts.most_common():
        per_exam = ", ".join(f"{e}={n}" for e, n in cat_by_exam[k].most_common())
        print(f"  {k:30s} {v:>5d}  ({per_exam})")
    print(f"\n결과 → {out_path}")


if __name__ == "__main__":
    main()

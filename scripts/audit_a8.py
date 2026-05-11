"""A8 — 시각자료를 시사하지만 첨부 이미지 없는 문항 상세 분석.

휴리스틱 분류:
  - likely_real_missing: 짧은 문제 + 시각자료 언급, 데이터 임베딩 흔적 없음
  - likely_text_embedded: 문제가 길고 숫자/리스트 패턴 풍부 — 시각자료가 텍스트로 들어옴
  - ambiguous: 어느 쪽도 명확하지 않음 → AI 검토 후보

출력:
  data/audit/a8_review.json — 분류 포함 raw
  data/audit/a8_review.md   — 자격증별 카테고리 요약
"""
from __future__ import annotations
import json
import re
import glob
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
EXAMS = ["s2", "g1", "g2", "iz"]

NV = re.compile(
    r"(다음\s*(그림|표|자료|보기|도표|지도|그래프)|아래\s*(그림|표|자료)"
    r"|<\s*그림\s*>|<\s*표\s*>|\[\s*그림\s*\]|\[\s*표\s*\])"
)
# 텍스트에 숫자 데이터/리스트가 풍부한지
DIGIT_RUN = re.compile(r"\d{2,}")
LIST_MARK = re.compile(r"(?:[ㄱㄴㄷㄹ]\.|①|②|③|④|⑤|\d+\)|\(\d+\))")
LINE_TABLE = re.compile(r"(?:^|\n).{0,40}\d.+\d", re.M)


def classify(qtext: str) -> tuple[str, dict]:
    n = len(qtext)
    digits = len(DIGIT_RUN.findall(qtext))
    lists = len(LIST_MARK.findall(qtext))
    table_like_lines = len(LINE_TABLE.findall(qtext))
    feats = {"len": n, "digit_runs": digits, "list_marks": lists, "table_like_lines": table_like_lines}

    # 강한 임베딩 신호: 숫자/리스트 풍부 OR 길이 충분 + 표 패턴
    if digits >= 5 or table_like_lines >= 3 or (n >= 350 and (digits >= 2 or lists >= 4)):
        return "likely_text_embedded", feats
    # 짧고 단서 없음 → 누락 의심
    if n <= 150 and digits <= 1 and table_like_lines == 0:
        return "likely_real_missing", feats
    return "ambiguous", feats


def main():
    rows = []
    for exam in EXAMS:
        for f in sorted(glob.glob(str(DATA / exam / f"{exam}_*.json"))):
            doc = json.loads(Path(f).read_text("utf-8"))
            file_label = Path(f).stem
            for q in doc["questions"]:
                qt = q.get("question") or ""
                m = NV.search(qt)
                if not m:
                    continue
                if q.get("question_images") or any(c.get("images") for c in q.get("choices") or []):
                    continue
                cat, feats = classify(qt)
                rows.append({
                    "exam": exam,
                    "file": file_label,
                    "number": q["number"],
                    "trigger": m.group(0),
                    "category": cat,
                    "feats": feats,
                    "subject": q.get("subject"),
                    "question": qt,
                })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "a8_review.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")

    by_cat_exam = Counter((r["category"], r["exam"]) for r in rows)
    md = ["# A8 첨부자료 누락 의심 분석", "",
          f"총 {len(rows)} 건. 휴리스틱 분류 후 ambiguous + likely_real_missing 은 별도 검토.", "",
          "## 카테고리 분포 (자격증 × 카테고리)", "",
          "| Exam | likely_real_missing | likely_text_embedded | ambiguous |",
          "|------|---------------------|---------------------|-----------|"]
    for exam in EXAMS:
        rm = by_cat_exam.get(("likely_real_missing", exam), 0)
        te = by_cat_exam.get(("likely_text_embedded", exam), 0)
        am = by_cat_exam.get(("ambiguous", exam), 0)
        md.append(f"| {exam} | **{rm}** | {te} | {am} |")

    md.append("")
    md.append("## likely_real_missing — 진짜 누락 의심 (우선 검토)")
    md.append("")
    for r in [x for x in rows if x["category"] == "likely_real_missing"]:
        md.append(f"- `{r['file']}#{r['number']}` ({r['exam']}, {r['subject']}) — `{r['trigger']}`")
        md.append(f"  - Q: {r['question'][:160]}")
    md.append("")
    md.append("## ambiguous — AI 검토 필요")
    md.append("")
    for r in [x for x in rows if x["category"] == "ambiguous"]:
        md.append(f"- `{r['file']}#{r['number']}` (len={r['feats']['len']}, digits={r['feats']['digit_runs']}) — `{r['trigger']}`")
        md.append(f"  - Q: {r['question'][:160]}")
    (OUT / "a8_review.md").write_text("\n".join(md), "utf-8")
    print(f"→ {OUT/'a8_review.md'} ({len(rows)}건)")
    for cat in ("likely_real_missing", "likely_text_embedded", "ambiguous"):
        n = sum(1 for r in rows if r["category"] == cat)
        print(f"  {cat}: {n}")


if __name__ == "__main__":
    main()

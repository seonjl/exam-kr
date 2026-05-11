"""A2.mismatch / A2.multi_mismatch 후보를 사람이 검토할 수 있게 컨텍스트 포함 추출.

산출:
  data/audit/a2_review.json — 후보 리스트 (문제/선택지/해설 포함)
  data/audit/a2_review.md   — 사람이 읽기 좋은 요약
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
EXAMS = ["s2", "g1", "g2", "iz"]


def find_question(exam: str, file_label: str, number: int) -> dict | None:
    f = DATA / exam / f"{file_label}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text("utf-8"))
    for q in d["questions"]:
        if q["number"] == number:
            return q
    return None


def section_of(detailed: str, header: str) -> str:
    import re
    m = re.search(rf"^\s*{re.escape(header)}\s*$\n(.*?)(?=^\s*(?:핵심 개념|정답 분석|오답 분석)\s*$|\Z)",
                  detailed, re.S | re.M)
    return m.group(1).strip() if m else ""


def main():
    rows = []
    for exam in EXAMS:
        rep_p = OUT / f"{exam}.json"
        if not rep_p.exists():
            continue
        rep = json.loads(rep_p.read_text("utf-8"))
        for issue in rep["issues"]:
            if not issue["code"].startswith(("A2.mismatch", "A2.multi_mismatch")):
                continue
            file_label, num = issue["qid"].split("#")
            q = find_question(exam, file_label, int(num))
            if q is None:
                continue
            rows.append({
                "exam": exam,
                "file": file_label,
                "number": int(num),
                "code": issue["code"],
                "known_error": issue.get("known_error", False),
                "answer_field": issue["answer_field"],
                "ai_final": issue["ai_final"],
                "ai_unique": issue["ai_unique"],
                "subject": q.get("subject"),
                "question": q.get("question"),
                "choices": [{"i": i+1, "text": c.get("text", "")[:120]} for i, c in enumerate(q.get("choices", []))],
                "answer_section": section_of(q.get("explanation_detailed", ""), "정답 분석")[:600],
            })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "a2_review.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")

    new_rows = [r for r in rows if not r["known_error"]]
    known_rows = [r for r in rows if r["known_error"]]

    md = ["# A2 정답키 의심 후보 검토 리스트", ""]
    md.append(f"총 {len(rows)} 건 / 새 발견 **{len(new_rows)}건** / 이미 알려진 오류 마커 있음 {len(known_rows)}건")
    md.append("")
    md.append("판정 카테고리: (a) AI 옳음/answer 키 오류 (b) AI 오류 (c) 둘 다 모호")
    md.append("")

    def render(group: list[dict], title: str) -> None:
        md.append(f"# {title} ({len(group)}건)")
        md.append("")
        by_exam: dict[str, list] = {}
        for r in group:
            by_exam.setdefault(r["exam"], []).append(r)
        for exam in EXAMS:
            if exam not in by_exam:
                continue
            md.append(f"## {exam} ({len(by_exam[exam])}건)")
            md.append("")
            for r in by_exam[exam]:
                md.append(f"### `{r['file']}#{r['number']}` — {r['code']}")
                md.append(f"- subject: {r['subject']}")
                md.append(f"- **answer 필드: {r['answer_field']}** / **AI 결론: {r['ai_final']}** (등장: {r['ai_unique']})")
                qshort = (r["question"] or "")[:200].replace("\n", " ")
                md.append(f"- Q: {qshort}")
                for c in r["choices"]:
                    star = " ★" if c["i"] == r["answer_field"] else ""
                    md.append(f"  - ({c['i']}) {c['text'][:80]}{star}")
                md.append(f"- 정답 분석 발췌(앞 300자): {r['answer_section'][:300].replace(chr(10), ' / ')}")
                md.append("")

    render(new_rows, "새 발견 (이미 알려진 오류 마커 없음)")
    render(known_rows, "이미 알려진 오류 (출처에 마커 있음 — AI 처리 검증용)")
    (OUT / "a2_review.md").write_text("\n".join(md), "utf-8")
    print(f"→ {OUT/'a2_review.md'} ({len(rows)}건)")


if __name__ == "__main__":
    main()

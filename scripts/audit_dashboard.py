"""모든 감사 산출을 모아 사람용 종합 대시보드 생성."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "audit"
EXAMS = ["s2", "g1", "g2", "iz"]


def load(name: str):
    p = OUT / name
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8"))


def main():
    md: list[str] = []
    md.append("# AI 콘텐츠 품질 감사 대시보드")
    md.append("")
    md.append("자동 생성. 각 섹션의 상세는 동일 디렉토리의 개별 파일 참고.")
    md.append("")

    # 1. 전체 감사 카운트
    md.append("## 1. 자격증별 종합")
    md.append("")
    md.append("| Exam | 문항 | A2 mismatch | A8 missing | A3 incomplete | A1 broken |")
    md.append("|------|------|-------------|------------|---------------|-----------|")
    for exam in EXAMS:
        rep = load(f"{exam}.json")
        if not rep:
            continue
        c = rep["issues_by_code"]
        a2 = sum(c.get(k, 0) for k in c if k.startswith("A2.mismatch") or k.startswith("A2.multi_mismatch"))
        a8 = c.get("A8.visual_implied_but_missing", 0)
        a3 = c.get("A3.incomplete_distractors", 0)
        a1 = c.get("A1.empty", 0) + c.get("A1.missing_sections", 0)
        md.append(f"| {exam} | {rep['questions']} | {a2} | {a8} | {a3} | {a1} |")
    md.append("")

    # 2. 적용된 정정 (corrections.log.json)
    corr = load("corrections.log.json") or []
    md.append("## 2. 적용된 데이터 정정")
    md.append("")
    md.append(f"총 {len(corr)} 건 적용 (`data/audit/corrections.log.json` 참고)")
    md.append("")
    by_kind = Counter(c["kind"] for c in corr)
    for kind, n in by_kind.most_common():
        md.append(f"- **{kind}**: {n}건")
    if corr:
        md.append("")
        md.append("### 상세")
        for c in corr:
            md.append(f"- `{c['qid']}` — {c['kind']}: {c.get('reason') or c.get('to', '')}")
    md.append("")

    # 3. A8 marking
    a8_log = load("a8_apply.log.json") or []
    a8_marked = sum(1 for x in a8_log if x.get("action") == "marked_defect")
    md.append("## 3. A8 첨부자료 누락 마킹")
    md.append("")
    md.append(f"`known_defect` 필드가 추가된 문항: **{a8_marked}건** (휴리스틱 + AI 검증)")
    md.append("")

    # 4. B1 재검수 결과
    rev = load("a2_revalidate.json") or []
    md.append("## 4. A2 새 발견 재검수 (B1)")
    md.append("")
    md.append(f"독립 재채점 {len(rev)}건. 카테고리:")
    by_v = Counter(r.get("verdict") for r in rev)
    for v, n in by_v.most_common():
        md.append(f"- **{v}**: {n}건")
    md.append("")

    # 5. 개념 정규화 감사 (P3)
    cr = load("concepts_review.json") or []
    md.append("## 5. 개념 정규화 거대 클러스터 감사 (P3)")
    md.append("")
    if cr:
        md.append("| Exam | ok | review | split |")
        md.append("|------|----|--------|-------|")
        for exam in EXAMS:
            rows = [r for r in cr if r["exam"] == exam]
            ok = sum(1 for r in rows if r.get("verdict") == "ok")
            rv = sum(1 for r in rows if r.get("verdict") == "review")
            sp = sum(1 for r in rows if r.get("verdict") == "split")
            md.append(f"| {exam} | {ok} | {rv} | {sp} |")
        md.append("")
        splits = [r for r in cr if r.get("verdict") == "split"]
        if splits:
            md.append(f"### 분리 권장 {len(splits)}건")
            for r in splits:
                md.append(f"- `{r['id']}` ({r['exam']}, {r['size']} members) — {r['name_ko']}")
            md.append("")

    # 6. no_conclusion 샘플 (P4) - 있으면
    nc = load("no_conclusion_sample.json")
    if nc:
        md.append("## 6. A2.no_conclusion 샘플 감사 (P4)")
        md.append("")
        by = Counter((r["exam"], r.get("verdict")) for r in nc if r.get("verdict"))
        md.append("| Exam | sampled | match | mismatch | mismatch률 |")
        md.append("|------|---------|-------|----------|------------|")
        for exam in EXAMS:
            ne = sum(1 for r in nc if r["exam"] == exam)
            m = by.get((exam, "match"), 0)
            mm = by.get((exam, "mismatch"), 0)
            ratio = f"{mm/ne*100:.1f}%" if ne else "-"
            md.append(f"| {exam} | {ne} | {m} | {mm} | {ratio} |")
        md.append("")

    # 7. 미해결/후속 작업
    md.append("## 7. 후속 작업 제안")
    md.append("")
    md.append("- A8 known_defect 마킹된 79건 — 원본 페이지 재추출 (FETCH_BASE_URL 환경변수 + extract 단계 재실행)")
    md.append("- 개념 정규화 split 권장 클러스터 — normalize_concepts.py 강제 분리안 적용")
    md.append("- A3 incomplete_distractors 74건 — 오답 분석 재생성 (P5)")
    md.append("- A2.no_conclusion 모집단 5천여건 — 샘플 결과로 정밀 재감사 범위 결정")
    md.append("")

    (OUT / "DASHBOARD.md").write_text("\n".join(md), "utf-8")
    print(f"→ {OUT/'DASHBOARD.md'}")


if __name__ == "__main__":
    main()

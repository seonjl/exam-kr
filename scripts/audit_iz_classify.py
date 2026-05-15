"""iz_full_revalidate.json 결과를 후처리하여 분류한다.

카테고리:
  - clean_match: 재검 == answer 키, ambiguous/defect 모두 false
  - vision_false_defect: defect_flagged 인데 question/choice 에 이미지가 첨부됨 (LLM이 못 봄 → 결함 아님)
  - real_defect_candidate: defect_flagged AND 이미지 없음 → 본문 진짜 결함 가능
  - mismatch_with_images: mismatch + 이미지 보유 → 답 비교 신뢰도 낮음 (재추출 후 재검수)
  - mismatch_text_only: mismatch + 이미지 없음 → answer 키 vs AI 비교 본격 후보
  - ambiguous: 모호 판정
  - error: claude 실패

산출:
  data/audit/iz_classify.json
  data/audit/iz_classify.md
  data/audit/iz_refetch_candidates.json  (재추출 후보 qid 리스트)
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IZ = DATA / "iz"
OUT = DATA / "audit"


def has_images(q: dict) -> bool:
    if q.get("question_images"):
        return True
    for c in q.get("choices", []):
        if c.get("images"):
            return True
    if "explanation_images" in q and q["explanation_images"]:
        return False  # 해설 이미지는 본문 결함 판단에 무관
    return False


def index_questions() -> dict[str, dict]:
    by_qid = {}
    for f in sorted(IZ.glob("iz_*.json")):
        if f.name == "sessions.json":
            continue
        data = json.loads(f.read_text("utf-8"))
        for q in data["questions"]:
            qid = f"{f.stem}#{q['number']}"
            by_qid[qid] = q
    return by_qid


def classify(rev: dict, q: dict) -> str:
    if rev.get("error"):
        return "error"
    has_img = has_images(q)
    rev_ans = rev.get("revalid_answer")
    key = rev.get("answer_key")
    is_mismatch = (rev_ans is not None and key is not None and rev_ans != key)

    if rev.get("defect"):
        if has_img:
            return "vision_false_defect"
        return "real_defect_candidate"
    if is_mismatch:
        if has_img:
            return "mismatch_with_images"
        return "mismatch_text_only"
    if rev.get("ambiguous"):
        return "ambiguous"
    if rev_ans == key:
        return "clean_match"
    return "unknown"


def main():
    rev_rows = json.loads((OUT / "iz_full_revalidate.json").read_text("utf-8"))
    questions = index_questions()
    classified = []
    cat_counts: dict[str, int] = {}
    for r in rev_rows:
        q = questions.get(r["qid"])
        if not q:
            continue
        cat = classify(r, q)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        classified.append({**r, "category": cat,
                           "has_images": has_images(q)})
    (OUT / "iz_classify.json").write_text(
        json.dumps(classified, ensure_ascii=False, indent=2), "utf-8")

    refetch_qids = [
        r["qid"] for r in classified
        if r["category"] in ("real_defect_candidate", "mismatch_text_only")
    ]
    (OUT / "iz_refetch_candidates.json").write_text(
        json.dumps(refetch_qids, ensure_ascii=False, indent=2), "utf-8")

    md = ["# iz 전체 B1 재검수 분류", ""]
    md.append(f"총 {len(classified)}건")
    md.append("")
    md.append("| 카테고리 | 건수 | 의미 |")
    md.append("|---------|------|------|")
    meanings = {
        "clean_match": "재검 = answer 키. 통과.",
        "mismatch_text_only": "재검 ≠ answer 키, 이미지 없음 — 학술 정정 후보",
        "mismatch_with_images": "재검 ≠ answer 키, 이미지 동반 — 재추출 후 재검수 필요",
        "real_defect_candidate": "AI가 결함 지적, 이미지 없음 — 재추출 후보",
        "vision_false_defect": "AI가 결함 지적했으나 이미지 첨부됨 — LLM 비전 한계로 인한 false positive",
        "ambiguous": "AI가 모호 판정",
        "error": "claude 호출 실패",
        "unknown": "분류 불가",
    }
    for k in ["clean_match", "mismatch_text_only", "mismatch_with_images",
              "real_defect_candidate", "vision_false_defect",
              "ambiguous", "error", "unknown"]:
        md.append(f"| {k} | {cat_counts.get(k, 0)} | {meanings[k]} |")
    md.append("")
    md.append(f"## 재추출 후보 (real_defect_candidate + mismatch_text_only): "
              f"{len(refetch_qids)}건")
    md.append("")
    for cat in ["mismatch_text_only", "real_defect_candidate",
                "mismatch_with_images", "ambiguous"]:
        items = [r for r in classified if r["category"] == cat]
        if not items:
            continue
        md.append(f"### {cat} ({len(items)}건)")
        md.append("")
        md.append("| qid | 과목 | answer 키 | 재검 | conf | reason |")
        md.append("|-----|------|-----------|------|------|--------|")
        for r in items:
            md.append(
                f"| `{r['qid']}` | {(r.get('subject') or '')[:18]} | "
                f"{r.get('answer_key')} | {r.get('revalid_answer','-')} | "
                f"{r.get('confidence','-')} | {(r.get('reason') or '')[:80]} |"
            )
        md.append("")

    (OUT / "iz_classify.md").write_text("\n".join(md), "utf-8")
    print(f"→ {OUT/'iz_classify.md'}")
    print(f"→ refetch candidates: {len(refetch_qids)}")
    for k, v in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

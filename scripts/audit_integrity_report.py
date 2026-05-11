"""모든 정정/마킹 결과를 통합한 데이터 무결성 리포트 생성.

산출:
  data/audit/INTEGRITY.md — 자격증별 결함 분류 + 적용된 정정 통계
  data/audit/integrity.json — 기계용 raw
"""
from __future__ import annotations
import json
import glob
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
EXAMS = ["s2", "g1", "g2", "iz"]


def main():
    summary = {
        "exams": {},
        "totals": {
            "questions": 0,
            "known_defect": 0,
            "by_defect_kind": Counter(),
            "corrections_applied": 0,
            "by_correction_kind": Counter(),
            "explanation_regenerated": 0,
            "answer_corrected": 0,
            "a3_regenerated": 0,
            "a1_fixed": 0,
        }
    }
    raw = []

    for exam in EXAMS:
        e_stats = {
            "questions": 0,
            "known_defect": 0,
            "by_defect_kind": Counter(),
            "answer_corrected": 0,
            "academic_answer_added": 0,
            "explanation_regenerated": 0,
            "a3_regenerated": 0,
            "a1_fixed": 0,
        }
        for f in sorted(glob.glob(str(DATA / exam / f"{exam}_*.json"))):
            doc = json.loads(Path(f).read_text("utf-8"))
            file_label = Path(f).stem
            for q in doc["questions"]:
                e_stats["questions"] += 1
                kd = q.get("known_defect")
                if kd:
                    e_stats["known_defect"] += 1
                    e_stats["by_defect_kind"][kd.get("kind", "?")] += 1
                    raw.append({"exam": exam, "qid": f"{file_label}#{q['number']}",
                                "kind": "known_defect", "detail": kd})
                if q.get("answer_original") is not None:
                    e_stats["answer_corrected"] += 1
                    raw.append({"exam": exam, "qid": f"{file_label}#{q['number']}",
                                "kind": "answer_corrected",
                                "from": q["answer_original"], "to": q["answer"],
                                "reason": q.get("correction", {}).get("reason")})
                if q.get("academic_answer"):
                    e_stats["academic_answer_added"] += 1
                    aa = q["academic_answer"]
                    raw.append({"exam": exam, "qid": f"{file_label}#{q['number']}",
                                "kind": "academic_answer_added",
                                "source_answer": q["answer"], "academic": aa["answer"],
                                "reason": aa.get("reason")})
                corr = q.get("correction") or {}
                if corr.get("kind_explanation") in ("regenerated", "regenerated_full"):
                    e_stats["explanation_regenerated"] += 1
                    raw.append({"exam": exam, "qid": f"{file_label}#{q['number']}",
                                "kind": "explanation_regenerated",
                                "subkind": corr.get("kind_explanation"),
                                "reason": corr.get("explanation_reason")})
                if q.get("a3_regenerated"):
                    e_stats["a3_regenerated"] += 1
                if q.get("a1_fixed"):
                    e_stats["a1_fixed"] += 1
        e_stats["by_defect_kind"] = dict(e_stats["by_defect_kind"])
        summary["exams"][exam] = e_stats
        for k in ("questions", "known_defect", "answer_corrected", "academic_answer_added",
                  "explanation_regenerated", "a3_regenerated", "a1_fixed"):
            summary["totals"][k] = summary["totals"].get(k, 0) + e_stats[k]
        for k, v in e_stats["by_defect_kind"].items():
            summary["totals"]["by_defect_kind"][k] += v

    summary["totals"]["by_defect_kind"] = dict(summary["totals"]["by_defect_kind"])
    summary["totals"]["corrections_applied"] = (
        summary["totals"]["answer_corrected"]
        + summary["totals"]["explanation_regenerated"]
        + summary["totals"]["a3_regenerated"]
        + summary["totals"]["a1_fixed"]
    )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "integrity.json").write_text(json.dumps({"summary": summary, "raw": raw},
                                        ensure_ascii=False, indent=2), "utf-8")

    md = ["# 데이터 무결성 리포트", "",
          f"총 문항 {summary['totals']['questions']:,} / known_defect {summary['totals']['known_defect']:,} ({summary['totals']['known_defect']/summary['totals']['questions']*100:.1f}%) / 자동 정정 적용 {summary['totals']['corrections_applied']:,}",
          ""]

    md.append("## 자격증별 요약")
    md.append("")
    md.append("| Exam | 문항 | known_defect | answer 정정 | academic | 해설 재생성 | A3 재생성 | A1 수정 |")
    md.append("|------|------|-------------|-------------|----------|------------|-----------|---------|")
    for exam in EXAMS:
        s = summary["exams"][exam]
        md.append(f"| {exam} | {s['questions']} | {s['known_defect']} ({s['known_defect']/s['questions']*100:.1f}%) | "
                  f"{s['answer_corrected']} | {s.get('academic_answer_added',0)} | {s['explanation_regenerated']} | {s['a3_regenerated']} | {s['a1_fixed']} |")

    md.append("")
    md.append("## known_defect 종류별 분포")
    md.append("")
    md.append("| Defect kind | s2 | g1 | g2 | iz | 합계 |")
    md.append("|-------------|----|----|----|----|------|")
    all_kinds = sorted(summary["totals"]["by_defect_kind"].keys())
    for kind in all_kinds:
        row = [kind]
        for exam in EXAMS:
            row.append(str(summary["exams"][exam]["by_defect_kind"].get(kind, 0)))
        row.append(str(summary["totals"]["by_defect_kind"][kind]))
        md.append("| " + " | ".join(row) + " |")
    md.append("")

    md.append("## 적용된 자동 정정")
    md.append("")
    md.append("### answer 필드 정정 (학술적 검증 + B1 재검수 통과만)")
    for r in raw:
        if r["kind"] == "answer_corrected":
            md.append(f"- `{r['qid']}` ({r['exam']}): {r['from']} → {r['to']} — {r.get('reason','')}")
    md.append("")
    md.append("### 해설 재생성")
    for r in raw:
        if r["kind"] == "explanation_regenerated":
            md.append(f"- `{r['qid']}` ({r['exam']}) — {r.get('reason','')}")
    md.append("")

    md.append("## 후속 액션 권장")
    md.append("")
    md.append(f"- **invalid_answer_index ({summary['totals']['by_defect_kind'].get('invalid_answer_index', 0)}건)**: 추출 단계에서 5번째 선택지 누락 — `extract_v2.py` 또는 `extract_concept_body.py` 의 선택지 추출 로직 점검 + 재추출 필요")
    md.append(f"- **missing_visual ({summary['totals']['by_defect_kind'].get('missing_visual', 0)}건)**: 본문에 그림/표 시사 + 첨부 이미지 부재 — 원본 페이지에서 이미지 재수집 필요 (FETCH_BASE_URL 환경변수 필요)")
    md.append(f"- **missing_question_body**: 문제 본문에 ㄱ/ㄴ/ㄷ 항목 누락 — 원본 재추출")
    md.append("")
    md.append("## 보존 정책")
    md.append("")
    md.append("모든 자동 정정은 비파괴: 원본은 `answer_original`, `explanation_detailed_pre_a1_fix`, `explanation_detailed_pre_a3` 필드에 보존. 롤백 가능.")

    (OUT / "INTEGRITY.md").write_text("\n".join(md), "utf-8")
    print(f"→ {OUT/'INTEGRITY.md'}")
    print(f"\n총 문항: {summary['totals']['questions']:,}")
    print(f"known_defect: {summary['totals']['known_defect']:,}")
    print(f"  by kind: {summary['totals']['by_defect_kind']}")
    print(f"자동 정정: {summary['totals']['corrections_applied']:,}")
    print(f"  answer 정정: {summary['totals']['answer_corrected']}")
    print(f"  academic_answer 추가: {summary['totals'].get('academic_answer_added', 0)}")
    print(f"  해설 재생성: {summary['totals']['explanation_regenerated']}")
    print(f"  A3 재생성: {summary['totals']['a3_regenerated']}")
    print(f"  A1 수정: {summary['totals']['a1_fixed']}")


if __name__ == "__main__":
    main()

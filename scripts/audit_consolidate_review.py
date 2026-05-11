"""모든 mismatch 후보를 한 파일로 통합. 사람이 검토할 우선순위 큐.

산출:
  data/audit/REVIEW_QUEUE.md
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"


applied_set: set[str] = set()


def section_for(title: str, items: list[dict], rationale: str) -> list[str]:
    # qid 정규화 — file+number 형태일 수도 있음
    for it in items:
        if not it.get("qid") and it.get("file") and it.get("number"):
            it["qid"] = f"{it['file']}#{it['number']}"
    filtered = [it for it in items if it.get("qid") not in applied_set]
    md = [f"## {title} ({len(filtered)}건 / 원래 {len(items)}건 중)", "", rationale, ""]
    items = filtered
    if not items:
        md.append("_(해당 없음 — 모두 적용 완료 또는 비대상)_")
        md.append("")
        return md
    for it in items:
        qid = it.get("qid")
        ans = it.get("answer_field", "?")
        ai = it.get("ai_final") or it.get("revalid", "?")
        verdict = it.get("verdict") or it.get("verified_verdict", "")
        reason = it.get("reason") or it.get("second_reason") or ""
        md.append(f"- `{qid}`: answer **{ans}** vs AI/재검 **{ai}** — {verdict}")
        if reason:
            md.append(f"  - 근거: {reason[:200]}")
    md.append("")
    return md


def applied_qids() -> set[str]:
    """이미 정정/마킹된 qid 집합 — answer_original 있거나 known_defect 있거나 explanation regenerated."""
    import glob
    applied = set()
    for exam in ["s2", "g1", "g2", "iz"]:
        for f in glob.glob(str(DATA / exam / f"{exam}_*.json")):
            doc = json.loads(Path(f).read_text("utf-8"))
            file_label = Path(f).stem
            for q in doc["questions"]:
                if (q.get("answer_original") is not None
                        or q.get("known_defect")
                        or (q.get("correction") or {}).get("kind_explanation") in ("regenerated", "regenerated_full")):
                    applied.add(f"{file_label}#{q['number']}")
    return applied


def main():
    global applied_set
    applied_set = applied_qids()
    applied = applied_set
    md = ["# 사람 검토 큐 (정정 후보 통합)", "",
          f"자동 정정 미적용 후보들. 우선순위 순. 각 항목은 사람이 학술/법령 근거로 최종 판정 후 적용. (이미 적용된 {len(applied)}건 제외)",
          ""]

    # 1. B1 1차 (이미 적용된 4건은 제외)
    revalid = json.loads((OUT / "a2_revalidate.json").read_text("utf-8"))
    held_b1 = [r for r in revalid if r.get("verdict") in ("재검수가 모호 판정", "answer 키 옳음 / AI 오류")]
    md += section_for(
        "1순위: B1 1차 보류 케이스 (참고용)",
        held_b1,
        "B1 1차 6건 중 4건은 적용됨. 나머지: 1건은 AI 해설이 답키와 다른데 재검수가 답키 옳다고 판정 (g2#108, **이미 해설 재생성 적용됨**), 1건은 데이터 결함 (g2#2)."
    )

    # 2. P4 1차 양차 합의
    p4 = json.loads((OUT / "p4_verified.json").read_text("utf-8"))
    p4_conf = [r for r in p4 if r.get("verified_verdict") == "confirmed_answer_key_error"]
    md += section_for(
        "2순위: P4 1차 양차 합의 mismatch",
        p4_conf,
        "P4 sampling 100건에서 발견 → B1 동일 프롬프트 2차 확인. 양차 합의했으나 학술 해석 모호하여 보류."
    )

    # 3. P4 확장 양차 합의
    p4e = json.loads((OUT / "p4_ext_verified.json").read_text("utf-8"))
    p4e_conf = [r for r in p4e if r.get("verified_verdict") == "confirmed_answer_key_error"]
    md += section_for(
        "3순위: P4 확장 양차 합의 mismatch",
        p4e_conf,
        "확장 200건 sampling 에서 발견 → 2차 합의."
    )

    # 4. A2.known (이미 source 마커 있는)
    known_a2 = []
    for exam in ["s2", "g1", "g2", "iz"]:
        rep = json.loads((OUT / f"{exam}.json").read_text("utf-8"))
        for issue in rep["issues"]:
            if issue["code"].startswith("A2.") and issue.get("known_error"):
                known_a2.append({
                    "qid": issue["qid"],
                    "answer_field": issue["answer_field"],
                    "ai_final": issue["ai_final"],
                    "verdict": issue["code"],
                })
    md += section_for(
        "4순위: A2.known — 출처에 이미 오류 마커가 있는 케이스",
        known_a2,
        "이미 '오류 신고가 접수된 문제' 마커 등이 박힌 문항. AI가 다른 답으로 결론. 출제자 의도와 학술적 정답이 다른 케이스 다수."
    )

    md.append("---")
    md.append("")
    md.append("## 일괄 처리 가이드")
    md.append("")
    md.append("각 후보를 검토 후 진짜 정정이라 판정하면:")
    md.append("```python")
    md.append("# scripts/audit_apply_fixes.py 의 ANSWER_FIXES 리스트에 추가")
    md.append("(\"<exam>\", \"<file_label>\", <number>, <from>, <to>, \"근거\"),")
    md.append("```")
    md.append("실행: `python3 scripts/audit_apply_fixes.py` (idempotent)")
    md.append("")

    (OUT / "REVIEW_QUEUE.md").write_text("\n".join(md), "utf-8")
    print(f"→ {OUT/'REVIEW_QUEUE.md'}")
    print(f"  P4 1차 합의: {len(p4_conf)}")
    print(f"  P4 확장 합의: {len(p4e_conf)}")
    print(f"  A2.known: {len(known_a2)}")


if __name__ == "__main__":
    main()

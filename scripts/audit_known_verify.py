"""A2.known (출처 분쟁 마커 있는 문항) B1 양차 검증.
적용 없이 결과만 기록 — 사용자가 어느 답을 채택할지 결정.

산출:
  data/audit/known_verified.json/.md
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"

EXAM_NAME = {"s2": "사회조사분석사 2급", "g1": "공인중개사 1차",
             "g2": "공인중개사 2차", "iz": "정보처리기사"}


def call_claude(p, timeout=240):
    r = subprocess.run(["claude", "-p", p], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout.strip()


PROMPT = """너는 한국 자격증 시험({exam_name}) 채점관이다. 본문과 선택지만 보고 정답을 신중히 판단하라.
기존 해설/정답 키 참고 금지. 본문에 "오류 신고가 접수된 문제" 등의 부가 안내문이 있어도 무시하라.

[과목] {subject}
[문제] {question}
[선택지]
{choices}

JSON 만:
{{"answer": 1-{n}, "confidence": 0.0-1.0, "ambiguous": true|false, "reason": "150자 이내"}}
"""


def parse_json(out):
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def find_q(exam, file_label, num):
    doc = json.loads((DATA / exam / f"{file_label}.json").read_text("utf-8"))
    for q in doc["questions"]:
        if q["number"] == num:
            return q
    return None


def main():
    # 모든 자격증의 A2.known 케이스 수집
    cands = []
    for exam in ["s2", "g1", "g2", "iz"]:
        rep = json.loads((OUT / f"{exam}.json").read_text("utf-8"))
        for issue in rep["issues"]:
            if not issue.get("known_error"):
                continue
            if not issue["code"].startswith("A2."):
                continue
            cands.append({
                "exam": exam,
                "qid": issue["qid"],
                "answer_field": issue["answer_field"],
                "ai_final": issue["ai_final"],
                "code": issue["code"],
            })
    print(f"A2.known 검증 대상: {len(cands)}건")

    results = []
    for i, c in enumerate(cands, 1):
        fl, num = c["qid"].split("#")
        q = find_q(c["exam"], fl, int(num))
        if q is None or q.get("known_defect"):
            results.append({**c, "skip": "defect"})
            continue
        choices = "\n".join(f"  ({k+1}) {ch.get('text','')}" for k, ch in enumerate(q["choices"]))
        # 첫 번째 패스
        prompt = PROMPT.format(exam_name=EXAM_NAME[c["exam"]], subject=q.get("subject") or "",
                               question=q.get("question") or "", choices=choices, n=len(q["choices"]))
        try:
            out1 = call_claude(prompt)
            p1 = parse_json(out1) or {}
            # 2차 (재현성 확인)
            out2 = call_claude(prompt)
            p2 = parse_json(out2) or {}
        except Exception as e:
            results.append({**c, "error": str(e)})
            print(f"  [{i}] ERROR {e}")
            continue
        a1, a2 = p1.get("answer"), p2.get("answer")
        amb = bool(p1.get("ambiguous") or p2.get("ambiguous"))
        if amb or a1 != a2:
            v = "inconsistent_or_ambiguous"
        elif a1 == c["answer_field"]:
            v = "agree_with_source"
        elif a1 == c["ai_final"]:
            v = "agree_with_ai"
        else:
            v = "new_answer"
        results.append({**c, "pass1": a1, "pass1_conf": p1.get("confidence"),
                        "pass1_reason": p1.get("reason"),
                        "pass2": a2, "pass2_conf": p2.get("confidence"),
                        "pass2_reason": p2.get("reason"),
                        "verdict": v})
        print(f"  [{i}/{len(cands)}] {c['qid']} src={c['answer_field']} ai={c['ai_final']} → 1차={a1} 2차={a2} ({v})")

    (OUT / "known_verified.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")

    from collections import Counter
    by_v = Counter(r.get("verdict") for r in results)
    md = ["# A2.known (출처 분쟁) B1 양차 검증", "",
          f"{len(results)} 건. 자동 적용 없음 — 출처 평가 시 학술적 정답 vs 공식 답 사이 선택은 사용자가 결정.", ""]
    md.append("| verdict | count |")
    md.append("|---------|-------|")
    for v, n in by_v.most_common():
        md.append(f"| {v} | {n} |")
    md.append("")
    md.append("## agree_with_ai — AI 학술적 정답이 두 번 일치")
    for r in results:
        if r.get("verdict") == "agree_with_ai":
            md.append(f"### `{r['qid']}` ({r['exam']})")
            md.append(f"- 공식 답: **{r['answer_field']}** | AI/재검 합의: **{r['pass1']}**")
            md.append(f"- 근거: {r.get('pass1_reason')}")
            md.append("")
    md.append("## agree_with_source — 두 번 검증 시 공식 답에 동의")
    for r in results:
        if r.get("verdict") == "agree_with_source":
            md.append(f"- `{r['qid']}`: 공식 답 {r['answer_field']} 재검 확인. AI(과거)는 {r['ai_final']} 주장이었으나 재검은 공식 답과 동일.")
    md.append("")

    (OUT / "known_verified.md").write_text("\n".join(md), "utf-8")
    print(f"\n→ {OUT/'known_verified.md'}")


if __name__ == "__main__":
    main()

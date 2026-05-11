"""확장 샘플링(no_conclusion_sample_ext) 의 mismatch 후보를 B1 동일 프롬프트로 재검수.

산출:
  data/audit/p4_ext_verified.json/.md
"""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"

EXAM_NAME = {"s2": "사회조사분석사 2급", "g1": "공인중개사 1차",
             "g2": "공인중개사 2차", "iz": "정보처리기사"}


def call_claude(prompt: str, *, timeout: int = 240) -> str:
    r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


PROMPT = """너는 한국 자격증 시험({exam_name}) 채점관이다. 아래 문항만 보고 정답을 신중하게 판단하라.
기존 해설/정답 키 참고 금지. 문제 본문과 선택지만 근거.
본문에 데이터/항목 누락이 의심되면 ambiguous=true.

[과목] {subject}
[문제] {question}
[선택지]
{choices}

JSON 만 출력:
{{"answer": 1-{n}, "confidence": 0.0-1.0, "ambiguous": true|false, "reason": "100자 이내"}}
"""


def parse_json(out: str):
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def find_q(exam, file_label, number):
    p = DATA / exam / f"{file_label}.json"
    doc = json.loads(p.read_text("utf-8"))
    for q in doc["questions"]:
        if q["number"] == number:
            return q
    return None


def main():
    rows = json.loads((OUT / "no_conclusion_sample_ext.json").read_text("utf-8"))
    cands = [r for r in rows if r.get("verdict") == "mismatch"]
    print(f"확장 mismatch 재검수: {len(cands)}건")
    results = []
    for i, c in enumerate(cands, 1):
        exam = c["exam"]
        fl, num = c["qid"].split("#")
        q = find_q(exam, fl, int(num))
        if q is None or q.get("known_defect"):
            results.append({**c, "skip": "known_defect_or_missing"})
            print(f"  [{i}] {c['qid']} skip")
            continue
        choices = "\n".join(f"  ({k+1}) {ch.get('text','')}" for k, ch in enumerate(q.get("choices", [])))
        prompt = PROMPT.format(
            exam_name=EXAM_NAME[exam], subject=q.get("subject") or "",
            question=q.get("question") or "", choices=choices, n=len(q["choices"]),
        )
        try:
            out = call_claude(prompt)
            parsed = parse_json(out) or {}
        except Exception as e:
            results.append({**c, "second_pass": None, "error": str(e)})
            print(f"  [{i}] ERROR: {e}")
            continue
        sp = parsed.get("answer")
        ambig = bool(parsed.get("ambiguous"))
        first = c.get("revalid")
        if ambig:
            verdict = "ambiguous"
        elif sp == first and sp != q["answer"]:
            verdict = "confirmed_answer_key_error"
        elif sp == q["answer"]:
            verdict = "first_pass_was_wrong"
        else:
            verdict = "disagreement"
        results.append({
            **c, "second_pass": sp, "second_confidence": parsed.get("confidence"),
            "second_ambiguous": ambig, "second_reason": parsed.get("reason"),
            "verified_verdict": verdict,
        })
        print(f"  [{i}] {c['qid']} answer={q['answer']} 1차={first} 2차={sp} → {verdict}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "p4_ext_verified.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")

    md = ["# 확장 샘플링 mismatch 재검수", ""]
    md.append("| qid | answer | 1차 | 2차 | conf | ambig | 판정 |")
    md.append("|-----|--------|-----|-----|------|-------|------|")
    for r in results:
        md.append(f"| `{r['qid']}` | {r['answer_field']} | {r.get('revalid')} | {r.get('second_pass')} | "
                  f"{r.get('second_confidence')} | {r.get('second_ambiguous')} | {r.get('verified_verdict','-')} |")
    confirmed = [r for r in results if r.get("verified_verdict") == "confirmed_answer_key_error"]
    md.append("")
    md.append(f"## 양차 합의 mismatch: {len(confirmed)}건")
    for r in confirmed:
        md.append(f"- `{r['qid']}`: answer {r['answer_field']} → {r['revalid']}")
        md.append(f"  - 2차 근거: {r.get('second_reason')}")
    (OUT / "p4_ext_verified.md").write_text("\n".join(md), "utf-8")
    print(f"\n→ {OUT/'p4_ext_verified.md'}")


if __name__ == "__main__":
    main()

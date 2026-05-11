"""P4 sampling 의 mismatch 후보를 B1 동일 프롬프트로 재검수.

목적: P4 1차 채점이 정확한지 두 번째 독립 채점으로 확인. 두 번 모두 동일하게
answer 키와 다른 답을 내면 진짜 정답키 의심으로 판정.

산출:
  data/audit/p4_verified.json
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
    r = subprocess.run(["claude", "-p", prompt],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


PROMPT = """너는 한국 자격증 시험({exam_name}) 채점관이다. 아래 문항만 보고 정답을 신중하게 판단하라.
기존 해설/정답 키 참고 금지. 문제 본문과 선택지만 근거.
문제 본문에 데이터 누락(표/그림 미첨부, 항목 일부 빠짐)이 의심되면 ambiguous=true 로 표기.

[과목] {subject}
[문제] {question}
[선택지]
{choices}

JSON 한 덩어리만 출력:
{{"answer": 1-{n} 정수, "confidence": 0.0-1.0, "ambiguous": true|false, "reason": "100자 이내"}}
"""


def parse_json(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def find_q(exam: str, file_label: str, number: int):
    p = DATA / exam / f"{file_label}.json"
    doc = json.loads(p.read_text("utf-8"))
    for q in doc["questions"]:
        if q["number"] == number:
            return q
    return None


def main():
    p4 = json.loads((OUT / "no_conclusion_sample.json").read_text("utf-8"))
    candidates = [r for r in p4 if r.get("verdict") == "mismatch"]
    print(f"P4 mismatch 재검수 대상: {len(candidates)}건")

    results = []
    for i, c in enumerate(candidates, 1):
        exam = c["exam"]
        file_label, num = c["qid"].split("#")
        q = find_q(exam, file_label, int(num))
        if q is None:
            continue
        # 데이터 결함 마킹된건 skip
        if q.get("known_defect"):
            results.append({**c, "second_pass": None, "skip": "known_defect"})
            print(f"  [{i}] {c['qid']} skip (known_defect)")
            continue
        choices = "\n".join(f"  ({k+1}) {ch.get('text','')}" for k, ch in enumerate(q.get("choices", [])))
        prompt = PROMPT.format(
            exam_name=EXAM_NAME[exam], subject=q.get("subject") or "",
            question=q.get("question") or "", choices=choices,
            n=len(q.get("choices") or []),
        )
        try:
            raw = call_claude(prompt)
            parsed = parse_json(raw) or {}
        except Exception as e:
            results.append({**c, "second_pass": None, "error": str(e)})
            print(f"  [{i}] {c['qid']} ERROR: {e}")
            continue
        sp = parsed.get("answer")
        ambig = bool(parsed.get("ambiguous"))
        first = c.get("revalid")
        # 합의 판정
        if ambig:
            verdict = "ambiguous"
        elif sp == first and sp != q["answer"]:
            verdict = "confirmed_answer_key_error"
        elif sp == q["answer"]:
            verdict = "p4_was_wrong"
        else:
            verdict = "disagreement"
        results.append({
            **c, "second_pass": sp, "second_confidence": parsed.get("confidence"),
            "second_ambiguous": ambig, "second_reason": parsed.get("reason"),
            "verified_verdict": verdict,
        })
        print(f"  [{i}] {c['qid']} answer={q['answer']} p4={first} second={sp} → {verdict}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "p4_verified.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")

    md = ["# P4 mismatch 재검수 결과", ""]
    md.append(f"P4 1차 mismatch {len(candidates)}건을 동일 B1 프롬프트로 2차 독립 채점.")
    md.append("")
    md.append("| qid | answer | 1차 | 2차 | conf | ambig | 판정 |")
    md.append("|-----|--------|-----|-----|------|-------|------|")
    for r in results:
        md.append(f"| `{r['qid']}` | {r['answer_field']} | {r.get('revalid')} | {r.get('second_pass')} | "
                  f"{r.get('second_confidence')} | {r.get('second_ambiguous')} | {r.get('verified_verdict','-')} |")
    md.append("")
    confirmed = [r for r in results if r.get("verified_verdict") == "confirmed_answer_key_error"]
    md.append(f"## 양차 합의 mismatch (confirmed_answer_key_error): {len(confirmed)}건")
    for r in confirmed:
        md.append(f"- `{r['qid']}` answer 필드 {r['answer_field']} → 재검 합의 {r['revalid']}")
        md.append(f"  - 2차 근거: {r.get('second_reason')}")
    (OUT / "p4_verified.md").write_text("\n".join(md), "utf-8")
    print(f"\n→ {OUT/'p4_verified.md'}")


if __name__ == "__main__":
    main()

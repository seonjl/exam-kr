"""P4: A2.no_conclusion 케이스를 stratified sampling 으로 독립 채점.

목적: "결론 표현 없음" 으로 검출 못한 mismatch 의 진짜 비율 추정.

전략:
  1. 4개 자격증의 no_conclusion 이슈를 각 exam 비율로 sampling (총 100건)
  2. 각 후보를 claude -p 로 독립 채점 (정답 키 미노출)
  3. answer 필드 vs 재검 결과 비교 → mismatch 비율

산출:
  data/audit/no_conclusion_sample.json
  data/audit/no_conclusion_sample.md
"""
from __future__ import annotations
import json
import random
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
import os, sys
EXAMS = (os.environ.get("EXAMS") or "s2,g1,g2,iz").split(",")
TOTAL_SAMPLES = int(os.environ.get("TOTAL_SAMPLES") or "100")
SEED = int(os.environ.get("SEED") or "7")
OUT_NAME = os.environ.get("OUT_NAME") or "no_conclusion_sample"

EXAM_NAME = {"s2": "사회조사분석사 2급", "g1": "공인중개사 1차",
             "g2": "공인중개사 2차", "iz": "정보처리기사"}


def call_claude(prompt: str, *, timeout: int = 180) -> str:
    r = subprocess.run(["claude", "-p", prompt],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


PROMPT = """너는 한국 자격증 시험({exam_name}) 채점관이다. 아래 문항만 보고 정답을 판단하라.
기존 해설/정답 키 참고 금지. 문제 본문과 선택지만 근거.

[과목] {subject}
[문제] {question}
[선택지]
{choices}

JSON 한 덩어리만 출력:
{{"answer": 1-{n}, "confidence": 0.0-1.0, "ambiguous": true|false, "reason": "60자"}}
"""


def parse_json(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def find_question(exam: str, file_label: str, number: int) -> dict | None:
    p = DATA / exam / f"{file_label}.json"
    doc = json.loads(p.read_text("utf-8"))
    for q in doc["questions"]:
        if q["number"] == number:
            return q
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # 후보 수집: audit JSON 의 A2.no_conclusion
    pool = {exam: [] for exam in EXAMS}
    for exam in EXAMS:
        rep = json.loads((OUT / f"{exam}.json").read_text("utf-8"))
        for issue in rep["issues"]:
            if issue["code"] == "A2.no_conclusion":
                pool[exam].append(issue["qid"])
    total = sum(len(v) for v in pool.values())
    print(f"no_conclusion total: {total}")

    rng = random.Random(SEED)
    samples = []
    for exam, qids in pool.items():
        n = round(TOTAL_SAMPLES * len(qids) / total)
        n = min(n, len(qids))
        chosen = rng.sample(qids, n) if qids else []
        for qid in chosen:
            samples.append((exam, qid))
    print(f"sampled: {len(samples)} (per exam: { {e: sum(1 for s in samples if s[0]==e) for e in EXAMS} })")

    results = []
    for i, (exam, qid) in enumerate(samples, 1):
        file_label, num = qid.split("#")
        q = find_question(exam, file_label, int(num))
        if q is None:
            continue
        choices = "\n".join(f"  ({i+1}) {c.get('text','')}" for i, c in enumerate(q.get("choices", [])))
        prompt = PROMPT.format(
            exam_name=EXAM_NAME[exam], subject=q.get("subject") or "",
            question=q.get("question") or "", choices=choices,
            n=len(q.get("choices") or []),
        )
        try:
            raw = call_claude(prompt)
            parsed = parse_json(raw) or {}
        except Exception as e:
            print(f"  [{i}/{len(samples)}] {qid} ERROR: {e}")
            results.append({"exam": exam, "qid": qid, "error": str(e)})
            continue
        revalid = parsed.get("answer")
        ambiguous = bool(parsed.get("ambiguous"))
        answer = q["answer"]
        verdict = "match" if revalid == answer else ("ambiguous" if ambiguous else "mismatch")
        results.append({
            "exam": exam, "qid": qid,
            "answer_field": answer,
            "revalid": revalid,
            "confidence": parsed.get("confidence"),
            "ambiguous": ambiguous,
            "reason": parsed.get("reason"),
            "verdict": verdict,
        })
        if i % 10 == 0 or verdict == "mismatch":
            print(f"  [{i}/{len(samples)}] {qid} answer={answer} revalid={revalid} → {verdict}")

    (OUT / f"{OUT_NAME}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")

    from collections import Counter
    by = Counter((r["exam"], r.get("verdict")) for r in results if r.get("verdict"))
    md = ["# A2.no_conclusion 샘플 감사 (P4)", "",
          f"총 {len(results)} 건 샘플 / 모집단 {total}", "",
          "| Exam | sampled | match | mismatch | ambiguous | mismatch률 |",
          "|------|---------|-------|----------|-----------|------------|"]
    for exam in EXAMS:
        ne = sum(1 for r in results if r["exam"] == exam)
        m = by.get((exam, "match"), 0)
        mm = by.get((exam, "mismatch"), 0)
        am = by.get((exam, "ambiguous"), 0)
        ratio = f"{mm/ne*100:.1f}%" if ne else "-"
        md.append(f"| {exam} | {ne} | {m} | {mm} | {am} | {ratio} |")
    md.append("")
    md.append("## mismatch 케이스 (재검 vs answer 키 불일치)")
    md.append("")
    for r in results:
        if r.get("verdict") == "mismatch":
            md.append(f"- `{r['qid']}` ({r['exam']}): answer={r['answer_field']} → revalid={r['revalid']} (conf {r.get('confidence')}) — {r.get('reason')}")
    (OUT / f"{OUT_NAME}.md").write_text("\n".join(md), "utf-8")
    print(f"\n→ {OUT/(OUT_NAME+'.md')}")


if __name__ == "__main__":
    main()

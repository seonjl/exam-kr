"""B1: A2 새 발견 후보를 claude -p 로 독립 재채점.

흐름:
  1. data/audit/a2_review.json 에서 known_error=False 인 후보 추림
  2. 각 후보를 자격증/문제/선택지만 보여주고 정답을 독립 판단 (기존 해설/answer 필드 미노출)
  3. 결과: answer 필드 / 기존 AI 결론 / 재검수 결론 3중 비교 → 카테고리

산출:
  data/audit/a2_revalidate.json
  data/audit/a2_revalidate.md
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"

EXAM_NAME = {
    "s2": "사회조사분석사 2급",
    "g1": "공인중개사 1차",
    "g2": "공인중개사 2차",
    "iz": "정보처리기사",
}


def call_claude(prompt: str, *, timeout: int = 180) -> str:
    r = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("claude returned empty output")
    return out


PROMPT_TMPL = """너는 한국 자격증 시험({exam_name}) 채점관이다. 아래 문항의 학술적/법령적 정답을 독립적으로 판단하라.

**중요:**
- 기존 해설, 정답 키, 출처를 참고하지 말고 오직 문제 본문과 선택지만 근거로 판단할 것.
- 문제 자체에 오류·결함(텍스트 깨짐, 선택지 모순 등)이 있으면 명시할 것.
- 답을 단일 번호로 정할 수 없으면 confidence 를 낮추고 reason 에 사유를 기재.

[과목] {subject}
[문제] {question}
[선택지]
{choices}

다음 JSON 한 덩어리만 출력하라(부가 설명 금지):
{{
  "answer": 1-{n_choices} 사이 정수 (가장 그럴듯한 단일 답),
  "confidence": 0.0~1.0,
  "ambiguous": true|false (선택지 중복/문제 결함 등으로 단일 답이 모호하면 true),
  "reason": "120자 이내 한국어 핵심 근거"
}}
"""


def build_prompt(row: dict) -> str:
    n = len(row["choices"])
    choices = "\n".join(f"  ({c['i']}) {c['text']}" for c in row["choices"])
    return PROMPT_TMPL.format(
        exam_name=EXAM_NAME.get(row["exam"], row["exam"]),
        subject=row.get("subject") or "",
        question=row["question"] or "",
        choices=choices,
        n_choices=n,
    )


def parse_json(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def categorize(answer_field: int, ai_final: int, revalid: int | None, ambiguous: bool) -> str:
    if revalid is None:
        return "재검수 파싱 실패"
    if ambiguous:
        return "재검수가 모호 판정"
    if revalid == answer_field and revalid == ai_final:
        return "셋 다 일치 (이 케이스는 도달하면 안됨)"
    if revalid == ai_final and revalid != answer_field:
        return "AI 옳음 / answer 키 오류"
    if revalid == answer_field and revalid != ai_final:
        return "answer 키 옳음 / AI 오류"
    return "셋 다 다름"


def main():
    review_p = OUT / "a2_review.json"
    rows = json.loads(review_p.read_text("utf-8"))
    candidates = [r for r in rows if not r.get("known_error", False)]
    print(f"새 발견 후보: {len(candidates)}건 재검수 시작", flush=True)

    results = []
    for i, r in enumerate(candidates, 1):
        qid = f"{r['file']}#{r['number']}"
        print(f"[{i}/{len(candidates)}] {qid} ...", flush=True)
        prompt = build_prompt(r)
        try:
            raw = call_claude(prompt)
            parsed = parse_json(raw)
        except Exception as e:
            results.append({**r, "revalidate": None, "error": str(e)})
            print(f"  ERROR: {e}")
            continue
        if not parsed:
            results.append({**r, "revalidate_raw": raw[:300], "revalidate": None, "error": "JSON parse failed"})
            print(f"  parse failed: {raw[:120]}")
            continue
        revalid = parsed.get("answer")
        ambiguous = bool(parsed.get("ambiguous"))
        verdict = categorize(r["answer_field"], r["ai_final"], revalid, ambiguous)
        results.append({
            **r,
            "revalidate": revalid,
            "confidence": parsed.get("confidence"),
            "ambiguous": ambiguous,
            "reason": parsed.get("reason"),
            "verdict": verdict,
        })
        print(f"  answer={r['answer_field']} ai={r['ai_final']} revalid={revalid} → {verdict}")

    (OUT / "a2_revalidate.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), "utf-8"
    )

    md = ["# A2 재검수 결과 (B1)", "",
          f"독립 채점한 {len(results)}건. 기존 해설/정답 키 노출 없이 문제+선택지만 보고 재판정.", ""]
    md.append("| qid | answer | AI | 재검 | conf | ambig | 판정 |")
    md.append("|-----|--------|----|------|------|-------|------|")
    for r in results:
        md.append(
            f"| `{r['file']}#{r['number']}` | {r['answer_field']} | {r['ai_final']} | "
            f"{r.get('revalidate')} | {r.get('confidence')} | {r.get('ambiguous')} | {r.get('verdict','-')} |"
        )
    md.append("")
    md.append("## 상세")
    for r in results:
        md.append("")
        md.append(f"### `{r['file']}#{r['number']}` — {r.get('verdict','-')}")
        md.append(f"- 과목: {r.get('subject')}")
        md.append(f"- answer 필드: **{r['answer_field']}** / 기존 AI: **{r['ai_final']}** / 재검: **{r.get('revalidate')}** (conf {r.get('confidence')}, ambig={r.get('ambiguous')})")
        if r.get("reason"):
            md.append(f"- 재검 근거: {r['reason']}")
        md.append(f"- 문제: {(r.get('question') or '')[:200]}")
        for c in r["choices"]:
            star = " ★" if c["i"] == r["answer_field"] else ""
            md.append(f"  - ({c['i']}) {c['text'][:80]}{star}")

    (OUT / "a2_revalidate.md").write_text("\n".join(md), "utf-8")
    print(f"\n→ {OUT/'a2_revalidate.md'}")


if __name__ == "__main__":
    main()

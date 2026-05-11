"""A3 재생성 (P5) 결과의 내용 품질을 샘플 검증.

20건 stratified 샘플 (자격증별 가중) → claude -p 로 각 오답 분석의 학술/법령적 타당성 평가.

산출:
  data/audit/a3_quality.json
  data/audit/a3_quality.md
"""
from __future__ import annotations
import json
import random
import re
import subprocess
import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
SAMPLE_SIZE = 20
SEED = 11

EXAM_NAME = {"s2": "사회조사분석사 2급", "g1": "공인중개사 1차",
             "g2": "공인중개사 2차", "iz": "정보처리기사"}


def call_claude(prompt: str, *, timeout: int = 240) -> str:
    r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


PROMPT = """너는 한국 자격증 시험({exam_name}) 해설 검수자다. 아래 문항의 **오답 분석** 섹션이 학술적/법령적으로 타당한지 평가하라.

[과목] {subject}
[문제] {question}
[선택지]
{choices}
[정답] {answer}번
[오답 분석]
{ohdap}

평가 기준:
- 각 오답이 왜 틀렸는지 정확하고 충분히 설명하는가?
- 사실관계 오류는 없는가?
- 정답을 제외한 모든 선택지를 다루고 있는가?

JSON 한 덩어리만 출력:
{{"score": 1-5 정수 (5=완벽), "issues": ["문제점 한국어로 1줄씩"], "verdict": "ok|minor_issue|needs_rework"}}
"""


def parse_json(out: str):
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def main():
    # 모든 a3_regenerated 케이스 수집
    cases = []
    for exam in ["s2", "g1", "g2", "iz"]:
        for f in sorted(glob.glob(str(DATA / exam / f"{exam}_*.json"))):
            doc = json.loads(Path(f).read_text("utf-8"))
            file_label = Path(f).stem
            for q in doc["questions"]:
                if q.get("a3_regenerated"):
                    cases.append((exam, file_label, q))
    print(f"a3_regenerated 총: {len(cases)}")

    rng = random.Random(SEED)
    sampled = rng.sample(cases, min(SAMPLE_SIZE, len(cases)))

    results = []
    for i, (exam, file_label, q) in enumerate(sampled, 1):
        choices = "\n".join(f"  ({k+1}) {c.get('text','')}" for k, c in enumerate(q.get("choices", [])))
        # 오답 분석 섹션 추출
        m = re.search(r"^\s*오답 분석\s*$\n(.*)", q["explanation_detailed"], re.S | re.M)
        ohdap = m.group(1).strip() if m else ""
        prompt = PROMPT.format(
            exam_name=EXAM_NAME[exam], subject=q.get("subject") or "",
            question=q.get("question") or "", choices=choices,
            answer=q["answer"], ohdap=ohdap,
        )
        try:
            out = call_claude(prompt)
            parsed = parse_json(out) or {}
        except Exception as e:
            results.append({"exam": exam, "qid": f"{file_label}#{q['number']}", "error": str(e)})
            print(f"  [{i}] ERROR: {e}")
            continue
        score = parsed.get("score")
        verdict = parsed.get("verdict")
        results.append({
            "exam": exam, "qid": f"{file_label}#{q['number']}",
            "score": score, "verdict": verdict,
            "issues": parsed.get("issues") or [],
        })
        print(f"  [{i}/{len(sampled)}] {file_label}#{q['number']} score={score} verdict={verdict}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "a3_quality.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")

    from collections import Counter
    by_v = Counter(r.get("verdict") for r in results)
    avg_score = sum(r["score"] for r in results if r.get("score")) / max(1, sum(1 for r in results if r.get("score")))

    md = ["# A3 재생성 품질 샘플 검증", "",
          f"{len(sampled)} 건 샘플 / 평균 score: {avg_score:.2f} / 5", ""]
    md.append("| verdict | count |")
    md.append("|---------|-------|")
    for v, n in by_v.most_common():
        md.append(f"| {v} | {n} |")
    md.append("")
    md.append("## minor_issue / needs_rework 케이스")
    for r in results:
        if r.get("verdict") not in ("ok", None):
            md.append(f"- `{r['qid']}` (score={r['score']}, verdict={r['verdict']})")
            for issue in r.get("issues", []):
                md.append(f"  - {issue}")
    (OUT / "a3_quality.md").write_text("\n".join(md), "utf-8")
    print(f"\n→ {OUT/'a3_quality.md'}")
    print(f"avg score: {avg_score:.2f}")


if __name__ == "__main__":
    main()

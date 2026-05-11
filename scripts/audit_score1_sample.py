"""explanation_audit.score=1 (improved=true) 케이스의 개선판 품질 샘플 검증.

원래 score=1 받은 해설이 개선 후에도 잔존 문제가 있는지 50건 stratified 샘플로 확인.

산출:
  data/audit/score1_sample.json/.md
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
SAMPLE_SIZE = 50
SEED = 23

EXAM_NAME = {"s2": "사회조사분석사 2급", "g1": "공인중개사 1차",
             "g2": "공인중개사 2차", "iz": "정보처리기사"}


def call_claude(prompt: str, *, timeout: int = 240) -> str:
    r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


PROMPT = """너는 한국 자격증 시험({exam_name}) 해설 검수자다. 아래 문항의 해설(개선 후)이 학술적으로 타당한지 평가하라.

[과목] {subject}
[문제] {question}
[선택지]
{choices}
[정답] {answer}번
[현재 해설]
{explanation}

평가 기준:
- 정답 결론이 명확하고 정답 키와 일치하는가?
- 핵심 개념·정답 분석·오답 분석 모두 사실관계 정확한가?
- 누락·오류·논리 모순이 없는가?

JSON 만 출력:
{{"score": 1-5 정수, "concerns": ["문제점 한국어로 1줄씩"], "verdict": "ok|minor|reissue"}}
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
    pool = []  # (exam, file_label, q)
    for exam in ["s2", "g1", "g2", "iz"]:
        for f in sorted(glob.glob(str(DATA / exam / f"{exam}_*.json"))):
            doc = json.loads(Path(f).read_text("utf-8"))
            file_label = Path(f).stem
            for q in doc["questions"]:
                a = q.get("explanation_audit") or {}
                if a.get("score") == 1 and a.get("improved"):
                    if q.get("known_defect"):
                        continue
                    pool.append((exam, file_label, q))
    print(f"score=1 improved=true 모집단: {len(pool)}")

    rng = random.Random(SEED)
    sampled = rng.sample(pool, min(SAMPLE_SIZE, len(pool)))

    results = []
    for i, (exam, file_label, q) in enumerate(sampled, 1):
        choices = "\n".join(f"  ({k+1}) {c.get('text','')[:200]}" for k, c in enumerate(q.get("choices", [])))
        prompt = PROMPT.format(
            exam_name=EXAM_NAME[exam], subject=q.get("subject") or "",
            question=q.get("question") or "", choices=choices,
            answer=q["answer"], explanation=q.get("explanation_detailed", "")[:2500],
        )
        try:
            out = call_claude(prompt)
            parsed = parse_json(out) or {}
        except Exception as e:
            results.append({"exam": exam, "qid": f"{file_label}#{q['number']}", "error": str(e)})
            print(f"  [{i}] ERROR: {e}")
            continue
        results.append({
            "exam": exam, "qid": f"{file_label}#{q['number']}",
            "score": parsed.get("score"),
            "verdict": parsed.get("verdict"),
            "concerns": parsed.get("concerns") or [],
        })
        print(f"  [{i}/{len(sampled)}] {file_label}#{q['number']} score={parsed.get('score')} verdict={parsed.get('verdict')}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score1_sample.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")

    from collections import Counter
    by_v = Counter(r.get("verdict") for r in results if not r.get("error"))
    valid = [r["score"] for r in results if r.get("score")]
    avg = sum(valid) / max(1, len(valid))

    md = ["# score=1 (improved) 잔존 품질 샘플 검증", "",
          f"{len(sampled)} 건 / 평균 score: {avg:.2f} / 5", ""]
    md.append("| verdict | count |")
    md.append("|---------|-------|")
    for v, n in by_v.most_common():
        md.append(f"| {v} | {n} |")
    md.append("")
    md.append("## reissue 필요 케이스")
    md.append("")
    for r in results:
        if r.get("verdict") == "reissue":
            md.append(f"### `{r['qid']}` ({r['exam']}) score={r['score']}")
            for c in r.get("concerns", []):
                md.append(f"- {c}")
            md.append("")
    (OUT / "score1_sample.md").write_text("\n".join(md), "utf-8")
    print(f"\n→ {OUT/'score1_sample.md'}")


if __name__ == "__main__":
    main()

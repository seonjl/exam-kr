"""A8 후보를 ambiguous 는 claude -p 로 분류 → 누락 확정된 케이스를 known_defect 로 마킹.

산출:
  data/audit/a8_apply.log.json — 처리 결과 로그
  data/{exam}/{file}.json      — 해당 문항에 known_defect 필드 추가
"""
from __future__ import annotations
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")


def call_claude(prompt: str, *, timeout: int = 120) -> str:
    r = subprocess.run(["claude", "-p", prompt],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


CLASSIFY_PROMPT = """다음 한국 자격증 시험 문제 본문에 대해, 시각자료(이미지/표/그림)가 본문 풀이에 필수인데 본문에 데이터가 임베딩되지 않았는지 판정하라.

[문제]
{question}

판정 기준:
- "missing": 본문이 그림/표/자료를 가리키는데 실제 데이터(숫자/항목/도표)가 본문에 들어있지 않아 풀이 불가능.
- "embedded": 본문 내에 풀이에 필요한 데이터가 텍스트로 충분히 들어있음.
- "metaphorical": "다음 자료/보기" 가 단순히 선택지를 가리키는 표현.

다음 JSON 만 출력:
{{"verdict": "missing|embedded|metaphorical", "confidence": 0.0-1.0, "reason": "30자 이내"}}
"""


def parse_json(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def mark_defect(exam: str, file_label: str, number: int, trigger: str, category: str, ai_verdict: str | None) -> bool:
    p = DATA / exam / f"{file_label}.json"
    doc = json.loads(p.read_text("utf-8"))
    for q in doc["questions"]:
        if q["number"] != number:
            continue
        if q.get("known_defect"):
            return False
        q["known_defect"] = {
            "kind": "missing_visual",
            "trigger": trigger,
            "audit_category": category,
            "ai_verdict": ai_verdict,
            "source": "audit_a8",
            "at": NOW,
        }
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
        return True
    return False


def main():
    rows = json.loads((OUT / "a8_review.json").read_text("utf-8"))
    log = []
    marked = 0

    # 1) likely_real_missing → 마킹
    for r in [x for x in rows if x["category"] == "likely_real_missing"]:
        if mark_defect(r["exam"], r["file"], r["number"], r["trigger"], r["category"], None):
            marked += 1
            log.append({"qid": f"{r['file']}#{r['number']}", "action": "marked_defect", "from": "heuristic"})
    print(f"likely_real_missing 마킹: {marked}")

    # 2) ambiguous → AI 분류 후 missing 만 마킹
    ambig = [x for x in rows if x["category"] == "ambiguous"]
    print(f"ambiguous AI 분류 시작: {len(ambig)}건")
    ai_marked = 0
    for i, r in enumerate(ambig, 1):
        try:
            out = call_claude(CLASSIFY_PROMPT.format(question=r["question"]))
            parsed = parse_json(out) or {}
            verdict = parsed.get("verdict")
        except Exception as e:
            verdict = None
            print(f"  [{i}/{len(ambig)}] {r['file']}#{r['number']} ERROR: {e}")
            log.append({"qid": f"{r['file']}#{r['number']}", "action": "error", "error": str(e)})
            continue
        print(f"  [{i}/{len(ambig)}] {r['file']}#{r['number']} → {verdict}")
        if verdict == "missing":
            if mark_defect(r["exam"], r["file"], r["number"], r["trigger"], r["category"], verdict):
                ai_marked += 1
                log.append({"qid": f"{r['file']}#{r['number']}", "action": "marked_defect", "from": "ai", "verdict": verdict})
        else:
            log.append({"qid": f"{r['file']}#{r['number']}", "action": "skipped", "verdict": verdict, "reason": parsed.get("reason")})

    print(f"ambiguous → missing 마킹: {ai_marked}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "a8_apply.log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n총 known_defect 추가: {marked + ai_marked} (heuristic {marked} + AI {ai_marked})")


if __name__ == "__main__":
    main()

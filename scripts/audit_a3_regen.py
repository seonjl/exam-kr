"""P5: A3 incomplete_distractors 케이스의 오답 분석 섹션 재생성.

기존 explanation_detailed 의 핵심개념/정답분석 은 유지, 오답분석만 재생성하여 누락된
선택지를 모두 다루도록.

산출:
  data/audit/a3_regen.log.json
  대상 문항의 explanation_detailed 갱신 + a3_regenerated 메타필드 추가
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


def call_claude(prompt: str, *, timeout: int = 240) -> str:
    r = subprocess.run(["claude", "-p", prompt],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


def split_sections(text: str) -> dict:
    SECTIONS = ("핵심 개념", "정답 분석", "오답 분석")
    out = {s: "" for s in SECTIONS}
    if not text:
        return out
    positions = []
    for s in SECTIONS:
        m = re.search(rf"^\s*{re.escape(s)}\s*$", text, re.M)
        if m:
            positions.append((m.start(), m.end(), s))
    positions.sort()
    for i, (_, end, s) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        out[s] = text[end:nxt].strip()
    return out


def find_q(exam: str, file_label: str, number: int):
    p = DATA / exam / f"{file_label}.json"
    doc = json.loads(p.read_text("utf-8"))
    for q in doc["questions"]:
        if q["number"] == number:
            return p, doc, q
    return None, None, None


PROMPT = """너는 한국 자격증 시험 채점 해설 작성자다. 아래 문항의 **오답 분석** 섹션만 작성하라.

[문제] {question}
[선택지]
{choices}
[정답] {answer}번
[기존 핵심 개념·정답 분석]
{prior}

규칙:
- 정답({answer}번)을 제외한 모든 오답 선택지에 대해 한 줄씩 왜 틀렸는지 간결히 설명.
- 각 항목은 ①/②/③/④/⑤ 기호로 시작.
- 군더더기 없이, 사실 위주.
- 해설/머리말 없이 오답 분석 내용만 출력. (헤더 '오답 분석' 없이 본문만)
"""


def main():
    cases = json.loads((OUT / "a3_cases.json").read_text("utf-8"))
    log = []
    print(f"A3 재생성 시작: {len(cases)}건")
    for i, case in enumerate(cases, 1):
        exam = case["exam"]
        file_label, num = case["qid"].split("#")
        p, doc, q = find_q(exam, file_label, int(num))
        if q is None:
            log.append({"qid": case["qid"], "action": "not_found"})
            continue
        if q.get("a3_regenerated"):
            log.append({"qid": case["qid"], "action": "skip_already_done"})
            continue
        # 데이터 결함이거나 누락이면 skip
        if q.get("known_defect"):
            log.append({"qid": case["qid"], "action": "skip_known_defect"})
            continue

        choices = "\n".join(f"  ({k+1}) {c.get('text','')}" for k, c in enumerate(q.get("choices", [])))
        prior = q.get("explanation_detailed", "")
        secs = split_sections(prior)
        prior_top = f"핵심 개념\n{secs['핵심 개념']}\n\n정답 분석\n{secs['정답 분석']}"

        prompt = PROMPT.format(
            question=q.get("question", ""), choices=choices,
            answer=q["answer"], prior=prior_top,
        )
        try:
            new_distractors = call_claude(prompt)
        except Exception as e:
            log.append({"qid": case["qid"], "action": "error", "error": str(e)})
            print(f"  [{i}/{len(cases)}] {case['qid']} ERROR: {e}")
            continue

        # 새 explanation_detailed 조립
        new_full = f"핵심 개념\n{secs['핵심 개념']}\n\n정답 분석\n{secs['정답 분석']}\n\n오답 분석\n{new_distractors.strip()}"
        q["explanation_detailed_pre_a3"] = q.get("explanation_detailed_pre_a3") or prior
        q["explanation_detailed"] = new_full
        q["a3_regenerated"] = {"at": NOW, "missing_before": case.get("missing"), "source": "audit_a3"}
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
        log.append({"qid": case["qid"], "action": "regenerated", "missing": case.get("missing")})
        print(f"  [{i}/{len(cases)}] {case['qid']} regenerated")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "a3_regen.log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), "utf-8")
    from collections import Counter
    by = Counter(l["action"] for l in log)
    print(f"\nDone. {dict(by)}")


if __name__ == "__main__":
    main()

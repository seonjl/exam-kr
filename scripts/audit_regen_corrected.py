"""answer 정정으로 explanation 불일치된 케이스들을 풀 해설 재생성."""
from __future__ import annotations
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

CASES = [
    ("s2", "s2_20030316", 61),
    ("s2", "s2_20000920", 68),
    ("s2", "s2_20110821", 59),
    ("g2", "g2_20050522", 16),
    ("g2", "g2_20050522", 32),
    ("g2", "g2_20071028", 15),
    # s2 deep 추가
    ("s2", "s2_20000920", 91),
    ("s2", "s2_20130602", 36),
    ("s2", "s2_20010923", 69),
    ("s2", "s2_20160508", 57),
    ("s2", "s2_20070805", 89),
    ("g1", "g1_20071028", 77),
    ("g2", "g2_20051030", 53),
]

EXAM_NAME = {"s2": "사회조사분석사 2급", "g1": "공인중개사 1차", "g2": "공인중개사 2차"}


def call_claude(prompt: str, *, timeout: int = 240) -> str:
    r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


PROMPT = """너는 한국 자격증 시험({exam_name}) 해설 작성자다. 아래 문항의 해설을 새로 작성하라.

[문제] {question}
[선택지]
{choices}
[정답] {answer}번
[정정 사유] {reason}

규칙:
- 정답이 {answer}번인 이유를 학술적/법령적으로 정확히 설명할 것.
- 출력은 다음 3섹션 (정확히 이 헤더):
  핵심 개념
  정답 분석
  오답 분석
- 오답 분석은 정답을 제외한 모든 선택지를 한 줄씩.
- 한국어, 군더더기 없는 톤. 250~600자 분량.

해설만 출력 (부가 텍스트 없이).
"""


def load_correction_reason(q: dict) -> str:
    """correction 메타필드에서 정정 사유 추출."""
    corr = q.get("correction") or {}
    return corr.get("reason") or "answer 필드 정정 (audit_a2_revalidate / p4 검증)"


def main():
    for exam, file_label, num in CASES:
        p = DATA / exam / f"{file_label}.json"
        doc = json.loads(p.read_text("utf-8"))
        for q in doc["questions"]:
            if q["number"] != num:
                continue
            if (q.get("correction") or {}).get("kind_explanation") == "regenerated_full":
                print(f"  skip {file_label}#{num} (already regenerated)")
                break
            choices = "\n".join(f"  ({i+1}) {c.get('text','')}" for i, c in enumerate(q["choices"]))
            prompt = PROMPT.format(
                exam_name=EXAM_NAME[exam],
                question=q.get("question") or "",
                choices=choices,
                answer=q["answer"],
                reason=load_correction_reason(q),
            )
            print(f"  regenerating {file_label}#{num} → {q['answer']} ...")
            try:
                new_expl = call_claude(prompt)
            except Exception as e:
                print(f"    ERROR: {e}")
                break
            for h in ("핵심 개념", "정답 분석", "오답 분석"):
                if h not in new_expl:
                    print(f"    WARN missing section {h}")
                    break
            q["explanation_detailed_pre_full_regen"] = q.get("explanation_detailed_pre_full_regen") or q.get("explanation_detailed")
            q["explanation_detailed"] = new_expl
            q["correction"] = {
                **(q.get("correction") or {}),
                "kind_explanation": "regenerated_full",
                "explanation_reason": "answer 정정 후 기존 해설과 모순 → 풀 해설 재생성",
                "source": "audit_regen_corrected",
                "at": NOW,
            }
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
            print(f"    done")
            break


if __name__ == "__main__":
    main()

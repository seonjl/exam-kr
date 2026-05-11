"""answer 필드가 선택지 범위를 벗어나는 데이터 결함 마킹.

탐지: answer < 1 or answer > len(choices) — 선택지 추출 단계 결함 의심.

산출:
  data/audit/invalid_answer.log.json
"""
from __future__ import annotations
import json
import glob
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    log = []
    for exam in ["s2", "g1", "g2", "iz"]:
        for f in sorted(glob.glob(str(DATA / exam / f"{exam}_*.json"))):
            doc = json.loads(Path(f).read_text("utf-8"))
            file_label = Path(f).stem
            changed = False
            for q in doc["questions"]:
                ans = q.get("answer")
                n = len(q.get("choices") or [])
                if not isinstance(ans, int) or n == 0:
                    continue
                if 1 <= ans <= n:
                    continue
                if q.get("known_defect"):
                    continue
                q["known_defect"] = {
                    "kind": "invalid_answer_index",
                    "answer": ans,
                    "n_choices": n,
                    "detail": f"answer={ans} 가 선택지 범위(1..{n}) 벗어남. 추출 단계 결함 의심.",
                    "source": "audit_invalid_answer",
                    "at": NOW,
                }
                log.append({"qid": f"{file_label}#{q['number']}",
                            "exam": exam, "answer": ans, "n_choices": n})
                changed = True
            if changed:
                Path(f).write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "invalid_answer.log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), "utf-8"
    )
    from collections import Counter
    by = Counter(l["exam"] for l in log)
    print(f"invalid answer 마킹: {len(log)}")
    for e, n in by.most_common():
        print(f"  {e}: {n}")


if __name__ == "__main__":
    main()

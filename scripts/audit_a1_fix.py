"""A1 missing_sections 케이스 자동 정정.

발견된 패턴:
  1. 'g1_20081026#55': '정answer 분석' 타이포 → '정답 분석'
  2. 'iz_*': 헤더 직후 개행 누락 ('핵심 개념소프트웨어...' → '핵심 개념\\n소프트웨어...')

산출:
  data/audit/a1_fix.log.json
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")

CASES = [
    ("g1", "g1_20081026", 55),
    ("iz", "iz_20220305", 32),
    ("iz", "iz_20220424", 24),
]

HEADERS = ("핵심 개념", "정답 분석", "오답 분석")


def fix_text(text: str) -> tuple[str, list[str]]:
    """A1 케이스 자동 정정. 반환: (fixed_text, change_log)."""
    changes = []
    # 1. '정answer 분석' 타이포 → '정답 분석'
    if "정answer 분석" in text:
        text = text.replace("정answer 분석", "정답 분석")
        changes.append("typo_jeongdab_analysis")
    # 2. 헤더 직후 개행 누락 — '핵심 개념X' 패턴 (X=한글) → '핵심 개념\nX'
    for h in HEADERS:
        pat = re.compile(rf"({re.escape(h)})(?=[가-힣])")
        if pat.search(text):
            text = pat.sub(r"\1\n", text)
            changes.append(f"header_newline:{h}")
    return text, changes


def main():
    log = []
    for exam, file_label, num in CASES:
        p = DATA / exam / f"{file_label}.json"
        doc = json.loads(p.read_text("utf-8"))
        for q in doc["questions"]:
            if q["number"] != num:
                continue
            orig = q.get("explanation_detailed", "")
            fixed, changes = fix_text(orig)
            if not changes:
                log.append({"qid": f"{file_label}#{num}", "action": "no_change"})
                print(f"  {file_label}#{num}: no change")
                continue
            q["explanation_detailed_pre_a1_fix"] = orig
            q["explanation_detailed"] = fixed
            q["a1_fixed"] = {"at": NOW, "changes": changes, "source": "audit_a1_fix"}
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
            log.append({"qid": f"{file_label}#{num}", "action": "fixed", "changes": changes})
            print(f"  {file_label}#{num}: {changes}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "a1_fix.log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nDone: {sum(1 for l in log if l['action']=='fixed')} fixed")


if __name__ == "__main__":
    main()

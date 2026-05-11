"""P3: 개념 정규화 품질 감사.

거대 클러스터(과병합 의심)에 대해 claude -p 로 outlier member 식별.

산출:
  data/audit/concepts_review.json — 클러스터별 검증 결과
  data/audit/concepts_review.md   — 사람용 요약
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
EXAMS = ["s2", "g1", "g2", "iz"]
TOP_N_PER_EXAM = 5  # 자격증별 검사할 거대 클러스터 수
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")


def call_claude(prompt: str, *, timeout: int = 180) -> str:
    r = subprocess.run(["claude", "-p", prompt],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    return r.stdout.strip()


PROMPT = """너는 한국 자격증 시험 개념 정규화 검증 전문가다. 아래 canonical concept 의 members 목록이 실제로 같은 개념을 가리키는지 평가하라.

[자격증] {exam_name}
[Canonical] {name_ko} (id: {cid})
[Members] (총 {n}개)
{members}

다음 JSON 한 덩어리만 출력:
{{
  "coherence": 1-5 정수 (1=대부분 다른 개념, 5=완벽 일치),
  "outliers": ["원래 canonical 과 어울리지 않는 member 문자열들"],
  "subgroups": ["만약 둘 이상의 개념이 섞여있다면, 자연스러운 분리안. 형식: '하위개념명: member1, member2'. 없으면 빈 리스트."],
  "verdict": "ok|review|split"
}}
"""

EXAM_NAME = {"s2": "사회조사분석사 2급", "g1": "공인중개사 1차", "g2": "공인중개사 2차", "iz": "정보처리기사"}


def parse_json(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for exam in EXAMS:
        idx = json.loads((DATA / "concepts" / exam / "index.json").read_text("utf-8"))
        big = sorted(
            ((cid, info) for cid, info in idx.items() if len(info.get("members") or []) >= 8),
            key=lambda x: -len(x[1]["members"])
        )[:TOP_N_PER_EXAM]
        print(f"[{exam}] 검사 대상 거대 클러스터: {len(big)}")
        for cid, info in big:
            members = info["members"]
            members_str = "\n".join(f"  - {m}" for m in members)
            prompt = PROMPT.format(
                exam_name=EXAM_NAME[exam], name_ko=info["name_ko"],
                cid=cid, n=len(members), members=members_str,
            )
            print(f"  {cid} ({len(members)} members) ...", flush=True)
            try:
                out = call_claude(prompt)
                parsed = parse_json(out) or {}
            except Exception as e:
                results.append({"exam": exam, "id": cid, "name_ko": info["name_ko"],
                                "size": len(members), "error": str(e)})
                print(f"    ERROR: {e}")
                continue
            results.append({
                "exam": exam, "id": cid, "name_ko": info["name_ko"],
                "size": len(members),
                "coherence": parsed.get("coherence"),
                "verdict": parsed.get("verdict"),
                "outliers": parsed.get("outliers") or [],
                "subgroups": parsed.get("subgroups") or [],
            })
            print(f"    coherence={parsed.get('coherence')} verdict={parsed.get('verdict')}")

    (OUT / "concepts_review.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")

    md = ["# 개념 정규화 품질 감사 (P3)", "",
          f"각 자격증 거대 클러스터(members ≥ 8) 상위 {TOP_N_PER_EXAM}개를 AI 평가.", "",
          "## 자격증별 verdict 분포", ""]
    from collections import Counter
    v_count = Counter((r["exam"], r.get("verdict")) for r in results)
    md.append("| Exam | ok | review | split | error/etc |")
    md.append("|------|----|--------|-------|-----------|")
    for exam in EXAMS:
        ok = v_count.get((exam, "ok"), 0)
        rv = v_count.get((exam, "review"), 0)
        sp = v_count.get((exam, "split"), 0)
        other = sum(1 for r in results if r["exam"] == exam and r.get("verdict") not in ("ok", "review", "split"))
        md.append(f"| {exam} | {ok} | {rv} | {sp} | {other} |")
    md.append("")
    md.append("## 분리 권장(split) 또는 검토(review) 케이스")
    md.append("")
    for r in results:
        if r.get("verdict") in ("review", "split") or r.get("outliers"):
            md.append(f"### `{r['id']}` ({r['exam']}, {r['size']} members) — {r.get('verdict')}, coherence={r.get('coherence')}")
            md.append(f"- name: {r['name_ko']}")
            if r.get("outliers"):
                md.append(f"- outliers: {r['outliers']}")
            if r.get("subgroups"):
                md.append("- 분리안:")
                for s in r["subgroups"]:
                    md.append(f"  - {s}")
            md.append("")
    (OUT / "concepts_review.md").write_text("\n".join(md), "utf-8")
    print(f"\n→ {OUT/'concepts_review.md'}")


if __name__ == "__main__":
    main()

"""두 git revision 의 data/*.json 파일을 question number 단위로 union 머지.

GLM 머신(theirs)이 추가한 concepts/explanation_audit/explanation_detailed 와
로컬(ours)이 추가한 vision_image_summary/vision_reprocessed_at/concepts_pre_vision/
explanation_detailed_pre_vision/needs_vision_reprocess 모두 보존한다.

규칙 (per question, per field):
- vision_* / *_pre_vision / needs_vision_reprocess: ours 우선 (theirs 무시) — 내 vision 작업 보존
- concepts: 어느 쪽에든 있으면 채택. 둘 다 있으면 ours (vision 으로 갱신된 결과) 우선.
- explanation_detailed: ours 가 vision_reprocessed_at 가지면 ours 우선 (vision 보완본). 아니면 theirs 우선.
- explanation_audit: 둘 다 있으면 ours 우선 (vision 으로 갱신된 audit).
- 그 외 모든 필드: theirs 우선 (GLM 최신값).
- 한쪽에만 있는 필드: 그 값 채택.

사용법:
  python3 scripts/merge_json_data.py <base_ref> <ours_ref> <theirs_ref>
    또는 인자 생략 시 자동 결정 (base=merge-base, ours=HEAD, theirs=MERGE_HEAD)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

# vision 작업의 핵심 필드 — ours 우선
VISION_FIELDS = {
    "vision_image_summary",
    "vision_reprocessed_at",
    "concepts_pre_vision",
    "explanation_detailed_pre_vision",
}


def git_show(ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "show", f"{ref}:{path}"],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        return None
    return r.stdout


def load_json(text: str | None) -> dict | None:
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def merge_question(q_ours: dict, q_theirs: dict) -> dict:
    """단일 question dict 머지. ours 가 vision 결과를 가지면 ours 우선 분기.

    Returns: 머지된 새 dict (입력 안 건드림).
    """
    out = dict(q_theirs)  # default base = theirs (최신 GLM)

    # ours-only 필드: vision_*, needs_vision_reprocess
    for k in VISION_FIELDS:
        if k in q_ours:
            out[k] = q_ours[k]

    # needs_vision_reprocess: ours 가 False 면 (vision 처리 완료) ours 우선.
    # ours 에만 있고 theirs 에 없으면 ours 채택.
    if "needs_vision_reprocess" in q_ours:
        out["needs_vision_reprocess"] = q_ours["needs_vision_reprocess"]

    # concepts: ours 가 vision 처리됐으면 (vision_reprocessed_at) ours 우선
    ours_visioned = bool(q_ours.get("vision_reprocessed_at"))
    if "concepts" in q_ours and "concepts" in q_theirs:
        if ours_visioned:
            out["concepts"] = q_ours["concepts"]
        # else: theirs (이미 default)
    elif "concepts" in q_ours:
        out["concepts"] = q_ours["concepts"]
    # elif "concepts" in q_theirs: already in out

    # explanation_detailed: ours 가 vision 으로 갱신된 경우 ours 우선
    if "explanation_detailed" in q_ours and ours_visioned:
        out["explanation_detailed"] = q_ours["explanation_detailed"]
    elif "explanation_detailed" in q_ours and "explanation_detailed" not in q_theirs:
        out["explanation_detailed"] = q_ours["explanation_detailed"]

    # explanation_audit: vision 처리됐으면 ours 우선
    if "explanation_audit" in q_ours and ours_visioned:
        out["explanation_audit"] = q_ours["explanation_audit"]
    elif "explanation_audit" in q_ours and "explanation_audit" not in q_theirs:
        out["explanation_audit"] = q_ours["explanation_audit"]

    return out


def merge_session(d_ours: dict, d_theirs: dict) -> tuple[dict, dict]:
    """세션 JSON 머지. 각 question 을 number 키로 매칭하여 union.

    Returns: (merged_dict, stats)
    """
    # 헤더 필드 union (theirs 우선, ours-only 채움)
    out = dict(d_theirs)
    for k, v in d_ours.items():
        if k == "questions":
            continue
        if k not in out:
            out[k] = v

    qs_ours = {q.get("number"): q for q in (d_ours.get("questions") or [])}
    qs_theirs = {q.get("number"): q for q in (d_theirs.get("questions") or [])}

    all_nums = sorted(set(qs_ours) | set(qs_theirs),
                       key=lambda x: (x is None, x))

    merged_questions = []
    stats = {"both": 0, "ours_only": 0, "theirs_only": 0, "vision_preserved": 0}
    for n in all_nums:
        qo = qs_ours.get(n)
        qt = qs_theirs.get(n)
        if qo and qt:
            m = merge_question(qo, qt)
            merged_questions.append(m)
            stats["both"] += 1
            if qo.get("vision_reprocessed_at"):
                stats["vision_preserved"] += 1
        elif qo:
            merged_questions.append(qo)
            stats["ours_only"] += 1
        else:
            merged_questions.append(qt)
            stats["theirs_only"] += 1

    out["questions"] = merged_questions
    # count 필드가 questions 길이와 다르면 갱신
    out["count"] = len(merged_questions)
    return out, stats


def changed_files(base: str, ref: str) -> set[str]:
    r = subprocess.run(["git", "diff", "--name-only", f"{base}..{ref}", "--", "data/"],
                       capture_output=True, text=True, cwd=ROOT)
    return {p for p in r.stdout.split() if p.endswith(".json")}


def main():
    args = sys.argv[1:]
    if len(args) == 3:
        base, ours, theirs = args
    elif len(args) == 0:
        # auto: base = merge-base(HEAD, origin/main), ours = HEAD, theirs = origin/main
        r = subprocess.run(["git", "merge-base", "HEAD", "origin/main"],
                           capture_output=True, text=True, cwd=ROOT)
        base = r.stdout.strip()
        ours = "HEAD"
        theirs = "origin/main"
    else:
        print(__doc__)
        sys.exit(1)

    print(f"base={base[:8]}  ours={ours}  theirs={theirs}")
    f_ours = changed_files(base, ours)
    f_theirs = changed_files(base, theirs)
    overlap = sorted(f_ours & f_theirs)
    ours_only = sorted(f_ours - f_theirs)
    theirs_only = sorted(f_theirs - f_ours)
    print(f"overlap={len(overlap)}  ours_only={len(ours_only)}  theirs_only={len(theirs_only)}")

    grand = {"both": 0, "ours_only": 0, "theirs_only": 0,
             "vision_preserved": 0, "files_written": 0}

    # 1) overlap: ours+theirs 머지 → working tree 에 기록
    for path in overlap:
        text_ours = git_show(ours, path)
        text_theirs = git_show(theirs, path)
        d_ours = load_json(text_ours)
        d_theirs = load_json(text_theirs)
        if d_ours is None or d_theirs is None:
            print(f"  WARN {path}: parse fail (ours={d_ours is None} theirs={d_theirs is None})")
            continue
        merged, s = merge_session(d_ours, d_theirs)
        (ROOT / path).write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        grand["both"] += s["both"]
        grand["ours_only"] += s["ours_only"]
        grand["theirs_only"] += s["theirs_only"]
        grand["vision_preserved"] += s["vision_preserved"]
        grand["files_written"] += 1

    # 2) ours_only: 로컬 그대로 (working tree 이미 보유 — skip)
    # 3) theirs_only: theirs 버전을 working tree 에 기록 (현재 로컬에는 없음)
    for path in theirs_only:
        text = git_show(theirs, path)
        if text is None:
            print(f"  WARN {path}: theirs show fail")
            continue
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        grand["files_written"] += 1

    print(f"\n=== merged ===")
    print(f"questions in both: {grand['both']}  ours_only: {grand['ours_only']}  theirs_only: {grand['theirs_only']}")
    print(f"vision_preserved (in overlap): {grand['vision_preserved']}")
    print(f"files written: {grand['files_written']}")


if __name__ == "__main__":
    main()

"""iz_refetch_candidates.json 의 qid 들을 원본에서 다시 가져와 현재 데이터와 비교한다.

fetch.py 의 DEFAULT_BASE (comcbt.com) 를 사용. FETCH_BASE_URL 로 override 가능.

흐름:
  1. data/audit/iz_refetch_candidates.json 읽기 (또는 --qid 인자로 단건 지정)
  2. 각 qid 에 대해 fetch.parse_question 으로 원본 페이지 가져와 신규 dict 생성
  3. 현재 data/iz/iz_<date>.json 의 해당 문항과 필드 비교
       - question / choices.text / answer / question_images / choices.images
  4. 변경 사항 요약 + 정정 패치(JSON) 생성

산출:
  data/audit/iz_refetch_diff.json   변경 요약
  data/audit/iz_refetch_diff.md     사람-가독 요약
  data/audit/iz_refetch_patch.json  적용용 패치 (qid → 변경 필드)

다음 단계에서 audit_iz_apply_refetch.py 로 patch 를 실제 JSON 에 적용.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch import _fetch_one, parse_question  # noqa: E402

DATA = ROOT / "data"
IZ = DATA / "iz"
OUT = DATA / "audit"
CAND = OUT / "iz_refetch_candidates.json"


def split_qid(qid: str) -> tuple[str, int]:
    file_stem, num = qid.split("#")
    date = file_stem.split("_")[-1]
    return date, int(num)


def load_current() -> dict[str, tuple[Path, dict, dict]]:
    """qid → (file, full_data, question_dict)"""
    by_qid = {}
    for f in sorted(IZ.glob("iz_*.json")):
        if f.name == "sessions.json":
            continue
        data = json.loads(f.read_text("utf-8"))
        for q in data["questions"]:
            qid = f"{f.stem}#{q['number']}"
            by_qid[qid] = (f, data, q)
    return by_qid


def field_diff(old: dict, new: dict) -> dict:
    diff = {}
    for key in ("question", "answer", "pass_rate"):
        if old.get(key) != new.get(key):
            diff[key] = {"old": old.get(key), "new": new.get(key)}
    old_choices = old.get("choices") or []
    new_choices = new.get("choices") or []
    if len(old_choices) != len(new_choices):
        diff["n_choices"] = {"old": len(old_choices), "new": len(new_choices)}
    chs = []
    for i in range(max(len(old_choices), len(new_choices))):
        oc = old_choices[i] if i < len(old_choices) else {}
        nc = new_choices[i] if i < len(new_choices) else {}
        if (oc.get("text") or "").strip() != (nc.get("text") or "").strip():
            chs.append({
                "i": i + 1,
                "old_text": oc.get("text"), "new_text": nc.get("text"),
            })
        elif (oc.get("images") or []) != (nc.get("images") or []):
            chs.append({
                "i": i + 1,
                "old_imgs": oc.get("images"), "new_imgs": nc.get("images"),
            })
    if chs:
        diff["choices"] = chs
    if (old.get("question_images") or []) != (new.get("question_images") or []):
        diff["question_images"] = {
            "old": old.get("question_images"), "new": new.get("question_images"),
        }
    return diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qid", action="append", default=[],
                    help="단건 검증 (반복 가능). 미지정 시 후보 파일 사용")
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    # fetch.py 의 DEFAULT_BASE 사용 — override 필요 시 FETCH_BASE_URL 환경변수

    qids = args.qid or json.loads(CAND.read_text("utf-8"))
    if args.limit:
        qids = qids[: args.limit]

    current = load_current()
    diffs = []
    patches = {}

    for i, qid in enumerate(qids, 1):
        if qid not in current:
            print(f"[{i}/{len(qids)}] {qid} not found — skip", flush=True)
            continue
        _f, _data, q_old = current[qid]
        date, num = split_qid(qid)
        print(f"[{i}/{len(qids)}] fetching {qid} ...", flush=True)
        try:
            html = _fetch_one("iz", date, num)
            q_new = parse_question(html, num)
        except Exception as e:
            print(f"  ERROR: {e}")
            diffs.append({"qid": qid, "error": str(e)[:200]})
            time.sleep(args.delay)
            continue
        if q_new is None:
            diffs.append({"qid": qid, "error": "parse returned None"})
            print("  parse returned None")
            time.sleep(args.delay)
            continue
        d = field_diff(q_old, q_new)
        if d:
            diffs.append({"qid": qid, "diff": d})
            patches[qid] = {
                "question": q_new.get("question"),
                "answer": q_new.get("answer"),
                "choices": q_new.get("choices"),
                "question_images": q_new.get("question_images"),
                "pass_rate": q_new.get("pass_rate"),
            }
            print(f"  diff fields: {list(d.keys())}")
        else:
            diffs.append({"qid": qid, "diff": None})
            print("  no diff")
        time.sleep(args.delay)

    (OUT / "iz_refetch_diff.json").write_text(
        json.dumps(diffs, ensure_ascii=False, indent=2), "utf-8")
    (OUT / "iz_refetch_patch.json").write_text(
        json.dumps(patches, ensure_ascii=False, indent=2), "utf-8")

    md = ["# iz re-fetch 비교 결과", ""]
    md.append(f"검사 {len(qids)}건 / 차이 발견 {sum(1 for d in diffs if d.get('diff'))}건")
    md.append("")
    for d in diffs:
        if d.get("error"):
            md.append(f"### `{d['qid']}` — ERROR {d['error']}")
            continue
        if not d.get("diff"):
            continue
        md.append(f"### `{d['qid']}`")
        for k, v in d["diff"].items():
            md.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False)[:300]}")
        md.append("")
    (OUT / "iz_refetch_diff.md").write_text("\n".join(md), "utf-8")
    print(f"→ {OUT/'iz_refetch_diff.md'}")
    print(f"→ patches for {len(patches)} qids")


if __name__ == "__main__":
    main()

"""iz 전체 800문항 B1 스타일 독립 재검수.

문제 본문 + 선택지만 보고 정답을 독립적으로 판단한다.
기존 answer / explanation_detailed / concepts 등 AI 산출물은 노출하지 않는다.

결과:
  data/audit/iz_full_revalidate.json   누적 (idempotent)
  data/audit/iz_full_revalidate.md     mismatch + 결함 후보 요약

병렬: claude CLI 동시성 낮음 → workers 기본 3.
사용:
  python3 scripts/audit_iz_full_revalidate.py            # 전체 실행
  python3 scripts/audit_iz_full_revalidate.py --workers 4
  python3 scripts/audit_iz_full_revalidate.py --limit 20 # 스모크 테스트
  python3 scripts/audit_iz_full_revalidate.py --report   # 결과 파일에서 MD만 재생성

known_defect 가 이미 마킹된 문항은 스킵.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IZ = DATA / "iz"
OUT = DATA / "audit"
RESULT_JSON = OUT / "iz_full_revalidate.json"
RESULT_MD = OUT / "iz_full_revalidate.md"

EXAM_NAME = "정보처리기사"

PROMPT_TMPL = """너는 한국 자격증 시험({exam_name}) 채점관이다. 아래 문항의 학술적 정답을 독립적으로 판단하라.

**중요:**
- 기존 해설, 정답 키, 출처를 참고하지 말고 오직 문제 본문과 선택지만 근거로 판단할 것.
- 문제 자체에 오류·결함(텍스트 깨짐, 선택지 모순, 이미지/표 누락 등)이 있으면 defect=true 로 표시.
- 답을 단일 번호로 정할 수 없으면 ambiguous=true 로 표시하고 reason 에 사유 기재.

[과목] {subject}
[문제] {question}
[선택지]
{choices}

다음 JSON 한 덩어리만 출력하라(부가 설명 금지):
{{
  "answer": 1-{n_choices} 사이 정수,
  "confidence": 0.0~1.0,
  "ambiguous": true|false,
  "defect": true|false,
  "reason": "120자 이내 한국어 핵심 근거"
}}
"""


def call_claude(prompt: str, *, timeout: int = 180) -> str:
    r = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()[:200]}")
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("claude returned empty output")
    return out


def parse_json(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def build_prompt(q: dict) -> str:
    choices = "\n".join(
        f"  ({i+1}) {c.get('text','')}" for i, c in enumerate(q.get("choices", []))
    )
    return PROMPT_TMPL.format(
        exam_name=EXAM_NAME,
        subject=q.get("subject") or "",
        question=q.get("question") or "",
        choices=choices,
        n_choices=len(q.get("choices", [])) or 4,
    )


def collect_questions() -> list[dict]:
    items = []
    for f in sorted(IZ.glob("iz_*.json")):
        if f.name == "sessions.json":
            continue
        data = json.loads(f.read_text("utf-8"))
        date = data.get("date") or f.stem.split("_")[-1]
        for q in data["questions"]:
            items.append({
                "qid": f"{f.stem}#{q['number']}",
                "file": f.name,
                "date": date,
                "number": q["number"],
                "subject": q.get("subject"),
                "question": q.get("question"),
                "choices": q.get("choices", []),
                "answer_key": q.get("answer"),
                "known_defect": q.get("known_defect"),
            })
    return items


def load_existing() -> dict:
    if RESULT_JSON.exists():
        rows = json.loads(RESULT_JSON.read_text("utf-8"))
        return {r["qid"]: r for r in rows}
    return {}


_save_lock = threading.Lock()


def atomic_save(results_map: dict) -> None:
    with _save_lock:
        rows = sorted(results_map.values(), key=lambda r: (r["file"], r["number"]))
        tmp = RESULT_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(RESULT_JSON)


def revalidate_one(item: dict) -> dict:
    prompt = build_prompt(item)
    t0 = time.time()
    try:
        raw = call_claude(prompt)
    except Exception as e:
        return {**item, "error": str(e)[:200], "elapsed": round(time.time()-t0, 1)}
    parsed = parse_json(raw)
    if not parsed:
        return {**item, "raw": raw[:300], "error": "JSON parse failed",
                "elapsed": round(time.time()-t0, 1)}
    return {
        **item,
        "revalid_answer": parsed.get("answer"),
        "confidence": parsed.get("confidence"),
        "ambiguous": bool(parsed.get("ambiguous")),
        "defect": bool(parsed.get("defect")),
        "reason": parsed.get("reason"),
        "elapsed": round(time.time()-t0, 1),
    }


def categorize(r: dict) -> str:
    if r.get("error"):
        return "error"
    if r.get("defect"):
        return "defect_flagged"
    if r.get("ambiguous"):
        return "ambiguous"
    rev = r.get("revalid_answer")
    key = r.get("answer_key")
    if rev is None or key is None:
        return "unknown"
    if rev == key:
        return "match"
    return "mismatch"


def write_report(results_map: dict) -> None:
    rows = sorted(results_map.values(), key=lambda r: (r["file"], r["number"]))
    cat = {}
    for r in rows:
        c = categorize(r)
        cat.setdefault(c, []).append(r)

    md = ["# iz 전체 B1 재검수 결과", "",
          f"총 {len(rows)}건 (정보처리기사 800문항 중)", ""]
    md.append("## 카테고리 분포")
    md.append("")
    md.append("| 카테고리 | 건수 |")
    md.append("|---------|------|")
    for k in ["match", "mismatch", "defect_flagged", "ambiguous", "error", "unknown"]:
        md.append(f"| {k} | {len(cat.get(k, []))} |")
    md.append("")

    for k in ["mismatch", "defect_flagged", "ambiguous", "error"]:
        items = cat.get(k, [])
        if not items:
            continue
        md.append(f"## {k} ({len(items)}건)")
        md.append("")
        md.append("| qid | 과목 | answer 키 | 재검 | conf | reason |")
        md.append("|-----|------|-----------|------|------|--------|")
        for r in items:
            md.append(
                f"| `{r['qid']}` | {(r.get('subject') or '')[:18]} | "
                f"{r.get('answer_key')} | {r.get('revalid_answer','-')} | "
                f"{r.get('confidence','-')} | {(r.get('reason') or r.get('error') or '')[:80]} |"
            )
        md.append("")

    RESULT_MD.write_text("\n".join(md), "utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="0=전체, N=처음 N건만")
    ap.add_argument("--report", action="store_true",
                    help="실행 없이 기존 결과로 MD만 재생성")
    ap.add_argument("--retry-errors", action="store_true",
                    help="error 마킹된 항목 재시도")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    existing = load_existing()

    if args.report:
        write_report(existing)
        print(f"report → {RESULT_MD}")
        return

    all_items = collect_questions()
    todo = []
    for it in all_items:
        if it["known_defect"]:
            continue
        prev = existing.get(it["qid"])
        if prev and not args.retry_errors:
            continue
        if prev and args.retry_errors and not prev.get("error"):
            continue
        todo.append(it)

    if args.limit:
        todo = todo[: args.limit]

    print(f"[plan] total={len(all_items)} cached={len(existing)} "
          f"todo={len(todo)} workers={args.workers}", flush=True)
    if not todo:
        write_report(existing)
        print(f"report → {RESULT_MD}")
        return

    done = 0
    started = time.time()
    SAVE_EVERY = 10
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(revalidate_one, it): it for it in todo}
        for fut in as_completed(futures):
            it = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {**it, "error": f"future: {e}"[:200]}
            existing[res["qid"]] = res
            done += 1
            cat = categorize(res)
            print(f"[{done}/{len(todo)}] {res['qid']} key={res.get('answer_key')} "
                  f"rev={res.get('revalid_answer','-')} → {cat} "
                  f"({res.get('elapsed','-')}s)", flush=True)
            if done % SAVE_EVERY == 0:
                atomic_save(existing)
                write_report(existing)

    atomic_save(existing)
    write_report(existing)
    elapsed = time.time() - started
    print(f"\n[done] {done} processed in {elapsed/60:.1f}min → {RESULT_MD}")


if __name__ == "__main__":
    main()

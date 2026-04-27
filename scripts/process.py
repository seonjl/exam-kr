"""통합 처리 스크립트: 이미지 OCR + 상세 해설을 한 번의 Claude CLI 호출로.

문항별 상태에 따라 최적 프롬프트 분기:
- 둘 다 필요 → 통합 프롬프트 (이미지 Read + 구조화 해설을 한 응답으로)
- OCR만 필요 → extract 프롬프트
- 해설만 필요 → enrich 프롬프트
- 둘 다 완료 → 스킵

이미지 결과는 data/.image_cache.json 에, 해설은 JSON 내 explanation_detailed 필드에 저장.
캐시 적용(image_cache → extras 필드 마이그레이션)은 완료 후 --apply 로 실행.

사용법:
  python3 process.py <examCode>                    # 자격증 전체
  python3 process.py <examCode> <YYYYMMDD>         # 단일 회차
  python3 process.py all-exams                     # 모든 자격증
  python3 process.py --apply                       # 캐시→JSON 반영
  python3 process.py --stats                       # 진척 통계
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from exams import EXAMS  # noqa: E402
from extract_images import (  # noqa: E402
    url_key, load_cache, save_cache, detect_kind, apply_cache,
    collect_urls, UA,
)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

# --------- prompts ---------

OCR_RULES = """규칙:
- 수식 → $$LaTeX$$ (KaTeX 호환)
- 표 → 마크다운 table
- 흐름도·트리·관계 다이어그램 → ```mermaid 블록 (flowchart TD, graph LR 등)
- 단순 한국어·기호·변수 리스트 → 그대로 평문
- 혼합이면 자연스러운 순서로 조합"""

EXPL_RULES = """구조:
핵심 개념
- 이 문제가 묻는 개념을 1~2줄로 요약

정답 분석
- 정답이 왜 옳은지 구체적으로 (2~4줄)

오답 분석
- ① / ② / ③ / ④ 각 보기 설명 (1줄씩)

다른 말은 붙이지 말고 위 세 섹션만 평문(마크다운 기호 없이)으로."""


def image_slots(q: dict) -> list[tuple[str, str]]:
    """(label, url) pairs for every image this question references."""
    out: list[tuple[str, str]] = []
    for u in (q.get("question_images") or []):
        out.append(("Q", u))
    for i, c in enumerate(q.get("choices") or []):
        for u in (c.get("images") or []):
            out.append((f"C{i+1}", u))
    for u in (q.get("explanation_images") or []):
        out.append(("E", u))
    return out


def need_ocr(q: dict, cache: dict) -> bool:
    slots = image_slots(q)
    if not slots:
        return False
    return any(url_key(u) not in cache for _, u in slots)


def need_enrich(q: dict) -> bool:
    return not q.get("explanation_detailed")


def build_combined_prompt(q: dict, exam_name: str,
                          slot_files: list[tuple[str, str, str]]) -> str:
    """slot_files = [(label, url, filename_in_cwd), ...]"""
    img_lines = "\n".join(f"{lbl}: {fn}" for lbl, _, fn in slot_files)
    choice_lines = "\n".join(
        f"{'①②③④'[i]} {(c.get('text') or '').strip() or '[이미지 참조]'}"
        for i, c in enumerate(q.get("choices") or []))
    return f"""당신은 {exam_name} 전문 강사입니다.
아래 기출문제에 대해 두 작업을 한 번에 수행하세요.

[문항 자료 이미지들 — 이 디렉터리의 파일을 Read 도구로 열어 확인]
{img_lines}

[문제] {q.get('question') or ''}
[보기]
{choice_lines}
[정답] {q.get('answer', '?')}번
[기존 해설] {(q.get('explanation') or '없음').strip() or '없음'}

=== 작업 1: 각 이미지의 내용을 구조화 마크다운으로 변환 ===
{OCR_RULES}

각 라벨(Q/C1~C4/E) 아래에 그 이미지의 변환 결과만 적으세요.

=== 작업 2: 해설을 학습용으로 재작성 ===
{EXPL_RULES}

위 이미지 내용을 해설에 자연스럽게 반영해도 좋습니다.

=== 출력 형식 (반드시 준수) ===

---EXTRAS-BEGIN---
Q:
(Q 라벨 이미지의 변환 결과. 없으면 이 블록 생략)

C1:
(C1 라벨 이미지의 변환 결과. 없으면 생략)

...
---EXTRAS-END---

---EXPLANATION-BEGIN---
핵심 개념
...

정답 분석
...

오답 분석
① ...
② ...
③ ...
④ ...
---EXPLANATION-END---
"""


def build_ocr_prompt(slot_files: list[tuple[str, str, str]]) -> str:
    img_lines = "\n".join(f"{lbl}: {fn}" for lbl, _, fn in slot_files)
    return f"""이 디렉터리의 이미지 파일들을 각각 Read 도구로 열어 구조화 마크다운으로 변환하세요.

[이미지 목록]
{img_lines}

{OCR_RULES}

출력 형식:

---EXTRAS-BEGIN---
Q:
(Q 이미지 변환 결과)

C1:
(C1 이미지 변환 결과)

...
---EXTRAS-END---

다른 말은 붙이지 마세요.
"""


def build_enrich_prompt(q: dict, exam_name: str) -> str:
    choices = q.get("choices") or []
    ct = lambda i: (choices[i].get("text") if i < len(choices) else "") or "[이미지]"
    return f"""당신은 {exam_name} 전문 강사입니다.
아래 기출문제의 해설을 학습용으로 다시 작성해주세요.

[과목] {q.get('subject') or ''}
[문제] {q.get('question') or ''}
[보기]
① {ct(0)}
② {ct(1)}
③ {ct(2)}
④ {ct(3)}
[정답] {q.get('answer', '?')}번
[기존 해설] {(q.get('explanation') or '없음').strip() or '없음'}

{EXPL_RULES}
"""


# --------- parser ---------

def parse_extras_block(text: str) -> dict[str, str]:
    """Returns {'Q': '...', 'C1': '...', ...}"""
    m = re.search(r"---EXTRAS-BEGIN---\s*(.*?)\s*---EXTRAS-END---", text, re.S)
    if not m:
        return {}
    body = m.group(1)
    out: dict[str, str] = {}
    # Match "LABEL:\n<content until next LABEL: or end>"
    for mm in re.finditer(r"^(Q|C[1-4]|E):\s*\n(.*?)(?=^\s*(?:Q|C[1-4]|E):\s*\n|\Z)",
                          body, re.M | re.S):
        label = mm.group(1)
        content = mm.group(2).strip()
        if content:
            out[label] = content
    return out


def parse_explanation_block(text: str) -> str:
    m = re.search(r"---EXPLANATION-BEGIN---\s*(.*?)\s*---EXPLANATION-END---", text, re.S)
    if m:
        return m.group(1).strip()
    # Fallback: if no markers, the whole output is the explanation
    return text.strip()


# --------- claude call ---------

def download_slot_files(slots: list[tuple[str, str]], tmpdir: Path) -> list[tuple[str, str, str]]:
    out = []
    for lbl, url in slots:
        ext = url.rsplit("?", 1)[0].rsplit(".", 1)[-1] or "gif"
        fn = f"{lbl}.{ext}"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            (tmpdir / fn).write_bytes(r.read())
        out.append((lbl, url, fn))
    return out


def call_claude(prompt: str, cwd: str | None = None, timeout: int = 180) -> str:
    r = subprocess.run(["claude", "-p", prompt],
                       capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("empty output")
    return out


# --------- per-question processor ---------

class Breaker:
    def __init__(self, threshold: int = 20):
        self.threshold = threshold
        self._f = 0
        self._lock = threading.Lock()
        self.tripped = False

    def ok(self):
        with self._lock: self._f = 0

    def bad(self):
        with self._lock:
            self._f += 1
            if self._f >= self.threshold: self.tripped = True


def process_question(q: dict, exam_code: str, cache: dict) -> dict:
    """Returns dict with 'ocr' (bool, image cache updated), 'enrich' (bool)."""
    did = {"ocr": 0, "enrich": 0}
    slots = image_slots(q)
    missing_slots = [(l, u) for (l, u) in slots if url_key(u) not in cache]
    do_ocr = bool(missing_slots)
    do_enrich = need_enrich(q)
    if not do_ocr and not do_enrich:
        return did

    exam_name = EXAMS.get(exam_code, {}).get("name", "")

    with tempfile.TemporaryDirectory(prefix="proc_") as td:
        tmpdir = Path(td)

        if do_ocr and do_enrich:
            slot_files = download_slot_files(missing_slots, tmpdir)
            prompt = build_combined_prompt(q, exam_name, slot_files)
            out = call_claude(prompt, cwd=td)
            extras_by_label = parse_extras_block(out)
            explanation = parse_explanation_block(out)

            for (lbl, url, _fn) in slot_files:
                content = extras_by_label.get(lbl)
                if content:
                    cache[url_key(url)] = {
                        "kind": detect_kind(content),
                        "content": content,
                        "ts": int(time.time()),
                    }
                    did["ocr"] += 1
            if explanation:
                q["explanation_detailed"] = explanation
                did["enrich"] = 1

        elif do_ocr:
            slot_files = download_slot_files(missing_slots, tmpdir)
            prompt = build_ocr_prompt(slot_files)
            out = call_claude(prompt, cwd=td)
            extras_by_label = parse_extras_block(out)
            for (lbl, url, _fn) in slot_files:
                content = extras_by_label.get(lbl)
                if content:
                    cache[url_key(url)] = {
                        "kind": detect_kind(content),
                        "content": content,
                        "ts": int(time.time()),
                    }
                    did["ocr"] += 1

        else:  # enrich only
            prompt = build_enrich_prompt(q, exam_name)
            out = call_claude(prompt, cwd=td)
            q["explanation_detailed"] = parse_explanation_block(out)
            did["enrich"] = 1

    return did


# --------- session / exam drivers ---------

def process_session(exam_code: str, session_code: str, *,
                    workers: int = 1, breaker: Breaker | None = None,
                    cache: dict | None = None) -> dict:
    path = DATA / exam_code / f"{exam_code}_{session_code}.json"
    if not path.exists():
        print(f"[{exam_code}/{session_code}] missing"); return {"skip": 1}
    d = json.loads(path.read_text(encoding="utf-8"))
    cache = cache if cache is not None else load_cache()
    breaker = breaker or Breaker()

    # What's todo?
    todo = []
    for q in d["questions"]:
        if need_ocr(q, cache) or need_enrich(q):
            todo.append(q)
    print(f"[{exam_code}/{session_code}] 대상 {len(todo)} / 총 {len(d['questions'])}", flush=True)
    if not todo:
        return {"ocr": 0, "enrich": 0, "skip": len(d["questions"])}

    done_ocr = done_enrich = failed = 0
    lock = threading.Lock()

    def worker(q):
        nonlocal done_ocr, done_enrich, failed
        if breaker.tripped: return
        try:
            r = process_question(q, exam_code, cache)
            breaker.ok()
            with lock:
                done_ocr += r["ocr"]
                done_enrich += r["enrich"]
            print(f"  Q{q['number']}  ✓  ocr+{r['ocr']} enrich+{r['enrich']}", flush=True)
        except Exception as e:
            breaker.bad()
            with lock:
                failed += 1
            print(f"  Q{q['number']}  ✗  {e}", flush=True)

    def save():
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        save_cache(cache)

    if workers <= 1:
        for i, q in enumerate(todo, 1):
            if breaker.tripped: break
            worker(q)
            if i % 5 == 0: save()
    else:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(worker, q) for q in todo]
            for i, _ in enumerate(cf.as_completed(futs), 1):
                if i % 5 == 0: save()
                if breaker.tripped:
                    for f in futs: f.cancel()
                    print("  [breaker tripped]", flush=True)
                    break

    save()
    return {
        "ocr": done_ocr, "enrich": done_enrich, "failed": failed,
        "tripped": breaker.tripped, "total": len(d["questions"]),
    }


def all_sessions(exam_code: str) -> list[str]:
    mani = DATA / exam_code / "sessions.json"
    if mani.exists():
        j = json.loads(mani.read_text(encoding="utf-8"))
        return [s["code"] for s in j["sessions"]]
    return sorted(p.name[len(exam_code)+1:-5] for p in (DATA / exam_code).glob(f"{exam_code}_*.json"))


def process_exam(exam_code: str, *, session_codes: list[str] | None = None,
                 workers: int = 1) -> dict:
    if exam_code not in EXAMS:
        raise SystemExit(f"Unknown exam code: {exam_code}")
    codes = session_codes or all_sessions(exam_code)
    cache = load_cache()
    breaker = Breaker(threshold=200)
    t0 = time.time()
    total = {"ocr": 0, "enrich": 0, "failed": 0, "sessions": 0, "tripped": False}
    for c in codes:
        r = process_session(exam_code, c, workers=workers, breaker=breaker, cache=cache)
        for k in ("ocr", "enrich", "failed"):
            total[k] += r.get(k, 0)
        total["sessions"] += 1
        if r.get("tripped"):
            total["tripped"] = True
            break
    print(f"[{exam_code}] ocr+{total['ocr']} enrich+{total['enrich']} "
          f"failed+{total['failed']} · {total['sessions']}회차 · "
          f"{(time.time()-t0)/60:.1f}분", flush=True)
    return total


# --------- stats ---------

def show_stats() -> None:
    cache = load_cache()
    urls = set(url_key(u) for u in collect_urls())
    ocr_done = sum(1 for u in urls if u in cache)
    # per exam enrich
    rows = []
    for code in EXAMS:
        ex_dir = DATA / code
        if not ex_dir.exists(): continue
        n = 0; done = 0
        for p in sorted(ex_dir.glob(f"{code}_*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            n += d["count"]
            done += sum(1 for q in d["questions"] if q.get("explanation_detailed"))
        rows.append((code, EXAMS[code]["name"], done, n))
    print(f"\n== OCR ==")
    print(f"  이미지 {len(urls)} · 캐시 {ocr_done} ({ocr_done*100/max(len(urls),1):.1f}%)")
    print(f"\n== 상세해설 ==")
    for code, name, done, n in rows:
        pct = done*100/max(n,1)
        print(f"  {code:3} {name:18} {done:5}/{n:5} ({pct:.1f}%)")


# --------- CLI ---------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exam_code", nargs="?", help="자격증 코드 또는 'all-exams'")
    ap.add_argument("session_code", nargs="?", help="회차 코드")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.stats:
        show_stats(); return
    if args.apply:
        r = apply_cache(load_cache())
        print(f"JSON 업데이트: 파일 {r['files_updated']} · 부분 스킵 {r['fields_skipped_partial']}")
        return
    if not args.exam_code:
        ap.print_help(); sys.exit(1)

    if args.exam_code == "all-exams":
        targets = list(EXAMS.keys())
    else:
        targets = [args.exam_code]

    grand = {"ocr": 0, "enrich": 0, "failed": 0}
    for code in targets:
        print(f"\n========== {code} · {EXAMS[code]['name']} ==========")
        sess = [args.session_code] if args.session_code else None
        r = process_exam(code, session_codes=sess, workers=args.workers)
        for k in grand: grand[k] += r.get(k, 0)
        if r.get("tripped"):
            print("중단 (breaker)"); break

    print(f"\n=== 총 ocr+{grand['ocr']} enrich+{grand['enrich']} failed+{grand['failed']} ===")


if __name__ == "__main__":
    main()

"""GLM 결과 결함 fix — audit/glm_defects.json 기반.

지원 카테고리 (--category):
  D10  concept=choice  — concepts 만 재추출 (explanation 안 건드림)
  D02  k1 5선지 explanation — ⑤번 포함하여 explanation_detailed 재생성
  D03  audit score 0/1 — explanation_detailed 재생성

방법: claude -p 서브프로세스, BATCH=5, workers=2, idempotent.
비파괴: `*_pre_fix_DXX` 키로 이전값 보존, `fix_DXX_at` 타임스탬프 기록.

사용법:
  python3 scripts/fix_glm_defects.py D10           # D10 전체 fix
  python3 scripts/fix_glm_defects.py D02 --limit 50   # 50문항만
  python3 scripts/fix_glm_defects.py D02 --workers 2
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from exams import EXAMS  # noqa: E402
from audit_glm_quality import scan_question  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
BATCH_SIZE = 5


# ── shared helpers ──────────────────────────────────────

def _q_block(q: dict) -> str:
    choices = q.get("choices") or []
    n = min(len(choices), len(_CIRCLED)) or 4

    def ct(i: int) -> str:
        c = choices[i] if i < len(choices) else {"text": ""}
        t = (c.get("text") or "").strip()
        if not t and (c.get("images") or []):
            t = "[이미지]"
        return t or "(비어있음)"

    existing = (q.get("explanation_detailed") or q.get("explanation") or "").strip()
    cl = "".join(f"{_CIRCLED[i]} {ct(i)}\n" for i in range(n))
    return (
        f"[Q{q.get('number')}]\n"
        f"[과목] {q.get('subject') or ''}\n"
        f"[문제] {q.get('question') or ''}\n"
        f"[보기]\n{cl}"
        f"[정답] {q.get('answer', '?')}번\n"
        f"[기존 해설]\n{existing or '(없음)'}\n"
    )


def call_claude(prompt: str, *, timeout: int = 300, retries: int = 3) -> str:
    last_err = ""
    for attempt in range(retries):
        if attempt:
            time.sleep(2 + 2 * attempt)
        r = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            last_err = f"rc={r.returncode} stderr={r.stderr.strip()[:200]}"
            continue
        out = r.stdout.strip()
        if not out:
            last_err = "empty output"
            continue
        return out
    raise RuntimeError(f"claude failed: {last_err}")


_JSON_RE = re.compile(r"\{[\s\S]*\}\s*$")


def parse_response(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    try:
        return json.loads(s)
    except Exception:
        pass
    m = _JSON_RE.search(s)
    if not m:
        raise ValueError(f"no JSON: {text[:200]!r}")
    return json.loads(m.group(0))


class Breaker:
    def __init__(self, n: int = 15):
        self.n = n
        self._f = 0
        self._lk = threading.Lock()
        self.tripped = False

    def ok(self):
        with self._lk:
            self._f = 0

    def bad(self):
        with self._lk:
            self._f += 1
            if self._f >= self.n:
                self.tripped = True


# ── prompts per category ────────────────────────────────

PROMPT_D10 = """당신은 {name} 전문 강사입니다. 아래 {nq}개 기출문제의 핵심 개념을 재추출합니다.

────────────────────────
{blocks}
────────────────────────

각 문제마다 다음 작업을 수행:

핵심 개념을 1~3개 한국어 명사구로 뽑으세요.
- 보기 텍스트를 그대로 복사하지 마세요. 정답의 의미를 추상화한 개념을 적으세요.
- 추상적 분야명("정보", "통계") 금지. 구체 개념("표본분산의 자유도") 권장.
- 가장 중심적인 개념을 첫 번째로.

출력은 다른 텍스트/코드펜스 없이 JSON 한 개:

{{"results": [
  {{"qnum": {qnums0}, "concepts": ["...", "..."]}},
  ...
]}}

규칙:
- results 길이 정확히 {nq}, qnum 은 {qnums} 와 1:1.
- JSON 외 텍스트 금지.
"""


PROMPT_D02 = """당신은 {name} 전문 강사입니다. 아래 {nq}개 5지선다 기출문제의 해설을 재작성합니다.

기존 해설이 ⑤번 보기를 다루지 않은 경우 ⑤까지 포함하여 모든 보기를 분석해야 합니다.

────────────────────────
{blocks}
────────────────────────

각 문제마다 다음 형식으로 평문(마크다운 기호 없이) 해설을 작성하세요:

핵심 개념
- 1~2줄로 이 문제가 묻는 개념 요약

정답 분석
- 정답이 왜 옳은지 구체적으로 (2~4줄)

오답 분석
- ① / ② / ③ / ④ / ⑤ 각 보기마다 정답/오답 여부 + 오답이면 왜 틀렸는지 1줄씩.
- 5개 모두 빠짐없이 한 줄씩 작성. 정답 보기에도 "정답" 으로 한 줄 표기.

섹션 제목은 위와 정확히 동일.

출력은 다른 텍스트/코드펜스 없이 JSON 한 개:

{{"results": [
  {{"qnum": {qnums0}, "improved_explanation": "..."}},
  ...
]}}

규칙:
- improved_explanation 안 줄바꿈은 \\n.
- results 길이 정확히 {nq}, qnum 은 {qnums} 와 1:1.
- JSON 외 텍스트 금지.
"""


PROMPT_D03 = """당신은 {name} 전문 강사입니다. 아래 {nq}개 기출문제의 해설을 보강합니다.

기존 해설이 부족하거나(score 0~1) 핵심 개념을 충분히 설명하지 못해 보강이 필요합니다.

────────────────────────
{blocks}
────────────────────────

각 문제마다 다음 형식으로 평문 해설을 작성:

핵심 개념
- 1~2줄

정답 분석
- 정답이 왜 옳은지 구체적으로 (2~4줄)

오답 분석
- 각 보기마다 (①, ②, ③, ...) 정답/오답 여부 + 오답이면 왜 틀렸는지 1줄씩 (보기 수가 5개면 ⑤까지 모두)

섹션 제목은 위와 정확히 동일.

출력은 JSON 한 개:

{{"results": [
  {{"qnum": {qnums0}, "improved_explanation": "..."}},
  ...
]}}

규칙:
- improved_explanation 안 줄바꿈은 \\n.
- results 길이 정확히 {nq}.
- JSON 외 텍스트 금지.
"""


CATEGORY_PROMPT = {"D10": PROMPT_D10, "D02": PROMPT_D02, "D03": PROMPT_D03}


def build_prompt(category: str, exam_code: str, qs: list[dict]) -> str:
    name = EXAMS.get(exam_code, {"name": ""}).get("name", "")
    blocks = "\n\n".join(_q_block(q) for q in qs)
    qnums = [q.get("number") for q in qs]
    tmpl = CATEGORY_PROMPT[category]
    return tmpl.format(name=name, nq=len(qs), blocks=blocks,
                         qnums=qnums, qnums0=qnums[0])


# ── apply per category ─────────────────────────────────

def apply_D10(q: dict, rec: dict) -> bool:
    concepts = rec.get("concepts") or []
    if not isinstance(concepts, list) or not concepts:
        return False
    concepts = [str(c).strip() for c in concepts if str(c).strip()][:3]
    if not concepts:
        return False
    if "concepts_pre_fix_D10" not in q:
        q["concepts_pre_fix_D10"] = q.get("concepts", [])
    q["concepts"] = concepts
    q["fix_D10_at"] = int(time.time())
    return True


def apply_expl(q: dict, rec: dict, tag: str) -> bool:
    """D02 / D03 공통: improved_explanation 적용."""
    new = rec.get("improved_explanation")
    if not new or not isinstance(new, str):
        return False
    new = new.strip()
    if len(new) < 50:
        return False
    pre_key = f"explanation_detailed_pre_fix_{tag}"
    if pre_key not in q:
        q[pre_key] = q.get("explanation_detailed", "")
    q["explanation_detailed"] = new
    q[f"fix_{tag}_at"] = int(time.time())
    return True


APPLIERS = {
    "D10": lambda q, r: apply_D10(q, r),
    "D02": lambda q, r: apply_expl(q, r, "D02"),
    "D03": lambda q, r: apply_expl(q, r, "D03"),
}


# ── scan + fix loop ────────────────────────────────────

def load_defects() -> dict:
    return json.loads((DATA / "audit" / "glm_defects.json").read_text(encoding="utf-8"))


def scan_targets(category: str) -> list:
    """라이브 스캔. category 는 'D02'/'D03'/'D10' 등 prefix 매칭."""
    out = []
    for exam in list(EXAMS.keys()):
        for f in sorted((DATA / exam).glob(f"{exam}_*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            for q in d.get("questions", []):
                n_choices = len(q.get("choices") or [])
                flags = scan_question(q, exam, n_choices)
                if any(fl.startswith(category) for fl in flags) \
                        and not q.get("fix_" + category + "_at"):
                    out.append((f, q.get("number")))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("category", choices=sorted(CATEGORY_PROMPT))
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--limit", type=int, help="총 처리 문항 상한")
    ap.add_argument("--breaker", type=int, default=15)
    args = ap.parse_args()

    cat = args.category
    print(f"=== fix {cat} ===")
    targets = scan_targets(cat)
    print(f"대상: {len(targets)} 문항")
    if args.limit:
        targets = targets[:args.limit]
        print(f"limit 적용: {len(targets)} 문항")
    if not targets:
        return

    # 파일별 그룹화 (같은 파일은 한 번만 load/save)
    by_file: dict[Path, list[int]] = {}
    for f, n in targets:
        by_file.setdefault(f, []).append(n)

    breaker = Breaker(n=args.breaker)
    done = failed = 0
    lock = threading.Lock()

    def process_batch(f: Path, exam: str, qs_data: list[tuple[dict, dict]]):
        """qs_data: [(d_root_ref, q_ref), ...] — 같은 파일 안 문항들"""
        nonlocal done, failed
        if breaker.tripped:
            return
        qs = [q for _, q in qs_data]
        try:
            text = call_claude(build_prompt(cat, exam, qs))
            j = parse_response(text)
            results = j.get("results") if isinstance(j, dict) else None
            if not isinstance(results, list):
                raise ValueError(f"no results: {text[:200]!r}")
            by_num = {r.get("qnum"): r for r in results if isinstance(r, dict)}
            ok = 0
            for _, q in qs_data:
                r = by_num.get(q["number"])
                if not r:
                    continue
                if APPLIERS[cat](q, r):
                    ok += 1
            if ok == 0:
                breaker.bad()
            else:
                breaker.ok()
            with lock:
                done += ok
                failed += len(qs) - ok
            print(f"  {f.stem} Q{[q['number'] for q in qs]} → {ok}/{len(qs)}", flush=True)
        except Exception as e:
            breaker.bad()
            with lock:
                failed += len(qs)
            print(f"  {f.stem} Q{[q['number'] for q in qs]} ✗ {e}", flush=True)

    t0 = time.time()
    # 각 파일을 독립적으로 처리 — 파일 내 batch_size 그룹.
    futs = []
    ex_executor = cf.ThreadPoolExecutor(max_workers=max(1, args.workers))
    try:
        for path, qnums in by_file.items():
            d = json.loads(path.read_text(encoding="utf-8"))
            num_to_q = {q.get("number"): q for q in d.get("questions", [])}
            qs_objs = [num_to_q[n] for n in qnums if n in num_to_q]
            exam = path.parent.name

            file_batches = [qs_objs[i:i+BATCH_SIZE]
                            for i in range(0, len(qs_objs), BATCH_SIZE)]

            def make_task(p, batch, dd):
                def task():
                    process_batch(p, exam, [(dd, q) for q in batch])
                    # 파일별 즉시 저장 (한 batch 끝날 때마다)
                    p.write_text(json.dumps(dd, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
                return task

            for batch in file_batches:
                futs.append(ex_executor.submit(make_task(path, batch, d)))
                if breaker.tripped:
                    break
            if breaker.tripped:
                break

        for f in cf.as_completed(futs):
            f.result()
            if breaker.tripped:
                for ff in futs:
                    ff.cancel()
                print("  [breaker tripped] 중단", flush=True)
                break
    finally:
        ex_executor.shutdown(wait=True)

    dt = time.time() - t0
    print(f"\n=== {cat} 결과: 처리 {done}  실패 {failed}  소요 {dt/60:.1f}분 ===")


if __name__ == "__main__":
    main()

"""needs_vision_reprocess=true 문항을 vision-capable model (claude -p) 로 재처리.

extract_concepts.py 는 텍스트만 입력하므로, 이미지가 핵심인 문항은 정답 보기·해설
이미지를 모델이 보지 못한 채 concepts/explanation_detailed 가 추출되어 있다.
이 스크립트는 해당 1,206 문항을 대상으로:

1. 문항의 모든 이미지 URL (question_images, choice images, explanation_images) 다운로드
2. claude -p 로 이미지 Read + 문제 텍스트 입력 → JSON 응답
3. 응답을 question 에 비파괴 적용:
   - concepts_pre_vision = 이전 concepts
   - explanation_detailed_pre_vision = 이전 explanation_detailed
   - concepts = 새 (vision 기반)
   - explanation_detailed = 새 (audit score < 3 이거나 vision 으로 보강 필요한 경우)
   - vision_image_summary = 이미지에서 본 내용 요약 (학습 자료)
   - vision_reprocessed_at = 타임스탬프
   - needs_vision_reprocess = false (완료 표시)
4. 5문항마다 중간 저장. circuit breaker 내장.

사용법:
  python3 vision_reprocess.py c1                 # c1 전체 (45개)
  python3 vision_reprocess.py k1 --limit 5       # k1 의 앞 5개만 테스트
  python3 vision_reprocess.py all-exams --workers 3
  python3 vision_reprocess.py c1 --dry           # 첫 프롬프트만 출력
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

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


# ── 이미지 다운로드 ──────────────────────────────────────

def download_image(url: str, dest: Path, *, timeout: int = 30) -> None:
    """이미지 URL → dest 파일로 저장. 실패 시 RuntimeError."""
    raw = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(raw, timeout=timeout) as r:
        dest.write_bytes(r.read())


def collect_image_urls(q: dict) -> list[tuple[str, str]]:
    """문항에서 (label, url) 페어를 수집.

    label: 'Q' (문제), '①'~'⑤' (보기 i), 'EXPL' (해설)
    """
    out: list[tuple[str, str]] = []
    for u in (q.get("question_images") or []):
        out.append(("Q", u))
    for i, c in enumerate(q.get("choices") or []):
        glyph = _CIRCLED[i] if i < len(_CIRCLED) else f"#{i+1}"
        for u in (c.get("images") or []):
            out.append((glyph, u))
    for u in (q.get("explanation_images") or []):
        out.append(("해설", u))
    return out


# ── prompt ──────────────────────────────────────────────

def _q_text(q: dict) -> str:
    choices = q.get("choices") or []

    def ct(i: int) -> str:
        c = choices[i] if i < len(choices) else {"text": ""}
        t = (c.get("text") or "").strip()
        if not t and (c.get("images") or []):
            t = "[이미지]"
        return t or "(비어있음)"

    n = min(len(choices), len(_CIRCLED)) or 4
    return "".join(f"{_CIRCLED[i]} {ct(i)}\n" for i in range(n))


def build_prompt(exam_code: str, q: dict, img_files: list[tuple[str, str]]) -> str:
    """img_files: [(label, filename), ...] — 같은 cwd 안 파일명들."""
    name = EXAMS.get(exam_code, {"name": ""}).get("name", "")
    choice_lines = _q_text(q)
    prev_concepts = q.get("concepts") or []
    prev_expl = (q.get("explanation_detailed") or q.get("explanation") or "").strip()

    img_list = "\n".join(f"- `{fn}` ({label})" for label, fn in img_files) or "(이미지 없음)"

    return f"""당신은 {name} 전문 강사입니다. 아래 기출문제를 **이미지까지 확인하여** 재분석하세요.

[과목] {q.get('subject') or ''}
[문제] {q.get('question') or ''}
[보기]
{choice_lines}[정답] {q.get('answer', '?')}번
[기존 해설]
{prev_expl or '(없음)'}

[기존 concepts] {prev_concepts}

이 디렉터리에 다음 이미지들이 있습니다. **모두 Read 도구로 열어서** 내용을 확인하세요:
{img_list}

각 이미지가 표(시트), 다이어그램, 회로도, 그래프, 한자/사진 등 무엇이든
거기에 적힌 모든 정보 (수식, 숫자, 라벨, 화살표 방향, 한자, 인명 등) 를 빠짐없이 읽어내세요.

그 다음 다음을 수행:

1) 이미지에서 본 내용을 한국어 평문으로 요약 (vision_image_summary).
   - 표라면 표를 마크다운 테이블로 옮겨 적고
   - 수식이라면 LaTeX 로 옮겨 적고
   - 다이어그램/사진이면 핵심 요소를 텍스트로 묘사
   - 학습자가 이 요약만 봐도 원본 이미지 없이 문제를 풀 수 있도록 충분하게.

2) 이미지를 본 후의 핵심 개념을 1~3개 한국어 명사구로 추출 (concepts).
   - 추상적 분야명("회로 이론") 금지. 구체적 개념("RLC 직렬 공진 주파수") 권장.

3) 이미지·문제·기존 해설을 종합한 새 해설 (improved_explanation). 평문 (마크다운 기호 없이):
   핵심 개념
   - 1~2줄
   정답 분석
   - 정답이 왜 옳은지 + 이미지에서 핵심 단서를 어떻게 읽었는지 (3~5줄)
   오답 분석
   - 각 보기마다 (①, ②, ③, …) 1줄씩 (보기 수가 5개면 ⑤까지)
   섹션 제목은 위와 정확히 동일하게.

출력은 다른 텍스트/코드펜스 없이 JSON 객체 하나만:

{{"vision_image_summary": "...", "concepts": ["...", "..."], "improved_explanation": "..."}}

규칙:
- improved_explanation 안 줄바꿈은 \\n.
- concepts 는 1~3 원소 배열.
- JSON 외 텍스트/주석/펜스 절대 금지.
"""


# ── claude -p ────────────────────────────────────────────

def call_claude(cwd: Path, prompt: str, *, timeout: int = 300, retries: int = 3) -> str:
    last_err = ""
    for attempt in range(retries):
        if attempt:
            time.sleep(2 + 2 * attempt)
        try:
            r = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True, text=True, cwd=str(cwd), timeout=timeout,
            )
            if r.returncode != 0:
                last_err = f"rc={r.returncode} stderr={r.stderr.strip()[:200]}"
                continue
            out = r.stdout.strip()
            if not out:
                last_err = "empty output"
                continue
            return out
        except subprocess.TimeoutExpired:
            last_err = "timeout"
            continue
    raise RuntimeError(f"claude failed after {retries}: {last_err}")


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
        raise ValueError(f"no JSON object: {text[:200]!r}")
    return json.loads(m.group(0))


# ── per-question worker ─────────────────────────────────

def process_question(exam_code: str, q: dict, *, dry: bool = False) -> dict:
    """One question → vision response. Mutates q in-place (unless dry)."""
    img_urls = collect_image_urls(q)
    if not img_urls:
        # needs_vision_reprocess 인데 이미지가 없으면 그냥 플래그만 해제
        if not dry:
            q["needs_vision_reprocess"] = False
        return {"qnum": q.get("number"), "no_images": True}

    with tempfile.TemporaryDirectory(prefix="vrx_") as td:
        tdp = Path(td)
        # 다운로드
        img_files: list[tuple[str, str]] = []
        for i, (label, url) in enumerate(img_urls):
            ext = url.rsplit(".", 1)[-1].split("?")[0].lower()
            if ext not in ("gif", "png", "jpg", "jpeg", "webp"):
                ext = "gif"
            fname = f"img{i+1}.{ext}"
            try:
                download_image(url, tdp / fname)
                img_files.append((label, fname))
            except Exception as e:
                print(f"    ! img dl 실패 {url}: {e}", flush=True)

        if not img_files:
            raise RuntimeError("모든 이미지 다운로드 실패")

        prompt = build_prompt(exam_code, q, img_files)
        if dry:
            print(prompt)
            return {"qnum": q.get("number"), "dry": True}

        text = call_claude(tdp, prompt)
        j = parse_response(text)

    # validate
    concepts = j.get("concepts") or []
    if not isinstance(concepts, list) or not concepts:
        raise ValueError(f"concepts invalid: {j!r}")
    concepts = [str(c).strip() for c in concepts if str(c).strip()][:3]
    if not concepts:
        raise ValueError("concepts empty after strip")

    vision_summary = str(j.get("vision_image_summary") or "").strip()
    improved = j.get("improved_explanation")
    if improved is not None:
        improved = str(improved).strip() or None

    # 비파괴 적용
    if "concepts_pre_vision" not in q:
        q["concepts_pre_vision"] = q.get("concepts", [])
    if improved and "explanation_detailed_pre_vision" not in q:
        q["explanation_detailed_pre_vision"] = q.get("explanation_detailed", "")

    q["concepts"] = concepts
    q["vision_image_summary"] = vision_summary
    if improved:
        q["explanation_detailed"] = improved
    q["vision_reprocessed_at"] = int(time.time())
    q["needs_vision_reprocess"] = False

    return {
        "qnum": q.get("number"),
        "concepts": concepts,
        "summary_chars": len(vision_summary),
        "improved": bool(improved),
    }


# ── circuit breaker ─────────────────────────────────────

class CircuitBreaker:
    def __init__(self, threshold: int = 15):
        self.threshold = threshold
        self._fails = 0
        self._lock = threading.Lock()
        self.tripped = False

    def ok(self):
        with self._lock:
            self._fails = 0

    def bad(self):
        with self._lock:
            self._fails += 1
            if self._fails >= self.threshold:
                self.tripped = True


# ── per-session processing ──────────────────────────────

def process_session(exam_code: str, session_path: Path, *,
                    limit: int | None = None, workers: int = 1,
                    dry: bool = False,
                    breaker: CircuitBreaker | None = None) -> dict:
    d = json.loads(session_path.read_text(encoding="utf-8"))
    todo = [q for q in d["questions"] if q.get("needs_vision_reprocess")]
    if limit is not None:
        todo = todo[:limit]
    if not todo:
        return {"session": session_path.name, "done": 0, "skip": True}

    print(f"[{session_path.name}] 대상 {len(todo)} 문항", flush=True)
    breaker = breaker or CircuitBreaker()
    done = failed = 0
    lock = threading.Lock()

    def save():
        session_path.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    def worker(q):
        nonlocal done, failed
        if breaker.tripped:
            return
        try:
            r = process_question(exam_code, q, dry=dry)
            breaker.ok()
            with lock:
                done += 1
            print(f"  Q{r['qnum']:<3} ✓  concepts={r.get('concepts')!s:60.60} "
                  f"summary={r.get('summary_chars',0)}자 imp={r.get('improved')}",
                  flush=True)
        except Exception as e:
            breaker.bad()
            with lock:
                failed += 1
            print(f"  Q{q.get('number')} ✗ {type(e).__name__}: {e}", flush=True)

    if workers <= 1:
        for i, q in enumerate(todo, 1):
            if breaker.tripped:
                print(f"  [breaker tripped] {breaker.threshold}회 연속 실패, 중단", flush=True)
                break
            worker(q)
            if i % 5 == 0 and not dry:
                save()
    else:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(worker, q) for q in todo]
            for i, _ in enumerate(cf.as_completed(futs), 1):
                if i % 5 == 0 and not dry:
                    save()
                if breaker.tripped:
                    for f in futs:
                        f.cancel()
                    print(f"  [breaker tripped] 중단", flush=True)
                    break

    if not dry:
        save()
    print(f"  [{session_path.name}] done={done} fail={failed}", flush=True)
    return {
        "session": session_path.name,
        "done": done, "failed": failed,
        "tripped": breaker.tripped,
    }


def process_exam(exam_code: str, *, limit_per_session: int | None = None,
                 workers: int = 1, dry: bool = False,
                 breaker: CircuitBreaker | None = None) -> dict:
    files = sorted((DATA / exam_code).glob(f"{exam_code}_*.json"))
    breaker = breaker or CircuitBreaker()
    grand = {"done": 0, "failed": 0, "sessions": 0}
    for p in files:
        # quick gate
        d = json.loads(p.read_text(encoding="utf-8"))
        if not any(q.get("needs_vision_reprocess") for q in d["questions"]):
            continue
        r = process_session(exam_code, p, limit=limit_per_session,
                            workers=workers, dry=dry, breaker=breaker)
        grand["done"] += r.get("done", 0)
        grand["failed"] += r.get("failed", 0)
        grand["sessions"] += 1
        if r.get("tripped"):
            grand["tripped"] = True
            print(f"[{exam_code}] breaker, 중단", flush=True)
            break
    return grand


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exam_code", help="자격증 코드 또는 all-exams")
    ap.add_argument("--limit", type=int, help="각 회차에서 앞 N개만 (테스트용)")
    ap.add_argument("--workers", type=int, default=1, help="병렬 호출 수 (기본 1)")
    ap.add_argument("--dry", action="store_true", help="첫 프롬프트만 출력")
    ap.add_argument("--breaker", type=int, default=15, help="연속 실패 임계치")
    args = ap.parse_args()

    t0 = time.time()
    breaker = CircuitBreaker(threshold=args.breaker)
    targets = list(EXAMS.keys()) if args.exam_code == "all-exams" else [args.exam_code]
    grand = {"done": 0, "failed": 0, "sessions": 0}
    for code in targets:
        if code not in EXAMS:
            print(f"unknown {code}", flush=True); continue
        print(f"\n====== {code} · {EXAMS[code]['name']} ======", flush=True)
        r = process_exam(code, limit_per_session=args.limit,
                         workers=args.workers, dry=args.dry,
                         breaker=breaker)
        grand["done"] += r["done"]
        grand["failed"] += r["failed"]
        grand["sessions"] += r["sessions"]
        if r.get("tripped"):
            break
    dt = time.time() - t0
    print(f"\n=== 총 {grand['sessions']}회차 · 처리 {grand['done']} · "
          f"실패 {grand['failed']} · 소요 {dt/60:.1f}분 ===")


if __name__ == "__main__":
    main()

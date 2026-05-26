"""개념 본문 생성 — concepts/<exam>/index.json 의 각 concept 에 `body` 필드를 채운다.

각 concept 마다 다음 5개 섹션을 평문/배열로 생성:
- definition  (1~2줄 정의)
- intuition   (1~2줄 직관·왜 중요한지)
- key_points  (2~4 bullet, 핵심 공식·규칙·특징)
- pitfalls    (1~2줄 자주 헷갈리는 점)
- example     (1~2줄 작은 예시)

본문은 실제 출제 양상에 맞춰지도록 refs 에서 샘플 문항 1~2개를 prompt 에 함께 넣어
근거(grounding)를 만든다.

특징:
- 단일 `claude -p` 호출 → JSON 한 줄 파싱.
- 이미 `body` 가 있는 concept 은 자동 스킵 (재실행 안전).
- N concepts 마다 index.json 중간 저장 (atomic write).
- 단일 워커 권장 (claude CLI throttle 회피). --workers 로 늘릴 수 있음.

사용법:
  python3 extract_concept_body.py iz                 # 정처기 전체
  python3 extract_concept_body.py iz --limit 10      # 앞 10개만
  python3 extract_concept_body.py iz --dry           # 첫 프롬프트만 출력
  python3 extract_concept_body.py iz --workers 2     # 병렬 워커
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from exams import EXAMS  # noqa: E402
from call_glm import call_glm  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

CLAUDE_TIMEOUT = 300
SAVE_EVERY = 5  # concepts


def index_path(exam_code: str) -> Path:
    return DATA / "concepts" / exam_code / "index.json"


def session_path(exam_code: str, session_code: str) -> Path:
    return DATA / exam_code / f"{exam_code}_{session_code}.json"


_session_cache: dict[tuple[str, str], dict | None] = {}
_session_cache_lock = threading.Lock()


def load_session(exam_code: str, session_code: str) -> dict | None:
    key = (exam_code, session_code)
    with _session_cache_lock:
        if key in _session_cache:
            return _session_cache[key]
    p = session_path(exam_code, session_code)
    if not p.exists():
        with _session_cache_lock:
            _session_cache[key] = None
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    with _session_cache_lock:
        _session_cache[key] = d
    return d


def find_question(exam_code: str, ref: dict) -> dict | None:
    sess = load_session(exam_code, ref.get("session", ""))
    if not sess:
        return None
    qnum = ref.get("qnum")
    for q in sess.get("questions", []):
        if q.get("number") == qnum:
            return q
    return None


def sample_refs(refs: list[dict], n: int = 2) -> list[dict]:
    """refs 에서 다양성 위해 앞쪽 + 중간 1개 (최대 n개)."""
    if not refs:
        return []
    if len(refs) <= n:
        return list(refs)
    picks = [refs[0]]
    if n >= 2 and len(refs) >= 2:
        picks.append(refs[len(refs) // 2])
    if n >= 3 and len(refs) >= 3:
        picks.append(refs[-1])
    return picks[:n]


def _q_block(q: dict) -> str:
    choices = q.get("choices") or []

    def ct(i: int) -> str:
        c = choices[i] if i < len(choices) else {"text": ""}
        t = (c.get("text") or "").strip()
        if not t and (c.get("images") or []):
            t = "[이미지]"
        return t or "(비어있음)"

    return (
        f"[과목] {q.get('subject') or ''}\n"
        f"[문제] {q.get('question') or ''}\n"
        f"[보기] ① {ct(0)} / ② {ct(1)} / ③ {ct(2)} / ④ {ct(3)}\n"
        f"[정답] {q.get('answer', '?')}번"
    )


def prompt_for_concept(exam_code: str, concept: dict, sample_qs: list[dict]) -> str:
    exam = EXAMS.get(exam_code, {"name": ""})
    exam_name = exam.get("name", "")
    name_ko = concept.get("name_ko") or concept.get("id")
    name_en = concept.get("name_en") or ""
    members = concept.get("members") or []
    members_str = ", ".join(members[:8]) if members else name_ko
    subjects = ", ".join(concept.get("subjects") or [])

    if sample_qs:
        sample_block = "\n────────────\n".join(_q_block(q) for q in sample_qs)
        grounding = (
            f"\n이 개념이 실제로 출제된 사례입니다 (참고용, 본문은 일반적인 설명):\n"
            f"────────────\n{sample_block}\n────────────\n"
        )
    else:
        grounding = ""

    return f"""당신은 {exam_name} 전문 강사입니다.
"{name_ko}" 개념의 본문을 학습자가 한 화면에서 빠르게 이해할 수 있게 짧게 정리하세요.

[개념]
- 한국어: {name_ko}
- 영문: {name_en or "(없음)"}
- 관련 과목: {subjects}
- 동의 표현: {members_str}
{grounding}
다음 5개 섹션을 JSON 으로 출력하세요. 각 섹션은 학습용 평문 (마크다운 기호 없이).

1) definition  — 이 개념이 무엇인지 1~2줄 정의. 군더더기 없이 명료하게.
2) intuition   — 왜 이 개념이 중요한지, 어떤 직관/관점인지 1~2줄.
3) key_points  — 핵심 규칙·공식·특징·구성요소를 짧은 한 줄 bullet 2~4개로. 각 항목 30자 안팎.
4) pitfalls    — 시험에서 자주 헷갈리는 점/오답 유도 패턴 1~2줄. 위 출제 사례에서 단서가 있다면 반영.
5) example     — 가장 작은 예시 1개 1~2줄. (수식/숫자/문장 어떤 형태든 가능)

규칙:
- 모든 텍스트는 한국어. 전문용어 영문 병기는 괄호로 OK.
- 절대 마크다운 헤더(#)·강조(**)·코드펜스 사용 금지. 평문만.
- key_points 는 정확히 2~4개 항목.
- 출력은 JSON 객체 하나만. 코드펜스/주석/추가 텍스트 금지.

출력 스키마:
{{"definition": "...", "intuition": "...", "key_points": ["...", "..."], "pitfalls": "...", "example": "..."}}
"""


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
        raise ValueError(f"no JSON object found: {text[:200]!r}")
    return json.loads(m.group(0))


def normalize_body(rec: dict) -> dict:
    def s(v) -> str:
        return str(v or "").strip()

    definition = s(rec.get("definition"))
    intuition = s(rec.get("intuition"))
    pitfalls = s(rec.get("pitfalls"))
    example = s(rec.get("example"))
    kps_raw = rec.get("key_points") or []
    if not isinstance(kps_raw, list):
        raise ValueError(f"key_points must be list: {kps_raw!r}")
    key_points = [s(x) for x in kps_raw if s(x)]
    if not (2 <= len(key_points) <= 6):
        raise ValueError(f"key_points must have 2~6 items, got {len(key_points)}")
    if not (definition and intuition and pitfalls and example):
        raise ValueError("missing required body section")
    return {
        "definition": definition,
        "intuition": intuition,
        "key_points": key_points[:4],
        "pitfalls": pitfalls,
        "example": example,
    }


def call_claude(prompt: str, *, timeout: int = CLAUDE_TIMEOUT) -> str:
    """GLM-5.1 API 호출 (기존 claude CLI 대체)."""
    return call_glm(prompt, max_tokens=4096)


def call_with_retry(prompt: str, *, retries: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            raw = call_claude(prompt)
            rec = parse_response(raw)
            return normalize_body(rec)
        except Exception as e:
            last = e
            wait = 15 * (attempt + 1)
            time.sleep(wait)
    assert last is not None
    raise last


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def process_exam(exam_code: str, *, limit: int | None, workers: int, dry: bool) -> int:
    p = index_path(exam_code)
    if not p.exists():
        print(f"[{exam_code}] no index.json, skip")
        return 0

    idx = json.loads(p.read_text(encoding="utf-8"))
    todo: list[tuple[str, dict]] = [
        (cid, c) for cid, c in idx.items() if not c.get("body")
    ]
    if limit is not None:
        todo = todo[:limit]
    total_concepts = len(idx)
    print(f"[{exam_code}] todo {len(todo)} / total {total_concepts}", flush=True)
    if not todo:
        return 0

    if dry:
        cid, c = todo[0]
        sample_qs = []
        for ref in sample_refs(c.get("refs") or []):
            q = find_question(exam_code, ref)
            if q:
                sample_qs.append(q)
        print(prompt_for_concept(exam_code, c, sample_qs))
        return 0

    write_lock = threading.Lock()
    progress_lock = threading.Lock()
    done = 0
    failed = 0
    since_save = 0

    def work(cid: str, c: dict) -> tuple[str, dict | None, str | None]:
        sample_qs: list[dict] = []
        for ref in sample_refs(c.get("refs") or [], n=2):
            q = find_question(exam_code, ref)
            if q:
                sample_qs.append(q)
        prompt = prompt_for_concept(exam_code, c, sample_qs)
        try:
            body = call_with_retry(prompt)
            return cid, body, None
        except Exception as e:
            return cid, None, str(e)[:200]

    t0 = time.time()
    if workers <= 1:
        results_iter = (work(cid, c) for cid, c in todo)
    else:
        ex = cf.ThreadPoolExecutor(max_workers=workers)
        results_iter = ex.map(lambda x: work(*x), todo)

    for cid, body, err in results_iter:
        with progress_lock:
            done += 1
            elapsed = time.time() - t0
            rate = done / max(elapsed, 0.01)
            eta = (len(todo) - done) / max(rate, 0.001)
            if err:
                failed += 1
                print(f"[{exam_code}] {done}/{len(todo)} FAIL {cid}: {err}", flush=True)
            else:
                print(f"[{exam_code}] {done}/{len(todo)} ok {cid}  "
                      f"({rate:.2f}/s, eta {eta/60:.1f}m)", flush=True)
            if body:
                with write_lock:
                    idx[cid]["body"] = body
                    since_save += 1
                    if since_save >= SAVE_EVERY:
                        atomic_write_json(p, idx)
                        since_save = 0

    # final flush
    with write_lock:
        if since_save:
            atomic_write_json(p, idx)

    print(f"[{exam_code}] complete: {done - failed} ok / {failed} failed", flush=True)
    return done - failed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("exam_code", help="s2/g1/g2/iz/sa")
    ap.add_argument("--limit", type=int, default=None, help="처리할 concept 수 상한")
    ap.add_argument("--workers", type=int, default=1, help="병렬 워커 (기본 1)")
    ap.add_argument("--dry", action="store_true", help="첫 프롬프트만 출력")
    args = ap.parse_args()

    if args.exam_code not in EXAMS:
        print(f"unknown exam: {args.exam_code}", file=sys.stderr)
        sys.exit(2)

    process_exam(args.exam_code, limit=args.limit, workers=args.workers, dry=args.dry)


if __name__ == "__main__":
    main()

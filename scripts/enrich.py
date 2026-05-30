"""해설 AI 증강 스크립트 (멀티 자격증 대응).

각 문항에 '핵심 개념 → 정답 분석 → 오답 분석' 구조의 상세 해설을 생성하여
JSON에 `explanation_detailed` 필드로 저장한다.

특징:
- 기존 `explanation`은 보존 (웹앱에서 상세/간단 토글 가능).
- **이미 `explanation_detailed`가 있는 문항·회차는 자동 스킵** (재실행 안전).
- Claude Code CLI(`claude -p`)를 서브프로세스로 호출 → API 키 불필요.
- 연속 실패 임계치 초과 시 자동 중단 (circuit breaker).

사용법:
  python3 enrich.py <examCode>                       # 자격증 전체 회차
  python3 enrich.py <examCode> <YYYYMMDD>            # 단일 회차
  python3 enrich.py <examCode> --limit 10            # 각 회차에서 앞 10문항만
  python3 enrich.py <examCode> --workers 2           # 병렬 호출 수
  python3 enrich.py all-exams                        # 모든 자격증 전부
  python3 enrich.py <examCode> --dry                 # 첫 프롬프트만 출력하고 종료

예:
  python3 enrich.py iz                  # 정보처리기사 전체
  python3 enrich.py g1 20241026         # 공인중개사 1차 2024-10-26 회차
  python3 enrich.py all-exams           # 4종 모두
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from exams import EXAMS  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def prompt_for(exam_code: str, q: dict) -> str:
    exam = EXAMS.get(exam_code, {"name": ""})
    name = exam.get("name", "")
    choices = q.get("choices") or []

    def ct(i: int) -> str:
        c = choices[i] if i < len(choices) else {"text": ""}
        t = (c.get("text") or "").strip()
        if not t and (c.get("images") or []):
            t = "[이미지]"
        return t or "(비어있음)"

    n = min(len(choices), len(_CIRCLED)) or 4
    choice_lines = "".join(f"{_CIRCLED[i]} {ct(i)}\n" for i in range(n))

    return f"""당신은 {name} 전문 강사입니다.
아래 기출문제의 해설을 공부하기 좋은 형태로 다시 작성해주세요.

[과목] {q.get('subject') or ''}
[문제] {q.get('question') or ''}
[보기]
{choice_lines}[정답] {q.get('answer', '?')}번
[기존 해설] {(q.get('explanation') or '(기본 해설 없음)').strip() or '(기본 해설 없음)'}

다음 구조로 평문(마크다운 기호 없이)으로 작성하세요:

핵심 개념
- 이 문제가 묻는 개념을 1~2줄로 요약

정답 분석
- 정답이 왜 옳은지 구체적으로 (2~4줄)

오답 분석
- 각 보기마다 (①, ②, ③, …) 정답/오답 여부 + 오답이면 왜 틀렸는지 1줄씩. 보기 수가 5개면 ⑤까지 모두 다룬다.

다른 말은 붙이지 말고 위 세 섹션만 출력하세요. 섹션 제목은 위와 정확히 동일하게 사용하세요.
"""


MODEL: str | None = None  # --model 로 설정 (sonnet 등). None 이면 기본 세션 모델.


def call_claude(prompt: str, *, timeout: int = 120, retries: int = 3) -> str:
    import time as _time
    last_err = ""
    cmd = ["claude", "-p", prompt]
    if MODEL:
        cmd[1:1] = ["--model", MODEL]
    for attempt in range(retries):
        if attempt:
            _time.sleep(2 + 2 * attempt)
        r = subprocess.run(
            cmd,
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
    raise RuntimeError(f"claude failed after {retries}: {last_err}")


class CircuitBreaker:
    """연속 실패가 임계치를 넘으면 더 이상 요청하지 않음."""

    def __init__(self, threshold: int = 20):
        self.threshold = threshold
        self._fails = 0
        self._lock = threading.Lock()
        self.tripped = False

    def record_success(self):
        with self._lock:
            self._fails = 0

    def record_failure(self):
        with self._lock:
            self._fails += 1
            if self._fails >= self.threshold:
                self.tripped = True


def session_path(exam_code: str, session_code: str) -> Path:
    return DATA / exam_code / f"{exam_code}_{session_code}.json"


def all_sessions(exam_code: str) -> list[str]:
    """회차 목록을 sessions.json에서 읽되, 없으면 파일명으로 유추."""
    mani = DATA / exam_code / "sessions.json"
    if mani.exists():
        j = json.loads(mani.read_text(encoding="utf-8"))
        return [s["code"] for s in j["sessions"]]
    return sorted(
        p.name[len(exam_code) + 1:-5]
        for p in (DATA / exam_code).glob(f"{exam_code}_*.json")
    )


def session_already_done(path: Path) -> bool:
    """모든 문항에 explanation_detailed가 있으면 True."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return all(q.get("explanation_detailed") for q in d["questions"])
    except Exception:
        return False


def process_session(exam_code: str, session_code: str, *,
                    limit: int | None = None, workers: int = 1,
                    dry: bool = False, breaker: CircuitBreaker | None = None) -> dict:
    path = session_path(exam_code, session_code)
    if not path.exists():
        print(f"[{exam_code}/{session_code}] missing, skip", flush=True)
        return {"code": session_code, "done": 0, "failed": 0, "total": 0}

    if session_already_done(path):
        print(f"[{exam_code}/{session_code}] 전체 증강 완료 상태, skip", flush=True)
        return {"code": session_code, "done": 0, "skip": 1}

    d = json.loads(path.read_text(encoding="utf-8"))
    todo = [q for q in d["questions"] if not q.get("explanation_detailed")]
    if limit is not None:
        todo = todo[:limit]
    print(f"[{exam_code}/{session_code}] 대상 {len(todo)} / 총 {len(d['questions'])}",
          flush=True)
    if not todo:
        return {"code": session_code, "done": 0, "skip": len(d["questions"])}

    if dry:
        print(prompt_for(exam_code, todo[0]))
        return {"code": session_code, "dry": True}

    done = failed = 0
    lock = threading.Lock()
    breaker = breaker or CircuitBreaker()

    def worker(q):
        nonlocal done, failed
        if breaker.tripped:
            return
        try:
            text = call_claude(prompt_for(exam_code, q))
            q["explanation_detailed"] = text
            breaker.record_success()
            with lock:
                done += 1
            print(f"  Q{q['number']}  ✓  ({len(text)} 자)", flush=True)
        except Exception as e:
            breaker.record_failure()
            with lock:
                failed += 1
            print(f"  Q{q['number']}  ✗  {e}", flush=True)

    def save():
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    if workers <= 1:
        for i, q in enumerate(todo, 1):
            if breaker.tripped:
                print(f"  [circuit breaker] 연속 실패 {breaker.threshold}회, 중단", flush=True)
                break
            worker(q)
            if i % 5 == 0:
                save()
    else:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(worker, q) for q in todo]
            for i, _ in enumerate(cf.as_completed(futs), 1):
                if i % 5 == 0:
                    save()
                if breaker.tripped:
                    for f in futs:
                        f.cancel()
                    print(f"  [circuit breaker] 연속 실패 {breaker.threshold}회, 중단",
                          flush=True)
                    break

    save()
    return {
        "code": session_code,
        "done": done, "failed": failed,
        "total": len(d["questions"]),
        "tripped": breaker.tripped,
    }


def process_exam(exam_code: str, *, session_codes: list[str] | None = None,
                 limit: int | None = None, workers: int = 1,
                 dry: bool = False, breaker: CircuitBreaker | None = None) -> dict:
    if exam_code not in EXAMS:
        raise SystemExit(f"Unknown exam code: {exam_code}. See scripts/exams.py")
    codes = session_codes or all_sessions(exam_code)
    if not codes:
        print(f"[{exam_code}] 회차 없음"); return {"done": 0, "failed": 0, "sessions": 0}
    breaker = breaker or CircuitBreaker()
    totals = {"done": 0, "failed": 0, "sessions": 0, "tripped": False}
    for c in codes:
        r = process_session(exam_code, c, limit=limit, workers=workers,
                            dry=dry, breaker=breaker)
        totals["done"] += r.get("done", 0)
        totals["failed"] += r.get("failed", 0)
        totals["sessions"] += 1
        if r.get("tripped"):
            totals["tripped"] = True
            print(f"[{exam_code}] circuit breaker 발동, 중단", flush=True)
            break
    return totals


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("exam_code", help="자격증 코드 (예: s2, g1, g2, iz) 또는 'all-exams'")
    ap.add_argument("session_code", nargs="?", help="회차 코드 YYYYMMDD (생략 시 전체)")
    ap.add_argument("--limit", type=int, help="각 회차에서 앞 N개만")
    ap.add_argument("--workers", type=int, default=1, help="병렬 호출 수 (기본 1)")
    ap.add_argument("--dry", action="store_true", help="첫 프롬프트만 출력하고 종료")
    ap.add_argument("--breaker", type=int, default=20,
                    help="연속 실패 임계치 (기본 20)")
    ap.add_argument("--model", default=None, help="claude -p 모델 (sonnet/haiku 등)")
    args = ap.parse_args()

    global MODEL
    MODEL = args.model

    t0 = time.time()
    grand = {"done": 0, "failed": 0, "sessions": 0, "exams": 0}

    if args.exam_code == "all-exams":
        targets = list(EXAMS.keys())
    else:
        targets = [args.exam_code]

    breaker = CircuitBreaker(threshold=args.breaker)
    for code in targets:
        print(f"\n========== {code} · {EXAMS[code]['name']} ==========", flush=True)
        sessions = [args.session_code] if args.session_code else None
        r = process_exam(code, session_codes=sessions, limit=args.limit,
                         workers=args.workers, dry=args.dry, breaker=breaker)
        grand["done"] += r["done"]
        grand["failed"] += r["failed"]
        grand["sessions"] += r["sessions"]
        grand["exams"] += 1
        if r.get("tripped"):
            break

    dt = time.time() - t0
    print(f"\n=== {grand['exams']}자격증 · {grand['sessions']}회차 · "
          f"증강 {grand['done']} / 실패 {grand['failed']} · 소요 {dt/60:.1f}분 ===")


if __name__ == "__main__":
    main()

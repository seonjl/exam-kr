"""개념 추출 + 해설 감사 + 해설 보완 (단일 호출 통합).

각 문항에서 1~3개 핵심 개념(한국어 명사구)을 뽑고,
같은 호출에서 기존 `explanation_detailed` 가 그 개념을 정확히 설명하는지 0~3점으로 감사한다.
score < 3 인 경우 같은 호출에서 받은 `improved_explanation` 으로 `explanation_detailed` 를 덮어쓴다.
원본 `explanation` (소스에서 수집한 인간 해설) 은 항상 보존한다.

특징:
- 단일 `claude -p` 호출 → JSON 한 줄 파싱 (concepts / audit / improved_explanation).
- **이미 `concepts` 가 있는 문항은 자동 스킵** (재실행 안전).
- 회차 단위 진행 + 5문항마다 중간 저장.
- CircuitBreaker 로 연속 실패시 중단.
- enrich.py 와 같은 인터페이스: `--workers`, `--limit`, `--dry`, `all-exams`.

사용법:
  python3 extract_concepts.py iz                       # 정보처리기사 전체
  python3 extract_concepts.py iz 20200606              # 단일 회차
  python3 extract_concepts.py iz --limit 5             # 각 회차에서 앞 5문항만
  python3 extract_concepts.py iz --workers 2           # 병렬 호출 수
  python3 extract_concepts.py iz --dry                 # 첫 프롬프트만 출력하고 종료
  python3 extract_concepts.py all-exams                # 4종 모두

출력 (각 question 에 추가되는 필드):
  - concepts: ["개념A", "개념B"]                        # 한국어 명사구 1~3개 (raw)
  - explanation_audit: { score, missing, improved, prev_chars }
  - explanation_detailed: (audit.score < 3 일 때) 개선판으로 덮어씀
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

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


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

    existing = (q.get("explanation_detailed") or q.get("explanation") or "").strip() \
        or "(해설 없음)"

    return f"""당신은 {name} 전문 강사입니다.
아래 기출문제에 대해 (1) 핵심 개념 추출, (2) 기존 해설 감사, (3) 필요 시 해설 보완을 수행합니다.

[과목] {q.get('subject') or ''}
[문제] {q.get('question') or ''}
[보기]
① {ct(0)}
② {ct(1)}
③ {ct(2)}
④ {ct(3)}
[정답] {q.get('answer', '?')}번
[기존 해설]
{existing}

다음 작업을 수행하세요.

1) 이 문제가 묻는 핵심 개념을 1~3개 한국어 명사구로 뽑으세요.
   - 추상적 분야명("프로그래밍", "통계학") 금지.
   - 구체적 개념("순차 코드 부여 방식", "표본 분산의 자유도") 권장.
   - 가장 중심적인 개념을 첫 번째로 두고, 보조 개념을 1~2개 더 추가.

2) 위 [기존 해설] 이 그 개념(들)을 정확히 설명하는지 0~3점으로 감사하세요.
   - 0: 틀림 (사실관계 오류)
   - 1: 부족 (핵심 빠짐 또는 오해 소지)
   - 2: 맞지만 thin (정답은 맞지만 개념 설명이 얕음)
   - 3: 충분 (개념과 정답·오답 분석 모두 명료)
   score 가 0~2 면 무엇이 빠졌는지 한 줄로 적으세요. score 가 3 이면 missing 은 빈 문자열.

3) score 가 0~2 인 경우에만 개선된 해설을 작성하세요. 형식은 다음과 같이 평문 (마크다운 기호 없이):
   핵심 개념
   - 1~2줄
   정답 분석
   - 정답이 왜 옳은지 (2~4줄)
   오답 분석
   - ① / ② / ③ / ④ 각 1줄
   섹션 제목은 위와 정확히 동일하게.
   score 가 3 이면 improved_explanation 은 null.

출력은 다른 텍스트 없이 **JSON 한 줄** 만:
{{"concepts": ["...", "..."], "audit": {{"score": 2, "missing": "..."}}, "improved_explanation": "..." }}

improved_explanation 안의 줄바꿈은 반드시 \\n 으로 이스케이프하세요.
JSON 외의 어떤 설명·주석·코드펜스도 출력하지 마세요.
"""


_JSON_RE = re.compile(r"\{[\s\S]*\}\s*$")


def parse_response(text: str) -> dict:
    """모델 응답에서 JSON 객체를 안전하게 뽑는다.

    코드펜스(```json ... ```) 가 섞여 와도 처리하고, 마지막 { ... } 블록을 우선한다.
    """
    s = text.strip()
    # strip code fences
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    # try direct parse
    try:
        return json.loads(s)
    except Exception:
        pass
    # fallback: greedy match the last {...}
    m = _JSON_RE.search(s)
    if not m:
        raise ValueError(f"no JSON object found: {text[:200]!r}")
    return json.loads(m.group(0))


def normalize_record(rec: dict) -> dict:
    """모델 응답을 검증하고 표준 형태로 정리."""
    concepts = rec.get("concepts") or []
    if not isinstance(concepts, list) or not concepts:
        raise ValueError(f"concepts must be a non-empty list: {rec!r}")
    concepts = [str(c).strip() for c in concepts if str(c).strip()][:3]
    if not concepts:
        raise ValueError("concepts empty after strip")

    audit = rec.get("audit") or {}
    score = audit.get("score")
    if not isinstance(score, int) or score < 0 or score > 3:
        raise ValueError(f"audit.score must be int 0..3: {audit!r}")
    missing = str(audit.get("missing") or "").strip()

    improved = rec.get("improved_explanation")
    if improved is not None:
        improved = str(improved).strip() or None

    if score < 3 and not improved:
        # 모델이 보완을 빼먹은 경우 — 감사만 채택, 덮어쓰기 안 함.
        improved = None

    return {
        "concepts": concepts,
        "audit": {"score": score, "missing": missing},
        "improved_explanation": improved,
    }


def call_claude(prompt: str, *, timeout: int = 180) -> str:
    r = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("claude returned empty output")
    return out


class CircuitBreaker:
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
    mani = DATA / exam_code / "sessions.json"
    if mani.exists():
        j = json.loads(mani.read_text(encoding="utf-8"))
        return [s["code"] for s in j["sessions"]]
    return sorted(
        p.name[len(exam_code) + 1:-5]
        for p in (DATA / exam_code).glob(f"{exam_code}_*.json")
    )


def session_already_done(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return all(q.get("concepts") for q in d["questions"])
    except Exception:
        return False


def apply_record(q: dict, rec: dict) -> None:
    """검증 끝난 record 를 question dict 에 반영."""
    q["concepts"] = rec["concepts"]
    score = rec["audit"]["score"]
    improved = rec["improved_explanation"]
    prev = q.get("explanation_detailed") or ""
    did_improve = bool(improved) and score < 3
    q["explanation_audit"] = {
        "score": score,
        "missing": rec["audit"]["missing"],
        "improved": did_improve,
        "prev_chars": len(prev),
    }
    if did_improve:
        q["explanation_detailed"] = improved


def process_session(exam_code: str, session_code: str, *,
                    limit: int | None = None, workers: int = 1,
                    dry: bool = False, breaker: CircuitBreaker | None = None) -> dict:
    path = session_path(exam_code, session_code)
    if not path.exists():
        print(f"[{exam_code}/{session_code}] missing, skip", flush=True)
        return {"code": session_code, "done": 0, "failed": 0, "total": 0}

    if session_already_done(path):
        print(f"[{exam_code}/{session_code}] 전체 추출 완료 상태, skip", flush=True)
        return {"code": session_code, "done": 0, "skip": 1}

    d = json.loads(path.read_text(encoding="utf-8"))
    todo = [q for q in d["questions"] if not q.get("concepts")]
    if limit is not None:
        todo = todo[:limit]
    print(f"[{exam_code}/{session_code}] 대상 {len(todo)} / 총 {len(d['questions'])}",
          flush=True)
    if not todo:
        return {"code": session_code, "done": 0, "skip": len(d["questions"])}

    if dry:
        print(prompt_for(exam_code, todo[0]))
        return {"code": session_code, "dry": True}

    done = failed = improved_count = 0
    score_hist = {0: 0, 1: 0, 2: 0, 3: 0}
    lock = threading.Lock()
    breaker = breaker or CircuitBreaker()

    def worker(q):
        nonlocal done, failed, improved_count
        if breaker.tripped:
            return
        try:
            text = call_claude(prompt_for(exam_code, q))
            rec = normalize_record(parse_response(text))
            apply_record(q, rec)
            breaker.record_success()
            with lock:
                done += 1
                score_hist[rec["audit"]["score"]] += 1
                if q["explanation_audit"]["improved"]:
                    improved_count += 1
            tag = "✎" if q["explanation_audit"]["improved"] else "·"
            print(f"  Q{q['number']}  ✓ {tag}  score={rec['audit']['score']} "
                  f"concepts={rec['concepts']}", flush=True)
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
                print(f"  [circuit breaker] 연속 실패 {breaker.threshold}회, 중단",
                      flush=True)
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
    print(f"  [{session_code}] 완료 done={done} fail={failed} "
          f"개선={improved_count} score_hist={score_hist}", flush=True)
    return {
        "code": session_code,
        "done": done, "failed": failed,
        "improved": improved_count,
        "score_hist": score_hist,
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
        print(f"[{exam_code}] 회차 없음")
        return {"done": 0, "failed": 0, "improved": 0, "sessions": 0}
    breaker = breaker or CircuitBreaker()
    totals = {"done": 0, "failed": 0, "improved": 0, "sessions": 0,
              "tripped": False}
    for c in codes:
        r = process_session(exam_code, c, limit=limit, workers=workers,
                            dry=dry, breaker=breaker)
        totals["done"] += r.get("done", 0)
        totals["failed"] += r.get("failed", 0)
        totals["improved"] += r.get("improved", 0)
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
    args = ap.parse_args()

    t0 = time.time()
    grand = {"done": 0, "failed": 0, "improved": 0, "sessions": 0, "exams": 0}

    targets = list(EXAMS.keys()) if args.exam_code == "all-exams" else [args.exam_code]

    breaker = CircuitBreaker(threshold=args.breaker)
    for code in targets:
        print(f"\n========== {code} · {EXAMS[code]['name']} ==========", flush=True)
        sessions = [args.session_code] if args.session_code else None
        r = process_exam(code, session_codes=sessions, limit=args.limit,
                         workers=args.workers, dry=args.dry, breaker=breaker)
        grand["done"] += r["done"]
        grand["failed"] += r["failed"]
        grand["improved"] += r["improved"]
        grand["sessions"] += r["sessions"]
        grand["exams"] += 1
        if r.get("tripped"):
            break

    dt = time.time() - t0
    print(f"\n=== {grand['exams']}자격증 · {grand['sessions']}회차 · "
          f"추출 {grand['done']} / 해설 보완 {grand['improved']} / "
          f"실패 {grand['failed']} · 소요 {dt/60:.1f}분 ===")


if __name__ == "__main__":
    main()

"""enrich + concept 추출 + taxonomy ID 매핑 통합 (단일 호출, 5문항 배치).

기존 3-step 파이프라인 (enrich → extract_concepts → normalize_concepts) 을
한 호출로 압축. 사전 정의된 taxonomy.json 의 ID 중에서 매핑하므로
별도 normalize 단계 불필요.

각 호출은 5문항 묶음 → JSON results 배열 반환:
- explanation_detailed: 핵심 개념/정답 분석/오답 분석 3섹션 평문
- concepts:    raw 한국어 명사구 1~3개 (검색·표시용)
- concept_ids: taxonomy 의 ID 1~3개 (정확 매칭, 없으면 빈 배열)

특징:
- 단일 `claude -p` 호출 → JSON 한 줄 파싱.
- 이미 explanation_detailed + concept_ids 가 있는 문항은 자동 스킵 (재실행 안전).
- 회차 단위 진행 + 배치마다 중간 저장.
- claude CLI 실패 시 retry (최대 3회, 30/60/90s backoff).
- 단일 워커 권장 (claude CLI throttle 회피).

사용법:
  python3 extract_v2.py sa                   # 전체 회차
  python3 extract_v2.py sa 20220424          # 단일 회차
  python3 extract_v2.py sa --limit 5         # 회차당 앞 5문항만
  python3 extract_v2.py sa --dry             # 첫 프롬프트만 출력하고 종료
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from exams import EXAMS  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

BATCH_SIZE = 5
CLAUDE_TIMEOUT = 600


def taxonomy_path(exam_code: str) -> Path:
    return DATA / "concepts" / exam_code / "taxonomy.json"


def load_taxonomy(exam_code: str) -> list[dict]:
    p = taxonomy_path(exam_code)
    if not p.exists():
        raise SystemExit(
            f"taxonomy 없음: {p}\n"
            "사전 정의된 개념 체계를 먼저 작성하세요."
        )
    return json.loads(p.read_text(encoding="utf-8"))["concepts"]


def normalize_subject(s: str) -> str:
    s = (s or "").strip()
    m = re.match(r"^\d+\s*과목\s*[:：]\s*(.+)$", s)
    return (m.group(1) if m else s).strip()


def taxonomy_for_subject(taxonomy: list[dict], subject: str) -> list[dict]:
    """과목 일치 우선, 없으면 전체."""
    subj = normalize_subject(subject)
    matched = [c for c in taxonomy if c["subject"] == subj]
    return matched or taxonomy


def _q_block(q: dict) -> str:
    choices = q.get("choices") or []

    def ct(i: int) -> str:
        c = choices[i] if i < len(choices) else {"text": ""}
        t = (c.get("text") or "").strip()
        if not t and (c.get("images") or []):
            t = "[이미지]"
        return t or "(비어있음)"

    raw_expl = (q.get("explanation") or "").strip() or "(원본 해설 없음)"
    return (
        f"[Q{q.get('number')}]\n"
        f"[과목] {q.get('subject') or ''}\n"
        f"[문제] {q.get('question') or ''}\n"
        f"[보기]\n"
        f"① {ct(0)}\n"
        f"② {ct(1)}\n"
        f"③ {ct(2)}\n"
        f"④ {ct(3)}\n"
        f"[정답] {q.get('answer', '?')}번\n"
        f"[원본 해설]\n{raw_expl}\n"
    )


def prompt_for_batch(exam_name: str, qs: list[dict],
                     taxonomy: list[dict]) -> str:
    """5문항용 프롬프트. taxonomy 는 해당 과목 후보 ID 리스트."""
    blocks = "\n\n".join(_q_block(q) for q in qs)
    qnums = [q.get("number") for q in qs]
    tax_lines = "\n".join(
        f"- {c['id']}: {c['name_ko']} [{c['subject']}]" for c in taxonomy
    )
    return f"""당신은 {exam_name} 전문 강사입니다.
아래 {len(qs)}개 기출문제 각각에 대해 (1) 학습용 해설 작성, (2) 핵심 개념 추출, (3) 사전 정의된 taxonomy ID 매핑 을 수행합니다.

────────────────────────
{blocks}
────────────────────────

사전 정의 개념 (이 ID 중에서만 매핑 — 영문 슬러그 그대로 사용):
{tax_lines}

각 문제마다 다음 작업을 수행하세요.

1) explanation_detailed 작성 — 학습자 수준에서 명료한 평문, 마크다운 기호 없이.
   형식 (섹션 제목 정확히 동일):
   핵심 개념
   - 1~2줄로 이 문제가 묻는 개념 요약
   정답 분석
   - 정답이 왜 옳은지 (2~4줄)
   오답 분석
   - ① / ② / ③ / ④ 각 1줄. 정답인 보기는 "정답" 한 단어로 표기.
   원본 해설이 충분히 좋더라도 위 3섹션 형식으로 다시 정리해 출력.

2) concepts — 한국어 명사구 1~3개. 첫 번째가 가장 중심 개념.
   - 추상 분야명 ("안전관리", "기계공학") 금지.
   - 구체적 개념 ("최소감지전류", "프레스 광전식 방호장치") 권장.

3) concept_ids — 위 사전 정의 개념 중에서 의미적으로 가장 가까운 ID 1~3개.
   - 정확히 일치하는 게 없으면 빈 배열 [] 반환 (억지로 매핑 금지).
   - taxonomy 에 없는 새 ID 생성 금지 — 위 리스트의 ID 만 사용.
   - 가장 적합한 ID 를 첫 번째에 배치.

출력은 다른 텍스트·코드펜스 없이 **JSON 객체 하나** 만. results 키에 입력 순서대로 (Q번호 포함):

{{"results": [
  {{"qnum": {qnums[0]},
    "explanation_detailed": "핵심 개념\\n- ...\\n\\n정답 분석\\n- ...\\n\\n오답 분석\\n- ① ...\\n- ② ...\\n- ③ ...\\n- ④ ...",
    "concepts": ["...", "..."],
    "concept_ids": ["concept-id-1", "concept-id-2"]
  }},
  ...
]}}

규칙:
- results 배열 길이는 정확히 {len(qs)} 이며, qnum 은 {qnums} 와 1:1 대응.
- explanation_detailed 안의 줄바꿈은 반드시 \\n 으로 이스케이프.
- JSON 외 텍스트/주석/펜스 절대 금지.
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
        raise ValueError(f"no JSON found: {text[:200]!r}")
    return json.loads(m.group(0))


def call_claude(prompt: str, *, max_retries: int = 3) -> str:
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            r = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
            )
            if r.returncode != 0:
                raise RuntimeError(
                    f"claude failed (rc={r.returncode}): "
                    f"{r.stderr.strip()[:200]}"
                )
            out = r.stdout.strip()
            if not out:
                raise RuntimeError("claude returned empty output")
            return out
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            last_err = e
            if attempt < max_retries:
                wait = 30 * attempt
                print(f"  ⚠ claude attempt {attempt}/{max_retries} 실패 "
                      f"({type(e).__name__}: {str(e)[:80]}) → {wait}s 대기",
                      flush=True)
                time.sleep(wait)
                continue
            raise
    raise last_err  # type: ignore[misc]


_SECTIONS = ["핵심 개념", "정답 분석", "오답 분석"]


def normalize_record(rec: dict, valid_ids: set[str]) -> dict:
    """모델 응답 검증 + 표준 형태로 정리."""
    ed = (rec.get("explanation_detailed") or "").strip()
    if len(ed) < 100:
        raise ValueError(f"explanation_detailed too short: {len(ed)} chars")
    missing_sections = [s for s in _SECTIONS if s not in ed]
    if missing_sections:
        raise ValueError(f"sections missing: {missing_sections}")

    concepts = rec.get("concepts") or []
    if not isinstance(concepts, list) or not concepts:
        raise ValueError("concepts must be non-empty list")
    concepts = [str(c).strip() for c in concepts if str(c).strip()][:3]
    if not concepts:
        raise ValueError("concepts empty after strip")

    cids_raw = rec.get("concept_ids") or []
    if not isinstance(cids_raw, list):
        raise ValueError("concept_ids must be list")
    cids: list[str] = []
    for cid in cids_raw[:3]:
        s = str(cid).strip()
        if not s:
            continue
        if s not in valid_ids:
            # 모델이 taxonomy 외 ID 만들었음 → 조용히 무시 (concepts 만 신뢰)
            continue
        if s not in cids:
            cids.append(s)
    return {
        "explanation_detailed": ed,
        "concepts": concepts,
        "concept_ids": cids,
    }


def apply_record(q: dict, rec: dict) -> None:
    q["explanation_detailed"] = rec["explanation_detailed"]
    q["concepts"] = rec["concepts"]
    q["concept_ids"] = rec["concept_ids"]


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


def question_done(q: dict) -> bool:
    return bool(
        q.get("explanation_detailed") and q.get("concepts")
        and "concept_ids" in q
    )


def session_already_done(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return all(question_done(q) for q in d["questions"])
    except Exception:
        return False


def chunked(lst: list, n: int) -> list[list]:
    return [lst[i:i + n] for i in range(0, len(lst), n)]


def process_session(exam_code: str, session_code: str, taxonomy: list[dict],
                    *, limit: int | None = None, dry: bool = False) -> dict:
    path = session_path(exam_code, session_code)
    if not path.exists():
        print(f"[{exam_code}/{session_code}] missing, skip", flush=True)
        return {"code": session_code, "done": 0, "failed": 0}
    if session_already_done(path):
        print(f"[{exam_code}/{session_code}] 전체 처리 완료, skip", flush=True)
        return {"code": session_code, "done": 0, "skip": 1}

    d = json.loads(path.read_text(encoding="utf-8"))
    todo = [q for q in d["questions"] if not question_done(q)]
    if limit is not None:
        todo = todo[:limit]
    print(f"[{exam_code}/{session_code}] 대상 {len(todo)} / 총 {len(d['questions'])}",
          flush=True)
    if not todo:
        return {"code": session_code, "done": 0, "skip": len(d["questions"])}

    valid_ids = {c["id"] for c in taxonomy}
    exam_name = EXAMS[exam_code]["name"]

    # 같은 과목끼리 묶어 배치 → taxonomy 후보 좁히기 (프롬프트 토큰 절약)
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for q in todo:
        by_subject[normalize_subject(q.get("subject") or "")].append(q)

    n_done = 0
    n_failed = 0

    for subj, qs in by_subject.items():
        sub_tax = taxonomy_for_subject(taxonomy, subj)
        for batch in chunked(qs, BATCH_SIZE):
            prompt = prompt_for_batch(exam_name, batch, sub_tax)
            qnums = [q["number"] for q in batch]
            if dry:
                print(prompt[:4000])
                print(f"\n... (prompt 총 {len(prompt)} 자, batch={qnums}, "
                      f"taxonomy={len(sub_tax)}) ...")
                return {"code": session_code, "dry": True}

            t0 = time.time()
            try:
                text = call_claude(prompt)
                obj = parse_response(text)
                results = obj.get("results") or []
                if len(results) != len(batch):
                    raise ValueError(
                        f"results length {len(results)} != batch {len(batch)}"
                    )
                # qnum → record 매핑
                by_q = {r.get("qnum"): r for r in results}
                norm: dict[int, dict] = {}
                for q in batch:
                    rec = by_q.get(q["number"])
                    if rec is None:
                        raise ValueError(
                            f"qnum {q['number']} missing in results"
                        )
                    norm[q["number"]] = normalize_record(rec, valid_ids)
                # 검증 통과 → 적용
                for q in batch:
                    apply_record(q, norm[q["number"]])
                n_done += len(batch)
                dt = time.time() - t0
                empty_ids = sum(1 for n in norm.values() if not n["concept_ids"])
                print(f"  Q{qnums}  ✓ ok={len(batch)} no_id={empty_ids} "
                      f"({dt:.1f}s)", flush=True)
            except Exception as e:
                n_failed += len(batch)
                dt = time.time() - t0
                print(f"  Q{qnums}  ✗ {type(e).__name__}: "
                      f"{str(e)[:120]} ({dt:.1f}s)", flush=True)

            # 배치마다 저장 (idempotent)
            path.write_text(
                json.dumps(d, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    print(f"[{session_code}] 완료 done={n_done} fail={n_failed}", flush=True)
    return {"code": session_code, "done": n_done, "failed": n_failed}


def write_outputs(exam_code: str, taxonomy: list[dict]) -> None:
    """taxonomy + 모든 question 의 concept_ids 로 aliases/index.json 산출."""
    out_dir = DATA / "concepts" / exam_code
    out_dir.mkdir(parents=True, exist_ok=True)

    # taxonomy 가 곧 canonical. raw concepts 에서 모인 phrase 들을 alias 로.
    by_id: dict[str, dict] = {}
    for c in taxonomy:
        by_id[c["id"]] = {
            "id": c["id"],
            "name_ko": c["name_ko"],
            "name_en": c.get("name_en") or "",
            "subjects": [c["subject"]],
            "members": [c["name_ko"]],
            "refs": [],
        }
    aliases: dict[str, str] = {c["name_ko"]: c["id"] for c in taxonomy}

    for sess_code in all_sessions(exam_code):
        p = session_path(exam_code, sess_code)
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for q in d["questions"]:
            for cid in q.get("concept_ids") or []:
                if cid in by_id:
                    by_id[cid]["refs"].append(
                        {"session": sess_code, "qnum": q["number"]}
                    )
            for raw in q.get("concepts") or []:
                aliases.setdefault(raw.strip(), "")

    # refs dedupe + sort + count
    for entry in by_id.values():
        seen = set()
        uniq = []
        for r in entry["refs"]:
            key = (r["session"], r["qnum"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        uniq.sort(key=lambda r: (r["session"], r["qnum"]))
        entry["refs"] = uniq
        entry["count"] = len(uniq)

    # 빈 alias (raw 인데 매핑 없는 것) 제거
    aliases = {k: v for k, v in aliases.items() if v}

    (out_dir / "aliases.json").write_text(
        json.dumps(aliases, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "index.json").write_text(
        json.dumps(by_id, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    n_used = sum(1 for e in by_id.values() if e["refs"])
    print(f"\n[write] aliases={len(aliases)}, index={len(by_id)} "
          f"(사용된 개념 {n_used}) → {out_dir}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("exam_code")
    ap.add_argument("session", nargs="?", default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="회차당 처리 문항 수 제한")
    ap.add_argument("--dry", action="store_true",
                    help="첫 배치 프롬프트만 출력하고 종료")
    args = ap.parse_args()

    if args.exam_code not in EXAMS:
        raise SystemExit(f"Unknown exam: {args.exam_code}")

    taxonomy = load_taxonomy(args.exam_code)
    print(f"taxonomy {len(taxonomy)}개 개념 로드", flush=True)

    if args.session:
        sessions = [args.session]
    else:
        sessions = all_sessions(args.exam_code)

    print(f"========== {args.exam_code} · {EXAMS[args.exam_code]['name']} "
          f"· {len(sessions)}회차 ==========", flush=True)

    t0 = time.time()
    n_done = 0
    n_fail = 0
    for sc in sessions:
        r = process_session(args.exam_code, sc, taxonomy,
                            limit=args.limit, dry=args.dry)
        if args.dry:
            return
        n_done += r.get("done", 0)
        n_fail += r.get("failed", 0)

    write_outputs(args.exam_code, taxonomy)

    dt = (time.time() - t0) / 60
    print(f"\n=== {args.exam_code} · {len(sessions)}회차 · 처리 {n_done} / "
          f"실패 {n_fail} · 소요 {dt:.1f}분 ===", flush=True)


if __name__ == "__main__":
    main()

"""개념 정규화 (A.2): raw 개념 phrase → canonical_id 매핑 + 인덱스.

extract_concepts.py 가 채운 각 question 의 `concepts[]` (raw 한국어 명사구) 들을
**과목 단위로 묶어** Claude 에게 클러스터링을 시킨다.
의미적으로 같은 개념(표기·접미어 차이) 은 한 canonical 로 합치고,
영문 슬러그 ID 와 한국어 canonical 이름을 부여한다.

산출물:
  data/concepts/{exam}/aliases.json   raw_phrase → canonical_id
  data/concepts/{exam}/index.json     canonical_id → metadata + question_refs

또한 각 question 에 concept_ids[] 필드를 추가 (raw concepts[] 는 보존).

사용법:
  python3 normalize_concepts.py iz                # iz 5과목 모두
  python3 normalize_concepts.py iz --subject 1    # 1과목만
  python3 normalize_concepts.py iz --dry          # 첫 과목 프롬프트만 출력
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


def session_files(exam_code: str) -> list[Path]:
    return sorted((DATA / exam_code).glob(f"{exam_code}_2*.json"))


def normalize_subject(s: str) -> str:
    """'1과목 : 소프트웨어 설계' → '소프트웨어 설계'"""
    s = (s or "").strip()
    m = re.match(r"^\d+\s*과목\s*[:：]\s*(.+)$", s)
    return (m.group(1) if m else s).strip()


def collect_raw(exam_code: str) -> dict[str, list[dict]]:
    """과목명 → [{phrase, refs:[{session, qnum}]}, ...]"""
    by_subject: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for f in session_files(exam_code):
        d = json.loads(f.read_text(encoding="utf-8"))
        sess = f.stem.split("_", 1)[1]
        for q in d["questions"]:
            if not q.get("concepts"):
                continue
            subj = normalize_subject(q.get("subject", ""))
            for c in q["concepts"]:
                by_subject[subj][c.strip()].append(
                    {"session": sess, "qnum": q["number"]}
                )
    out: dict[str, list[dict]] = {}
    for subj, phrases in by_subject.items():
        items = []
        for ph, refs in phrases.items():
            items.append({"phrase": ph, "count": len(refs), "refs": refs})
        items.sort(key=lambda x: (-x["count"], x["phrase"]))
        out[subj] = items
    return out


def prompt_for_subject(exam_name: str, subject: str, items: list[dict]) -> str:
    """입력 phrase 마다 1-based 인덱스를 부여 — 출력은 인덱스 배열로만 받아 토큰 절약."""
    lines = []
    for i, it in enumerate(items, start=1):
        sample = it["refs"][:3]
        sample_str = ", ".join(f"{r['session']}-Q{r['qnum']}" for r in sample)
        more = f" (+{len(it['refs']) - 3} 더)" if len(it["refs"]) > 3 else ""
        lines.append(f"{i}. ({it['count']}회) \"{it['phrase']}\" — {sample_str}{more}")
    lst = "\n".join(lines)
    last_idx = len(items)

    return f"""당신은 {exam_name} [{subject}] 과목 전문가입니다.
아래는 기출 문제에서 추출된 raw 개념 phrase 목록입니다 ({len(items)}개, 빈도순, 1-based 인덱스 부여됨).
의미적으로 같은 개념끼리 묶고, 각 묶음에 canonical 한국어 이름과 영문 slug ID 를 부여하세요.

[원칙]
1. 너무 잘게 쪼갠 변형(괄호 표기, 접미어, 띄어쓰기, 한·영 병기 차이) 은 같은 canonical 로 합칩니다.
   - 예: "워크 스루(Walk-through)", "워크스루", "워크-스루" → 하나로 묶기
2. 같은 개념의 다른 측면(예: "DFD 표기 요소" vs "DFD 4대 구성요소") 도 일반적으로 같은 canonical 로 합칩니다 (개념 단위는 너무 잘게 쪼개지 않는다).
3. 명확히 다른 개념은 분리합니다. 무리한 통합 금지.
4. canonical 한국어 이름 (name_ko) 은 가장 일반적이고 표준적인 표기를 채택. 영문 약어는 괄호로 보조 가능.
5. 영문 slug (id) 는 kebab-case, 알파벳 소문자/숫자/하이픈만, 최대 60자. 자명하지 않으면 한글 음역 대신 영문 의역.

[입력 raw 개념]
{lst}

출력은 다른 텍스트·코드펜스 없이 **JSON 한 객체** 만. members 는 위 입력 인덱스 (정수) 배열:
{{"concepts": [
  {{"id": "walkthrough-review",
    "name_ko": "워크 스루(Walk-through) 검토 기법",
    "name_en": "Walk-through Review",
    "members": [1, 7, 23]
  }},
  ...
]}}

규칙:
- members 는 1 부터 {last_idx} 사이의 정수.
- 위 1~{last_idx} 의 모든 인덱스는 정확히 하나의 canonical 의 members 에 등장해야 합니다 (누락·중복 금지).
- id 는 canonical 간 중복 금지.
- members 에 string 을 넣지 말 것 (반드시 정수).
"""


_JSON_RE = re.compile(r"\{[\s\S]*\}\s*$")


def parse_json(text: str) -> dict:
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


def call_claude(prompt: str, *, timeout: int = 1800) -> str:
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


def materialize_members(items: list[dict], result: dict) -> dict:
    """모델이 members 를 1-based int index 로 줬으면 string phrase 로 매핑.
    이미 string 이면 그대로 (legacy 캐시 호환)."""
    concepts = result.get("concepts") or []
    n = len(items)
    for c in concepts:
        members = c.get("members") or []
        new_members: list[str] = []
        for m in members:
            if isinstance(m, bool):  # bool 은 int 의 subclass라서 따로 거른다
                raise ValueError(f"bad member: {m!r}")
            if isinstance(m, int):
                if m < 1 or m > n:
                    raise ValueError(f"member index out of range 1..{n}: {m}")
                new_members.append(items[m - 1]["phrase"])
            elif isinstance(m, str):
                new_members.append(m)
            else:
                raise ValueError(f"member must be int or str: {m!r}")
        c["members"] = new_members
    return result


def validate_subject_result(items: list[dict], result: dict) -> list[dict]:
    """입력 phrase 가 빠짐없이 정확히 한 번씩 members 에 들어갔는지 검증."""
    input_set = {it["phrase"] for it in items}
    seen = {}
    concepts = result.get("concepts") or []
    if not isinstance(concepts, list) or not concepts:
        raise ValueError("concepts list missing/empty")
    ids_seen = set()
    for c in concepts:
        cid = c.get("id")
        if not cid or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", cid):
            raise ValueError(f"bad id: {cid!r}")
        if cid in ids_seen:
            raise ValueError(f"dup id: {cid}")
        ids_seen.add(cid)
        if not c.get("name_ko"):
            raise ValueError(f"{cid}: name_ko missing")
        members = c.get("members") or []
        if not members:
            raise ValueError(f"{cid}: empty members")
        for m in members:
            if m in seen:
                raise ValueError(f"phrase {m!r} in both {seen[m]} and {cid}")
            if m not in input_set:
                raise ValueError(f"{cid}: phrase {m!r} not in input")
            seen[m] = cid
    missing = input_set - seen.keys()
    if missing:
        raise ValueError(
            f"{len(missing)} phrases not assigned, e.g. {list(missing)[:3]}"
        )
    return concepts


def _safe_subject(subject: str) -> str:
    return re.sub(r"[^\w가-힣]+", "_", subject).strip("_")


def cache_path(exam_code: str, subject: str) -> Path:
    return DATA / "concepts" / exam_code / "_cache" / f"{_safe_subject(subject)}.json"


def cache_batch_path(exam_code: str, subject: str, bi: int, total: int) -> Path:
    safe = _safe_subject(subject)
    return DATA / "concepts" / exam_code / "_cache" / f"{safe}_b{bi}of{total}.json"


# 한 호출당 출력 JSON이 ~50KB 가까워지면 claude -p 가 stall 되는 경향. 안전 배치 크기.
BATCH_SIZE = 150


def chunk_items(items: list[dict], target_size: int = BATCH_SIZE) -> list[list[dict]]:
    """과목 내부 phrase 들을 표면 유사 prefix 로 묶고, target_size 근방으로 패킹.

    같은 prefix(첫 5자, 공백·괄호 제거 후 lowercase) 인 phrase 들은 같은 batch 에 배치 →
    cross-batch 중복 canonical 생성을 줄인다.
    """
    if len(items) <= target_size:
        return [items]

    def key(phrase: str) -> str:
        s = re.sub(r"[\s·\(\)\[\]/.,]+", "", phrase.lower())
        return s[:5] if s else ""

    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        groups[key(it["phrase"])].append(it)

    sorted_groups = sorted(groups.values(), key=lambda g: -len(g))
    batches: list[list[dict]] = []
    for g in sorted_groups:
        placed = False
        for b in batches:
            if len(b) + len(g) <= target_size:
                b.extend(g)
                placed = True
                break
        if not placed:
            batches.append(list(g))
    return batches


def _call_and_validate(exam_name: str, label: str,
                       items: list[dict]) -> list[dict]:
    prompt = prompt_for_subject(exam_name, label, items)
    t0 = time.time()
    text = call_claude(prompt)
    dt = time.time() - t0
    result = parse_json(text)
    materialize_members(items, result)
    concepts = validate_subject_result(items, result)
    print(f"  ✓ [{label}] {len(items)} → {len(concepts)} canonical ({dt:.1f}s)",
          flush=True)
    return concepts


def normalize_subject_call(exam_code: str, exam_name: str, subject: str,
                           items: list[dict], dry: bool,
                           refresh: bool) -> list[dict]:
    print(f"\n--- [{subject}] raw {len(items)} phrase 정규화 ---", flush=True)

    # legacy 단일파일 캐시 (chunking 도입 전 형태) — 있으면 그대로 사용
    legacy = cache_path(exam_code, subject)
    if not refresh and legacy.exists():
        cached = json.loads(legacy.read_text(encoding="utf-8"))
        try:
            concepts = validate_subject_result(items, cached)
            print(f"  ↻ cache hit (single-file) → {len(concepts)} canonical",
                  flush=True)
            return concepts
        except Exception as e:
            print(f"  ! single-file cache invalid ({e}), 배치 재생성", flush=True)

    if dry:
        prompt = prompt_for_subject(exam_name, subject, items)
        print(prompt[:4000])
        print(f"\n... (prompt 총 {len(prompt)} 자, items {len(items)}개) ...")
        return []

    batches = chunk_items(items)
    n_batches = len(batches)
    sizes = [len(b) for b in batches]
    print(f"  chunked into {n_batches} batch(es): sizes={sizes}", flush=True)

    merged: list[dict] = []
    by_id: dict[str, dict] = {}
    id_collisions = 0

    for bi, batch in enumerate(batches, 1):
        batch_cache = cache_batch_path(exam_code, subject, bi, n_batches)
        concepts: list[dict] | None = None
        if not refresh and batch_cache.exists():
            try:
                cached = json.loads(batch_cache.read_text(encoding="utf-8"))
                concepts = validate_subject_result(batch, cached)
                print(f"  ↻ batch {bi}/{n_batches} cache hit "
                      f"→ {len(concepts)} canonical", flush=True)
            except Exception as e:
                print(f"  ! batch {bi} cache invalid ({e}), 재생성", flush=True)
                concepts = None

        if concepts is None:
            label = (f"{subject} (배치 {bi}/{n_batches})" if n_batches > 1
                     else subject)
            concepts = _call_and_validate(exam_name, label, batch)
            batch_cache.parent.mkdir(parents=True, exist_ok=True)
            batch_cache.write_text(
                json.dumps({"concepts": concepts}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        for c in concepts:
            cid = c["id"]
            if cid in by_id:
                # cross-batch id 충돌: 같은 canonical 로 보고 members 합침
                existing = by_id[cid]
                for m in c["members"]:
                    if m not in existing["members"]:
                        existing["members"].append(m)
                id_collisions += 1
            else:
                cp = dict(c)
                cp["members"] = list(c["members"])
                by_id[cid] = cp
                merged.append(cp)

    if id_collisions:
        print(f"  ⓘ cross-batch id 충돌 {id_collisions}건 (자동 merge)", flush=True)

    final = validate_subject_result(items, {"concepts": merged})
    n_in = len(items); n_out = len(final)
    print(f"  ◎ [{subject}] TOTAL {n_in} → {n_out} canonical "
          f"(압축률 {(1-n_out/n_in)*100:.1f}%)", flush=True)
    return final


def write_outputs(exam_code: str,
                  by_subject_concepts: dict[str, list[dict]],
                  raw_by_subject: dict[str, list[dict]]) -> None:
    """aliases.json + index.json 산출. 같은 canonical id 가 여러 과목에서 나오면
    members·refs 를 합치고 subjects 는 리스트로 보존."""
    out_dir = DATA / "concepts" / exam_code
    out_dir.mkdir(parents=True, exist_ok=True)

    aliases: dict[str, str] = {}
    index: dict[str, dict] = {}
    merges = 0

    for subject, concepts in by_subject_concepts.items():
        ref_lookup = {it["phrase"]: it["refs"] for it in raw_by_subject[subject]}
        for c in concepts:
            cid = c["id"]
            members = list(c["members"])
            new_refs: list[dict] = []
            for m in members:
                aliases[m] = cid
                new_refs.extend(ref_lookup.get(m, []))

            if cid in index:
                # cross-subject 같은 id → 같은 canonical 로 보고 통합
                existing = index[cid]
                # members: 순서 보존 dedupe
                merged_members = list(dict.fromkeys(existing["members"] + members))
                existing["members"] = merged_members
                existing["refs"].extend(new_refs)
                if subject not in existing["subjects"]:
                    existing["subjects"].append(subject)
                merges += 1
            else:
                index[cid] = {
                    "id": cid,
                    "name_ko": c["name_ko"],
                    "name_en": c.get("name_en") or "",
                    "subjects": [subject],
                    "members": members,
                    "refs": new_refs,
                }

    # post-process: refs dedupe + sort + count
    for entry in index.values():
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

    (out_dir / "aliases.json").write_text(
        json.dumps(aliases, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[write] aliases={len(aliases)} entries, index={len(index)} canonicals"
          + (f", cross-subject merges={merges}" if merges else "")
          + f" → {out_dir}", flush=True)


def annotate_questions(exam_code: str, aliases: dict[str, str]) -> int:
    """각 question 에 concept_ids[] (canonical) 추가. raw concepts[] 보존."""
    n = 0
    for f in session_files(exam_code):
        d = json.loads(f.read_text(encoding="utf-8"))
        changed = False
        for q in d["questions"]:
            raw = q.get("concepts") or []
            if not raw:
                continue
            ids: list[str] = []
            for r in raw:
                cid = aliases.get(r.strip())
                if cid and cid not in ids:
                    ids.append(cid)
            if q.get("concept_ids") != ids:
                q["concept_ids"] = ids
                changed = True
                n += 1
        if changed:
            f.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("exam_code")
    ap.add_argument("--subject", help="과목 번호 (1~5) 또는 과목명. 생략 시 전체.")
    ap.add_argument("--dry", action="store_true", help="첫 과목 프롬프트만 출력")
    ap.add_argument("--refresh", action="store_true",
                    help="과목별 캐시 무시하고 재생성")
    args = ap.parse_args()

    if args.exam_code not in EXAMS:
        raise SystemExit(f"Unknown exam: {args.exam_code}")
    exam_name = EXAMS[args.exam_code]["name"]
    raw = collect_raw(args.exam_code)
    if not raw:
        raise SystemExit(f"raw 개념 없음. 먼저 extract_concepts.py 를 실행하세요.")

    canon_subjects = list(EXAMS[args.exam_code]["subjects"])
    # raw 에서 등장 순으로 결정 (canon_subjects 기준 정렬, 그 외는 뒤에)
    sorted_subjects = [s for s in canon_subjects if s in raw] + \
                      [s for s in raw if s not in canon_subjects]

    targets = sorted_subjects
    if args.subject:
        if args.subject.isdigit():
            i = int(args.subject) - 1
            if i < 0 or i >= len(canon_subjects):
                raise SystemExit(f"--subject 1..{len(canon_subjects)}")
            targets = [canon_subjects[i]]
        else:
            if args.subject not in raw:
                raise SystemExit(f"--subject 매칭 안 됨: {args.subject!r}")
            targets = [args.subject]

    by_subject_concepts: dict[str, list[dict]] = {}
    for subj in targets:
        items = raw.get(subj) or []
        if not items:
            print(f"[skip] {subj}: items 0")
            continue
        concepts = normalize_subject_call(
            args.exam_code, exam_name, subj, items, args.dry, args.refresh,
        )
        if not args.dry:
            by_subject_concepts[subj] = concepts

    if args.dry:
        return

    if not by_subject_concepts:
        print("정규화 결과 없음, 종료")
        return

    write_outputs(args.exam_code, by_subject_concepts, raw)
    aliases = json.loads(
        (DATA / "concepts" / args.exam_code / "aliases.json").read_text("utf-8")
    )
    n = annotate_questions(args.exam_code, aliases)
    print(f"[annotate] {n} questions updated with concept_ids[]")


if __name__ == "__main__":
    main()

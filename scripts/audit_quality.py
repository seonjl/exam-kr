"""AI 생성 콘텐츠 품질 자동 진단 (A1~A9).

산출:
  data/audit/{exam}.json   — 문항/개념 단위 이슈 raw 리스트
  data/audit/SUMMARY.md    — 사람이 읽는 요약

사용:
  python3 scripts/audit_quality.py            # 4개 자격증 전부
  python3 scripts/audit_quality.py s2 g1      # 일부만
"""
from __future__ import annotations
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"

EXAMS = ["s2", "g1", "g2", "iz"]
SECTIONS = ("핵심 개념", "정답 분석", "오답 분석")
CIRCLED = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
INV_CIRCLED = {v: k for k, v in CIRCLED.items()}
# 본문에 이미지/자료가 있어야 함을 시사하는 표현
NEEDS_VISUAL = re.compile(
    r"(다음\s*(그림|표|자료|보기|도표|지도|그래프)|아래\s*(그림|표|자료)"
    r"|<\s*그림\s*>|<\s*표\s*>|\[\s*그림\s*\]|\[\s*표\s*\])"
)
URL_RE = re.compile(r"^https?://[\w.\-]+/.+\.(gif|png|jpg|jpeg|webp)(\?.*)?$", re.I)


def load_exam(exam: str) -> list[tuple[Path, dict]]:
    files = sorted((DATA / exam).glob(f"{exam}_*.json"))
    return [(f, json.loads(f.read_text(encoding="utf-8"))) for f in files]


def load_concepts(exam: str) -> tuple[dict, dict] | tuple[None, None]:
    cdir = DATA / "concepts" / exam
    idx_p, al_p = cdir / "index.json", cdir / "aliases.json"
    if not idx_p.exists():
        return None, None
    return json.loads(idx_p.read_text("utf-8")), json.loads(al_p.read_text("utf-8"))


def split_sections(text: str) -> dict[str, str]:
    """explanation_detailed 를 섹션별로 분리. 누락된 섹션은 빈 문자열."""
    out = {s: "" for s in SECTIONS}
    if not text:
        return out
    # 각 섹션 헤더 위치 탐색
    positions = []
    for s in SECTIONS:
        m = re.search(rf"^\s*{re.escape(s)}\s*$", text, re.M)
        if m:
            positions.append((m.start(), m.end(), s))
    positions.sort()
    for i, (_, end, s) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        out[s] = text[end:nxt].strip()
    return out


def find_referenced_numbers(text: str, n_choices: int) -> set[int]:
    """텍스트에서 거론된 선택지 번호 추출 (①~⑤, (N), N번, 정답은 N)."""
    nums: set[int] = set()
    for ch, n in CIRCLED.items():
        if n <= n_choices and ch in text:
            nums.add(n)
    # (1), (2), ..., (5) - 선택지 번호 표기
    for m in re.finditer(r"\(([1-5])\)", text):
        n = int(m.group(1))
        if n <= n_choices:
            nums.add(n)
    # N번 표기
    for m in re.finditer(r"([1-5])\s*번", text):
        n = int(m.group(1))
        if n <= n_choices:
            nums.add(n)
    return nums


# 결론 패턴 — digit 매칭은 반드시 "번" 동반 필요 (false positive 방지: "3개 회사", "4층" 등)
_CONCLUSION_PATTERNS = [
    (re.compile(r"정답[은이]\s*([①②③④⑤])"), "circled"),
    (re.compile(r"정답[은이]\s*([1-5])\s*번"), "digit"),
    (re.compile(r"([①②③④⑤])(?:번)?[이가은]\s*정답"), "circled"),
    (re.compile(r"([1-5])\s*번[이가은]\s*정답"), "digit"),
    (re.compile(r"([①②③④⑤])(?:번)?[이가]\s*정답\s*(?:으로\s*)?처리"), "circled"),
    (re.compile(r"([1-5])\s*번[이가]\s*정답\s*(?:으로\s*)?처리"), "digit"),
    (re.compile(r"따라서\s*정답[은이]?\s*([①②③④⑤])"), "circled"),
    (re.compile(r"따라서\s*정답[은이]?\s*([1-5])\s*번"), "digit"),
]

_KNOWN_ERROR_MARKERS = re.compile(
    r"(오류\s*신고|문제\s*오류|모두\s*정답\s*처리|복수\s*정답|정답\s*없음|출제\s*오류)"
)


def extract_conclusion(text: str, n_choices: int) -> dict:
    """정답 분석 섹션에서 AI 결론을 추출.

    반환: {final, all_mentions[(pos,num)], unique_nums, status}
    status:
      - "no_conclusion": 결론 패턴 0건
      - "single": 단일 번호만 결론으로 거론
      - "multi": 여러 번호가 결론 패턴에 등장 (혼선)
    """
    matches: list[tuple[int, int]] = []
    for pat, kind in _CONCLUSION_PATTERNS:
        for m in pat.finditer(text):
            g = m.group(1)
            n = CIRCLED[g] if kind == "circled" else int(g)
            if 1 <= n <= n_choices:
                matches.append((m.start(), n))
    if not matches:
        return {"final": None, "all_mentions": [], "unique_nums": [], "status": "no_conclusion"}
    matches.sort()
    nums = sorted({n for _, n in matches})
    return {
        "final": matches[-1][1],
        "all_mentions": matches,
        "unique_nums": nums,
        "status": "single" if len(nums) == 1 else "multi",
    }


def audit_question(q: dict, file_label: str, idx: dict | None) -> list[dict]:
    issues: list[dict] = []
    qid = f"{file_label}#{q.get('number')}"
    # known_defect 마킹된 문항은 audit 제외 (이미 확인된 데이터 결함)
    if q.get("known_defect"):
        return issues
    n_choices = len(q.get("choices", []))
    answer = q.get("answer")
    detailed = q.get("explanation_detailed", "") or ""
    secs = split_sections(detailed)

    # A1: 섹션 구조
    missing_secs = [s for s in SECTIONS if not secs[s]]
    if not detailed.strip():
        issues.append({"qid": qid, "code": "A1.empty", "msg": "explanation_detailed 비어있음"})
    elif missing_secs:
        issues.append({"qid": qid, "code": "A1.missing_sections", "missing": missing_secs})

    # A2: 정답 분석 결론 == answer
    if secs["정답 분석"] and isinstance(answer, int) and 1 <= answer <= n_choices:
        scan_text = secs["정답 분석"] + "\n" + secs.get("오답 분석", "")
        conc = extract_conclusion(scan_text, n_choices)
        qtext = q.get("question") or ""
        known_error = bool(_KNOWN_ERROR_MARKERS.search(qtext) or _KNOWN_ERROR_MARKERS.search(detailed))
        if conc["status"] == "no_conclusion":
            issues.append({"qid": qid, "code": "A2.no_conclusion"})
        elif conc["final"] != answer:
            base = "A2.multi_mismatch" if conc["status"] == "multi" else "A2.mismatch"
            code = base + (".known" if known_error else ".new")
            issues.append({
                "qid": qid, "code": code,
                "answer_field": answer,
                "ai_final": conc["final"],
                "ai_unique": conc["unique_nums"],
                "known_error": known_error,
            })

    # A3: 오답 분석이 정답 외 모든 번호 커버
    if secs["오답 분석"] and isinstance(answer, int) and n_choices >= 2:
        refs = find_referenced_numbers(secs["오답 분석"], n_choices)
        expected = set(range(1, n_choices + 1)) - {answer}
        miss = expected - refs
        if miss:
            issues.append({
                "qid": qid, "code": "A3.incomplete_distractors",
                "missing": sorted(miss),
            })

    # A4: concept_ids 가 index 에 존재
    if idx is not None:
        for cid in q.get("concept_ids") or []:
            if cid not in idx:
                issues.append({"qid": qid, "code": "A4.unknown_concept_id", "id": cid})

    # A7: 이미지 URL 형식
    for url in q.get("question_images") or []:
        if not URL_RE.match(url):
            issues.append({"qid": qid, "code": "A7.bad_url", "where": "question", "url": url})
    for ci, c in enumerate(q.get("choices") or []):
        for url in c.get("images") or []:
            if not URL_RE.match(url):
                issues.append({
                    "qid": qid, "code": "A7.bad_url",
                    "where": f"choice[{ci}]", "url": url,
                })

    # A8: 시각자료를 시사하는 표현 있는데 첨부 없음
    qtext = q.get("question") or ""
    if NEEDS_VISUAL.search(qtext) and not (q.get("question_images") or any(c.get("images") for c in q.get("choices") or [])):
        # 데이터가 텍스트로 임베딩된 케이스는 제외 (audit_a8.py heuristic 동일)
        digit_runs = len(re.findall(r"\d{2,}", qtext))
        if digit_runs < 5:
            issues.append({"qid": qid, "code": "A8.visual_implied_but_missing"})

    return issues


def audit_concepts(idx: dict, all_questions: list[dict]) -> dict:
    """A5, A6: 클러스터 크기 분포 + subject 혼합."""
    sizes = []
    big = []        # members 25개 이상
    singletons = 0
    mixed_subjects = []   # subjects > 1
    # subject lookup: 정규화 단계에서 index.json 의 subjects 필드 사용
    for cid, info in idx.items():
        members = info.get("members") or []
        sizes.append(len(members))
        if len(members) == 1:
            singletons += 1
        if len(members) >= 25:
            big.append({"id": cid, "name": info.get("name_ko"), "size": len(members)})
        subs = info.get("subjects") or []
        if len(subs) > 1:
            mixed_subjects.append({"id": cid, "name": info.get("name_ko"), "subjects": subs, "size": len(members)})
    sizes.sort()
    n = len(sizes)
    return {
        "total_canonicals": n,
        "total_members": sum(sizes),
        "singleton_count": singletons,
        "singleton_ratio": round(singletons / n, 3) if n else 0,
        "p50_size": sizes[n // 2] if n else 0,
        "p90_size": sizes[int(n * 0.9)] if n else 0,
        "max_size": sizes[-1] if n else 0,
        "big_clusters_top10": sorted(big, key=lambda x: -x["size"])[:10],
        "mixed_subject_count": len(mixed_subjects),
        "mixed_subject_top10": sorted(mixed_subjects, key=lambda x: -x["size"])[:10],
    }


def audit_audit_field(all_questions: list[dict]) -> dict:
    score_dist = Counter()
    improved = 0
    no_audit = 0
    for q in all_questions:
        a = q.get("explanation_audit")
        if not a:
            no_audit += 1
            continue
        score_dist[a.get("score")] += 1
        if a.get("improved"):
            improved += 1
    total = len(all_questions)
    return {
        "total_questions": total,
        "no_audit": no_audit,
        "score_distribution": dict(sorted(score_dist.items(), key=lambda x: (x[0] is None, x[0]))),
        "improved_count": improved,
        "improved_ratio": round(improved / total, 3) if total else 0,
    }


def audit_exam(exam: str) -> dict:
    files = load_exam(exam)
    idx, _aliases = load_concepts(exam)

    all_q: list[dict] = []
    issues: list[dict] = []
    for path, doc in files:
        label = path.stem  # e.g. s2_20000312
        for q in doc["questions"]:
            all_q.append(q)
            issues.extend(audit_question(q, label, idx))

    by_code = Counter(i["code"] for i in issues)
    report = {
        "exam": exam,
        "files": len(files),
        "questions": len(all_q),
        "issue_total": len(issues),
        "issues_by_code": dict(by_code.most_common()),
        "audit_field": audit_audit_field(all_q),
        "concepts": audit_concepts(idx, all_q) if idx else None,
        "issues": issues,
    }
    return report


def write_summary(reports: dict[str, dict]) -> str:
    lines = ["# AI 콘텐츠 품질 진단 요약", ""]
    lines.append("| Exam | 문항 | A2.new | A2.known | A2.multi.new | A2.multi.known | A1 | A3 | A8 |")
    lines.append("|------|------|--------|----------|--------------|----------------|----|----|----|")
    for exam, r in reports.items():
        c = r["issues_by_code"]
        a1 = c.get("A1.empty", 0) + c.get("A1.missing_sections", 0)
        a2_new = c.get("A2.mismatch.new", 0)
        a2_known = c.get("A2.mismatch.known", 0)
        a2m_new = c.get("A2.multi_mismatch.new", 0)
        a2m_known = c.get("A2.multi_mismatch.known", 0)
        a3 = c.get("A3.incomplete_distractors", 0)
        a8 = c.get("A8.visual_implied_but_missing", 0)
        lines.append(f"| {exam} | {r['questions']} | {a2_new} | {a2_known} | {a2m_new} | {a2m_known} | {a1} | {a3} | {a8} |")
    lines += ["", "## 검사 항목", ""]
    lines += [
        "- **A1** explanation_detailed 섹션 누락 (핵심 개념/정답 분석/오답 분석)",
        "- **A2.mismatch** AI 결론(단일)과 `answer` 불일치 — 가장 신뢰할 수 있는 후보",
        "- **A2.multi** 결론 표현에 여러 번호 등장 (혼선) — 실제 결론을 사람이 봐야 함",
        "- **A2.no_conc** 정답 분석에서 결론 표현을 찾지 못함",
        "- **A3** 오답 분석이 정답 외 선택지 일부를 다루지 않음",
        "- **A4** `concept_ids[]` 가 index.json 에 없음",
        "- **A7** 이미지 URL 형식 비정상",
        "- **A8** 본문이 시각자료를 시사하지만 첨부 이미지 없음",
        "",
        "## explanation_audit 점수 분포",
        "",
    ]
    for exam, r in reports.items():
        af = r["audit_field"]
        lines.append(f"### {exam}")
        lines.append(f"- 총 {af['total_questions']} / audit 없음 {af['no_audit']} / improved {af['improved_count']} ({af['improved_ratio']*100:.1f}%)")
        dist = " ".join(f"{k}={v}" for k, v in af["score_distribution"].items())
        lines.append(f"- score: {dist}")
        lines.append("")
    lines.append("## 개념 정규화 (A5/A6)")
    lines.append("")
    lines.append("| Exam | canonical | singleton | p50 | p90 | max | mixed-subj |")
    lines.append("|------|-----------|-----------|-----|-----|-----|------------|")
    for exam, r in reports.items():
        c = r.get("concepts")
        if not c:
            lines.append(f"| {exam} | - | - | - | - | - | - |")
            continue
        lines.append(
            f"| {exam} | {c['total_canonicals']} | {c['singleton_count']} ({c['singleton_ratio']*100:.0f}%) | "
            f"{c['p50_size']} | {c['p90_size']} | {c['max_size']} | {c['mixed_subject_count']} |"
        )
    lines += ["", "### 거대 클러스터 Top (과병합 의심)", ""]
    for exam, r in reports.items():
        c = r.get("concepts")
        if not c:
            continue
        if not c["big_clusters_top10"]:
            continue
        lines.append(f"**{exam}**")
        for b in c["big_clusters_top10"][:5]:
            lines.append(f"- `{b['id']}` ({b['size']} members) — {b['name']}")
        lines.append("")
    return "\n".join(lines)


def main():
    targets = sys.argv[1:] or EXAMS
    OUT.mkdir(parents=True, exist_ok=True)
    reports = {}
    for exam in targets:
        print(f"[audit] {exam} ...", flush=True)
        r = audit_exam(exam)
        reports[exam] = r
        (OUT / f"{exam}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  questions={r['questions']} issues={r['issue_total']}")
    (OUT / "SUMMARY.md").write_text(write_summary(reports), encoding="utf-8")
    print(f"\n→ {OUT}/SUMMARY.md")


if __name__ == "__main__":
    main()

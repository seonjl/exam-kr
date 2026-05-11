"""기출 데이터 수집 스크립트 (범용).

scripts/exams.py의 EXAMS 테이블을 참조하여 동작한다.

사용법:
  python3 fetch.py <code> list                 # 해당 자격증 회차 목록
  python3 fetch.py <code> fetch <YYYYMMDD>     # 단일 회차 JSON 저장
  python3 fetch.py <code> fetch-all            # 전체 회차 순회
  python3 fetch.py <code> manifest             # data/<code>/sessions.json 재생성
  python3 fetch.py all-exams fetch-all         # 모든 자격증 전체

예:
  python3 fetch.py g1 fetch-all
  python3 fetch.py s2 list
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from html import unescape
from pathlib import Path
from urllib.parse import urlencode

import urllib.request

sys.path.insert(0, str(Path(__file__).parent))
from exams import EXAMS  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120"
# 데이터 소스 base URL은 환경변수로만 주입한다. 하드코딩 금지.
BASE = os.environ.get("FETCH_BASE_URL", "").rstrip("/")
DATA_ROOT = Path(__file__).parent.parent / "data"
DATA_ROOT.mkdir(exist_ok=True)


def _require_base() -> None:
    if not BASE:
        raise SystemExit(
            "FETCH_BASE_URL 환경변수가 필요합니다. "
            "예: FETCH_BASE_URL='https://example.com/path' python3 fetch.py ..."
        )


def _req(url: str, data: bytes | None = None, referer: str | None = None,
         *, retries: int = 5) -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data,
                                         method="POST" if data else "GET")
            req.add_header("User-Agent", UA)
            req.add_header("Accept", "text/html,*/*;q=0.8")
            if referer:
                req.add_header("Referer", referer)
            if data:
                req.add_header("Content-Type",
                               "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            return raw.decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            wait = min(30, 2 ** i)
            print(f"  [retry {i+1}/{retries}] {type(e).__name__}: {e}; "
                  f"sleeping {wait}s", flush=True)
            time.sleep(wait)
    raise last or RuntimeError("request failed")


def cfg(code: str) -> dict:
    if code not in EXAMS:
        raise SystemExit(f"Unknown exam code: {code}. See scripts/exams.py")
    return EXAMS[code]


def out_dir(code: str) -> Path:
    d = DATA_ROOT / code
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dbname(code: str) -> str:
    """comcbt 사이트의 dbname. EXAMS 에 'dbname' 명시 없으면 exam code 그대로."""
    return cfg(code).get("dbname", code)


def list_sessions(code: str) -> list[tuple[str, str]]:
    _require_base()
    c = cfg(code)
    body = _req(f"{BASE}/s_view2.php",
                data=urlencode({"dbname": _dbname(code),
                                "hack_number": c["hack"]}).encode(),
                referer=f"{BASE}/s_view1.php")
    rows = re.findall(r"<option\s+value\s*=\s*(\d{8})\s*>([^<]+)</option>", body)
    seen, out = set(), []
    for code_, label in rows:
        if code_ in seen:
            continue
        seen.add(code_)
        out.append((code_, label.strip()))
    return out


def _fetch_one(code: str, date: str, number: int) -> str:
    _require_base()
    c = cfg(code)
    db = _dbname(code)
    qs = urlencode({
        "dbname": db, "tablename": date, "tablename2": date,
        "number": number, "mode": "mode2",
        "jd": 0, "jumsu": 0, "odabnumber": "", "jungdabnumber": "",
        "start_time": 0, "end_time": 0, "check": 0,
        "hack_number": c["hack"], "mo": 0, "gichul_number": -2,
        "yearmoradio": "", "h_db": db,
        **c["parts"],
    })
    return _req(f"{BASE}/s_view3_in.php?{qs}",
                referer=f"{BASE}/s_view3_main.php")


_END_RE = re.compile(r"모든 문제를 다 풀었습니다")


def _clean(node: str) -> str:
    s = re.sub(r"<script.*?</script>", "", node, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", "", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</?(p|div|li|tr|td|table|font|b|span|center)[^>]*>",
               "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _extract_images(node: str, base: str = "https:") -> list[str]:
    out = []
    for m in re.finditer(r'<img[^>]*src=["\']([^"\']+)', node):
        src = m.group(1)
        if src.startswith("//"):
            src = base + src
        out.append(src)
    return out


_SUBJ_RE = re.compile(r"(\d+과목\s*:\s*[^<]+?)</")


def parse_question(html: str, number: int, *, img_base: str = "https:") -> dict | None:
    if _END_RE.search(html):
        return None
    body = html.split("</head>", 1)[-1]

    subj_m = _SUBJ_RE.search(body)
    subject = subj_m.group(1).strip() if subj_m else ""

    stem_m = re.search(
        rf'<b[^>]*>\s*{number}\.\s*(?P<q>.+?)</b>\s*'
        rf'(?:<font[^>]*>)*\s*(?:\(정답률:(?P<rate>\d+)%\))?',
        body, re.S)
    if not stem_m:
        return None
    stem_html = stem_m.group("q")
    stem_text = _clean(stem_html)
    pass_rate = int(stem_m.group("rate")) if stem_m.group("rate") else None

    bigi1_form = re.search(
        r"<FORM\b[^>]*name=['\"]?bigi_form_1['\"]?[^>]*>",
        body, re.I)
    stim_end = bigi1_form.start() if bigi1_form else len(body)
    stim_region = body[stem_m.end():stim_end]
    stem_imgs = _extract_images(stem_html, img_base) + _extract_images(stim_region, img_base)
    stim_text = _clean(re.sub(r'<img[^>]*>', '', stim_region))
    if stim_text:
        extra = "\n".join(
            ln for ln in stim_text.splitlines()
            if ln.strip()
            and not re.match(r'^\(정답률:\d+%\)\s*$', ln.strip())
        ).strip()
        if extra:
            stem_text = f"{stem_text}\n\n{extra}".strip()

    # 5지선다 지원 — 먼저 form 존재 범위를 탐지하여 max 결정
    max_choice = 4
    for i in (5,):
        if re.search(rf"name=['\"]?bigi_form_{i}['\"]", body, re.I):
            max_choice = i
    choices = []
    for i in range(1, max_choice + 1):
        cm = re.search(
            rf"name=['\"]?bigi_form_{i}['\"]?.*?</form>\s*</td>\s*"
            rf"<td[^>]*align=['\"]?left['\"]?[^>]*>(.*?)</td>",
            body, re.S | re.I)
        if not cm:
            choices.append({"text": "", "images": []})
            continue
        chunk = cm.group(1)
        choices.append({
            "text": _clean(chunk),
            "images": _extract_images(chunk, img_base),
        })

    ans_m = re.search(r"id=['\"]?jungdabcolor(\d+)['\"]?[^>]*>\s*(\d+)", body)
    if ans_m:
        answer = int(ans_m.group(2))
    else:
        m2 = re.search(r"정답\s*:\s*\[\s*(\d+)\s*\]", body)
        answer = int(m2.group(1)) if m2 else None

    expl_m = re.search(r"문제\s*해설", body)
    explanation_text = ""
    explanation_images: list[str] = []
    if expl_m:
        tail = body[expl_m.end():]
        tail = re.split(r"밀양금성컴퓨터학원", tail, maxsplit=1)[0]
        explanation_text = _clean(tail)
        explanation_images = _extract_images(tail, img_base)

    return {
        "number": number,
        "subject": subject,
        "question": stem_text,
        "question_images": stem_imgs,
        "pass_rate": pass_rate,
        "choices": choices,
        "answer": answer,
        "explanation": explanation_text,
        "explanation_images": explanation_images,
    }


def fetch_session(code: str, date: str, label: str = "", *,
                  max_q: int = 250, delay: float = 0.4) -> dict:
    items: list[dict] = []
    for n in range(1, max_q + 1):
        html = _fetch_one(code, date, n)
        parsed = parse_question(html, n)
        if parsed is None:
            break
        items.append(parsed)
        time.sleep(delay)
    current = ""
    for q in items:
        if q["subject"]:
            current = q["subject"]
        else:
            q["subject"] = current
    return {
        "exam": EXAMS[code]["name"],
        "dbname": code,
        "date": date,
        "label": label,
        "count": len(items),
        "questions": items,
    }


def _session_path(code: str, date: str) -> Path:
    return out_dir(code) / f"{code}_{date}.json"


def _manifest_path(code: str) -> Path:
    return out_dir(code) / "sessions.json"


def _write_manifest(code: str, sessions: list[tuple[str, str]]) -> None:
    index = []
    for c_, label in sessions:
        path = _session_path(code, c_)
        count = 0
        if path.exists():
            try:
                count = json.loads(path.read_text(encoding="utf-8"))["count"]
            except Exception:
                count = 0
        y, m, d = c_[:4], c_[4:6], c_[6:8]
        index.append({
            "code": c_,
            "date": f"{y}-{m}-{d}",
            "year": int(y),
            "label": label,
            "count": count,
            "file": f"{code}_{c_}.json",
        })
    _manifest_path(code).write_text(
        json.dumps({
            "exam": EXAMS[code]["name"],
            "dbname": code,
            "subjects": EXAMS[code]["subjects"],
            "sessions": index,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {_manifest_path(code)} ({len(index)} sessions)")


def _write_top_manifest() -> None:
    """Write data/exams.json listing every exam with its session index file."""
    all_exams = []
    for code, c in EXAMS.items():
        mani = _manifest_path(code)
        if not mani.exists():
            continue
        j = json.loads(mani.read_text(encoding="utf-8"))
        total_q = sum(s.get("count", 0) for s in j["sessions"])
        all_exams.append({
            "code": code,
            "name": c["name"],
            "subjects": c["subjects"],
            "sessions": len(j["sessions"]),
            "questions": total_q,
            "manifest": f"{code}/sessions.json",
        })
    (DATA_ROOT / "exams.json").write_text(
        json.dumps({"exams": all_exams}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {DATA_ROOT / 'exams.json'} ({len(all_exams)} exams)")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(1)

    # Special: fetch-all across all exams
    if args[0] == "all-exams":
        cmd = args[1] if len(args) > 1 else "fetch-all"
        for code in EXAMS:
            print(f"\n========== {code} : {EXAMS[code]['name']} ==========")
            sys.argv = ["fetch.py", code, cmd]
            try:
                main()
            except SystemExit:
                pass
        _write_top_manifest()
        return

    code = args[0]
    cmd = args[1] if len(args) > 1 else "list"
    _ = cfg(code)

    if cmd == "list":
        for c_, label in list_sessions(code):
            print(f"{c_}\t{label}")
        return

    if cmd == "fetch":
        date = args[2]
        label_map = dict(list_sessions(code))
        data = fetch_session(code, date, label_map.get(date, ""))
        path = _session_path(code, date)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"{path} ({data['count']} questions)")
        return

    if cmd == "fetch-all":
        sessions = list_sessions(code)
        for c_, label in sessions:
            path = _session_path(code, c_)
            if path.exists():
                print(f"skip {c_}")
                continue
            data = fetch_session(code, c_, label, delay=0.3)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            print(f"{path} ({data['count']} questions)", flush=True)
        _write_manifest(code, sessions)
        _write_top_manifest()
        return

    if cmd == "manifest":
        _write_manifest(code, list_sessions(code))
        _write_top_manifest()
        return

    print(__doc__)


if __name__ == "__main__":
    main()

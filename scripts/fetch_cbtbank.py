#!/usr/bin/env python3
"""cbtbank.kr 기출문제 수집 → 우리 스키마 JSON.

저작권: 공개 콘텐츠인 문제·보기·공식 정답만 수집한다.
cbtbank 자체 AI 해설(.reply)·플랫폼 안내문은 수집하지 않는다. 해설은 우리 enrich 로 생성.

정답은 `<ol class="circlednumbers" correct="K">` 의 correct 속성(1-based).
과목 헤더: `<p class="text-center text-dark">N과목: NAME`.

사용법:
  python3 fetch_cbtbank.py sw            # 사회복지사1급 전 회차
  python3 fetch_cbtbank.py sw --date 20250111
"""
from __future__ import annotations
import argparse
import json
import re
import ssl
import time
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# 자격증 정의: code → {name, 교시 prefix 목록, 회차 카테고리}
EXAMS = {
    "sw": {
        "name": "사회복지사 1급",
        # (교시 prefix, 카테고리명) — 회차 코드는 prefix+YYYYMMDD
        "periods": [
            ("f1", "사회복지사-1급(1교시)"),
            ("f2", "사회복지사-1급(2교시)"),
            ("f3", "사회복지사-1급(3교시)"),
        ],
    },
}


def fetch(url: str, retries: int = 3) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch 실패 {url}: {last}")


def list_dates(periods) -> list[str]:
    """카테고리 페이지에서 회차 날짜(YYYYMMDD) 목록 수집 (1교시 기준)."""
    import urllib.parse
    _, cat = periods[0]
    html = fetch("https://cbtbank.kr/category/" + urllib.parse.quote(cat))
    codes = sorted(set(re.findall(r"/exam/([a-z0-9]+)", html)))
    dates = sorted({c[2:] for c in codes if re.match(r"^f\d\d{8}$", c)})
    return dates


def parse_exam(html: str) -> list[dict]:
    """exam 페이지 HTML → [{subject, number, question, choices, answer, images...}]."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    current_subject = ""
    # 문서 순서로 과목 헤더와 exam-box 를 순회
    for el in soup.find_all(["p", "div"]):
        cls = el.get("class") or []
        txt = el.get_text(" ", strip=True)
        if el.name == "p" and "text-center" in cls and re.match(r"\d+과목\s*:", txt):
            # "N과목: NAME" → 깨끗한 과목명 (교시별 번호 중복이라 prefix 제거, 공백 정리)
            name = re.sub(r"^\d+과목\s*:\s*", "", txt)
            current_subject = re.sub(r"\s+", "", name).strip()
            continue
        if el.name == "div" and "exam-box" in cls:
            q = parse_box(el, current_subject)
            if q:
                out.append(q)
    return out


def parse_box(box, subject: str) -> dict | None:
    title = box.find("p", class_="exam-title")
    ol = box.find("ol", class_="circlednumbers")
    if not title or not ol:
        return None
    # AI 해설(.reply) 등 비문항 영역 제거 안전장치: title/ol 만 사용
    # 문제 텍스트 (앞의 번호 span 제거)
    num_span = title.find("span", class_="exam-number")
    qnum = None
    if num_span:
        try:
            qnum = int(num_span.get_text(strip=True))
        except ValueError:
            qnum = None
        num_span.extract()
    qtext = title.get_text(" ", strip=True)
    qtext = re.sub(r"^\.\s*", "", qtext).strip()
    q_imgs = content_imgs(title)

    choices = []
    for li in ol.find_all("li", recursive=False):
        choices.append({"text": li.get_text(" ", strip=True), "images": content_imgs(li)})

    answer = None
    if ol.get("correct"):
        try:
            answer = int(ol["correct"])
        except ValueError:
            answer = None
    # 정답률
    pr = box.find("span", class_="exam-cpercent")
    pass_rate = None
    if pr:
        m = re.search(r"(\d+)", pr.get_text())
        if m:
            pass_rate = int(m.group(1))

    q = {
        "number": box.get("question-num") or qnum,
        "subject": subject,
        "question": qtext,
        "choices": choices,
        "answer": answer,
    }
    if q_imgs:
        q["question_images"] = q_imgs
    if pass_rate is not None:
        q["pass_rate"] = pass_rate
    return q


def content_imgs(el) -> list[str]:
    """문항 콘텐츠 이미지만 (SNS/프로필/아이콘 제외)."""
    res = []
    for img in el.find_all("img"):
        src = img.get("src") or ""
        if any(x in src for x in ["member_image", "no_profile", "sns_share", "/img/", "icon"]):
            continue
        if src.startswith("/"):  # cbtbank 상대경로 → 절대 URL
            src = "https://cbtbank.kr" + src
        res.append(src)
    return res


def build_exam(code: str, only_date: str | None = None) -> None:
    spec = EXAMS[code]
    dates = list_dates(spec["periods"])
    if only_date:
        dates = [d for d in dates if d == only_date]
    print(f"[{code}] {spec['name']} — {len(dates)}회차", flush=True)
    outdir = DATA / code
    outdir.mkdir(exist_ok=True)
    sessions = []
    for date in dates:
        questions = []
        n = 0
        for prefix, _cat in spec["periods"]:
            url = f"https://cbtbank.kr/exam/{prefix}{date}"
            try:
                qs = parse_exam(fetch(url))
            except Exception as e:
                print(f"  ! {url} 실패: {e}", flush=True)
                continue
            for q in qs:
                n += 1
                q["number"] = n  # 회차 내 연속 번호
                questions.append(q)
            time.sleep(0.5)
        if not questions:
            print(f"  {date}: 문항 0 — 스킵", flush=True)
            continue
        label = f"{date[:4]}년{date[4:6]}월{date[6:8]}일"
        # 표준 세션 파일 형식 (다른 자격증과 동일)
        data = {
            "exam": spec["name"],
            "dbname": code,
            "date": date,
            "label": label,
            "count": len(questions),
            "questions": questions,
            "source_site": "cbtbank.kr",
            "source_url": f"https://cbtbank.kr/exam/",
        }
        fp = outdir / f"{code}_{date}.json"
        fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        subjects = sorted({q["subject"] for q in questions if q.get("subject")})
        sessions.append((date, label))
        print(f"  ✓ {date}: {len(questions)}문항 ({len(subjects)}과목)", flush=True)
    # FE 호환 매니페스트 (fetch.py 재사용) + 전체 exams.json 갱신
    import fetch as _f
    _f._write_manifest(code, sessions)
    _f._write_top_manifest()
    print(f"완료: {len(sessions)}회차 → {outdir}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code", choices=list(EXAMS))
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    build_exam(args.code, args.date)


if __name__ == "__main__":
    main()

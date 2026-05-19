#!/usr/bin/env python3
"""
passcbt.kr — static prerender builder.

Reads data/* JSON, generates a deployable dist/* tree:

    dist/
      index.html                                   home (SPA shell, no prerender body)
      exam/<code>/index.html                       per-exam overview prerender
      exam/<code>/<session>/index.html             per-session prerender (all 100 Qs inline)
      concept/<code>/<slug>/index.html             per-concept prerender
      sitemap.xml                                  sitemap index
      sitemap-<code>.xml                           per-exam sub-sitemap
      robots.txt                                   absolute Sitemap URL
      webapp/...                                   copy of webapp/ assets (app.js, app.css, ...)
      data/...                                     copy of data/ JSON (SPA still fetches these at runtime)

The same SPA bundle (/webapp/app.{js,css}) is loaded by every prerender page;
on hydration it removes the <main id="prerender"> block and renders the SPA UI.

Run:
    python3 scripts/build_pages.py
    BASE_URL=https://www.passcbt.kr python3 scripts/build_pages.py
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]
    _PIL_OK = True
except ImportError as _pil_err:
    print(f"[og] Pillow import failed ({_pil_err}); falling back to /og-image.png")
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment, misc]
    _PIL_OK = False

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEBAPP = ROOT / "webapp"
DIST = ROOT / "dist"

BASE_URL = os.environ.get("BASE_URL", "https://www.passcbt.kr").rstrip("/")
SITE_NAME = "passcbt.kr"

# Korean-glyph font candidates, tried in order. The first that exists is used
# for OG image rendering. If none is found, OG generation falls back to
# the static /og-image.png and per-exam OG generation is skipped.
_FONT_CANDIDATES = [
    str(ROOT / "webapp" / "assets" / "og" / "font.ttf"),
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)

def fmt_date_kr(yyyymmdd: str) -> str:
    if len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return yyyymmdd
    y, m, d = yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:8]
    return f"{y}년 {int(m)}월 {int(d)}일"

def truncate(s: str, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"

def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------

def load_exams() -> list[dict]:
    return json.loads((DATA / "exams.json").read_text("utf-8"))["exams"]

def load_sessions(code: str) -> list[dict]:
    p = DATA / code / "sessions.json"
    return json.loads(p.read_text("utf-8"))["sessions"] if p.exists() else []

def load_session(code: str, sess_code: str) -> dict | None:
    p = DATA / code / f"{code}_{sess_code}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else None

def load_concept_index(code: str) -> dict:
    p = DATA / "concepts" / code / "index.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}

# ---------------------------------------------------------------------------
# page shell — reuse webapp/index.html as the source of truth
# ---------------------------------------------------------------------------

SHELL = (WEBAPP / "index.html").read_text("utf-8")

_RX_TITLE = re.compile(r"<title>[^<]*</title>")
_RX_META = lambda key, attr="name": re.compile(
    rf'<meta\s+{attr}="{re.escape(key)}"\s+content="[^"]*"\s*/?>'
)

def patch_shell(*, title: str, description: str, canonical: str,
                prerender_body: str, json_ld: str = "",
                og_image: str | None = None,
                og_title: str | None = None,
                og_description: str | None = None) -> str:
    h = SHELL
    og_title = og_title or title
    og_description = og_description or description
    og_image = og_image or f"{BASE_URL}/og-image.png"

    h = _RX_TITLE.sub(f"<title>{esc(title)}</title>", h, count=1)

    def replace(name: str, value: str, attr: str = "name") -> None:
        nonlocal h
        new_tag = f'<meta {attr}="{name}" content="{esc(value)}">'
        h2, n = _RX_META(name, attr).subn(new_tag, h, count=1)
        if n == 0:
            # not present — inject before </head>
            h2 = h.replace("</head>", new_tag + "\n</head>", 1)
        h = h2

    replace("description", description)
    replace("og:title", og_title, attr="property")
    replace("og:description", og_description, attr="property")
    replace("og:image", og_image, attr="property")
    replace("og:type", "article", attr="property")
    replace("twitter:title", og_title)
    replace("twitter:description", og_description)
    replace("twitter:card", "summary_large_image")

    inject = (
        f'<link rel="canonical" href="{esc(canonical)}">\n'
        f'<meta property="og:url" content="{esc(canonical)}">\n'
        f'<meta property="og:site_name" content="{SITE_NAME}">\n'
    )
    g_ver = os.environ.get(
        "GOOGLE_SITE_VERIFICATION",
        "nQeFu3iFhhd8Ug5aa7dQGso0sGvT7rOmkkr3f2NT_B8",
    ).strip()
    n_ver = os.environ.get(
        "NAVER_SITE_VERIFICATION",
        "df8578ec166880ee7c96b531cf77952dc8b59f87",
    ).strip()
    if g_ver:
        inject += f'<meta name="google-site-verification" content="{esc(g_ver)}">\n'
    if n_ver:
        inject += f'<meta name="naver-site-verification" content="{esc(n_ver)}">\n'
    if json_ld:
        inject += f'<script type="application/ld+json">{json_ld}</script>\n'
    h = h.replace("</head>", inject + "</head>", 1)

    if prerender_body:
        h = h.replace("</body>", prerender_body + "\n</body>", 1)
    return h

# ---------------------------------------------------------------------------
# rendering — question / session / exam / concept body
# ---------------------------------------------------------------------------

CIRCLED = "①②③④⑤⑥⑦⑧⑨"

def br(s: str) -> str:
    return esc(s).replace("\n", "<br>")

def render_question_block(q: dict) -> str:
    n = q.get("number") or 0
    stem = esc(q.get("question") or "")
    subject = esc(q.get("subject") or "")
    extras_html = ""
    for ex in q.get("question_extras") or []:
        if ex.get("content"):
            extras_html += f'<pre class="pre-extra">{esc(ex["content"])}</pre>'

    answer_no = q.get("answer") or 0  # 1-based in source data
    choices_html = []
    for i, c in enumerate(q.get("choices") or []):
        marker = CIRCLED[i] if i < len(CIRCLED) else f"{i+1})"
        cls = "choice is-answer" if (i + 1) == answer_no else "choice"
        choices_html.append(
            f'<li class="{cls}"><span class="m">{marker}</span> {esc(c.get("text") or "")}</li>'
        )

    explanation = q.get("explanation_detailed") or q.get("explanation") or ""
    expl_html = f'<div class="explanation"><strong>해설</strong><br>{br(explanation)}</div>' if explanation else ""

    concepts = q.get("concepts") or []
    concept_html = ""
    if concepts:
        chips = "".join(f'<span class="chip">{esc(c)}</span>' for c in concepts)
        concept_html = f'<div class="concepts"><strong>핵심 개념</strong> {chips}</div>'

    return (
        f'<article class="q" id="q{n}">'
        f'<header class="qh"><h2 class="qn">{n}번 · {subject}</h2></header>'
        f'<p class="qb">{stem}</p>'
        + extras_html
        + f'<ol class="choices">{"".join(choices_html)}</ol>'
        + f'<div class="answer"><strong>정답</strong> {answer_no}번</div>'
        + expl_html
        + concept_html
        + "</article>"
    )

def render_session_page(exam: dict, sess_meta: dict, data: dict, og_image: str | None = None) -> tuple[str, str, str]:
    """returns (html, title, description)"""
    code = exam["code"]
    sess_code = sess_meta["code"]
    label = fmt_date_kr(sess_code)
    questions = data.get("questions") or []
    title = f'{exam["name"]} {label} 기출문제 정답·해설 ({len(questions)}문항 무료)'
    first_q = (questions[0]["question"] if questions else "")
    description = truncate(
        f'{exam["name"]} {label} 기출문제 {len(questions)}문항 무료 CBT 풀이. '
        f'정답·AI 보강 해설·핵심 개념. {first_q}'
    )
    canonical = f'{BASE_URL}/exam/{code}/{sess_code}'

    items = "".join(render_question_block(q) for q in questions)
    body = (
        f'<main id="prerender" class="prerender prerender-session">'
        f'<header><h1>{esc(title)}</h1>'
        f'<p>{esc(exam["name"])} · {esc(label)} · 총 {len(questions)}문항. '
        f'각 문제의 정답과 AI 보강 해설, 핵심 개념을 함께 확인하세요.</p></header>'
        f'<section class="questions">{items}</section>'
        f'<footer><p><a href="/exam/{code}">← {esc(exam["name"])} 회차 목록</a></p></footer>'
        f'</main>'
    )

    # JSON-LD: QAPage. Cap at 30 mainEntities to avoid bloating; full text is in body.
    qa = []
    for q in questions[:30]:
        ans_no = q.get("answer") or 0  # 1-based
        choices = q.get("choices") or []
        ans_text = ""
        if 1 <= ans_no <= len(choices):
            ans_text = choices[ans_no - 1].get("text") or ""
        # Schema.org/Answer should be the actual answer, with the explanation as supporting text.
        explanation = (q.get("explanation_detailed") or q.get("explanation") or "")[:600]
        answer_text = ans_text + ("\n\n" + explanation if explanation else "") if ans_text else explanation
        qa.append({
            "@type": "Question",
            "name": (q.get("question") or "")[:300],
            "text": q.get("question") or "",
            "answerCount": 1,
            "acceptedAnswer": {
                "@type": "Answer",
                "text": answer_text[:1500],
            },
        })
    ld = {
        "@context": "https://schema.org",
        "@type": "QAPage",
        "mainEntity": qa,
    }

    h = patch_shell(
        title=title,
        description=description,
        canonical=canonical,
        prerender_body=body,
        json_ld=json.dumps(ld, ensure_ascii=False, separators=(",", ":")),
        og_image=og_image,
    )
    return h, title, description

def render_exam_page(exam: dict, sessions: list[dict], all_exams: list[dict],
                     og_image: str | None = None) -> str:
    code = exam["code"]
    title = f'{exam["name"]} 기출문제 · 정답 · 해설 ({exam.get("sessions", 0)}회차 무료)'
    description = truncate(
        f'{exam["name"]} 기출문제 {exam.get("questions", 0):,}문항 · {exam.get("sessions", 0)}회차 무료 CBT 풀이. '
        f'각 문항 정답·AI 보강 해설·핵심 개념 제공. '
        f'과목: {", ".join(exam.get("subjects") or [])}.'
    )
    canonical = f'{BASE_URL}/exam/{code}'

    session_rows = "".join(
        f'<li><a href="/exam/{code}/{s["code"]}">{fmt_date_kr(s["code"])}</a> '
        f'<span class="muted">{s.get("count", 0)}문항</span></li>'
        for s in sessions
    )
    subj_rows = "".join(f"<li>{esc(sub)}</li>" for sub in (exam.get("subjects") or []))
    cross_rows = "".join(
        f'<li><a href="/exam/{e["code"]}">{esc(e["name"])}</a> '
        f'<span class="muted">{e.get("sessions", 0)}회차 · {e.get("questions", 0):,}문항</span></li>'
        for e in all_exams if e["code"] != code
    )
    body = (
        f'<main id="prerender" class="prerender prerender-exam">'
        f'<header><h1>{esc(title)}</h1>'
        f'<p>총 {exam.get("sessions", 0)}개 회차 · {exam.get("questions", 0)}문항. '
        f'각 회차별 정답과 AI 보강 해설, 핵심 개념을 함께 제공합니다.</p></header>'
        f'<section><h2>시험 과목</h2><ul class="subjects">{subj_rows}</ul></section>'
        f'<section><h2>회차별 기출</h2><ul class="sessions">{session_rows}</ul></section>'
        f'<footer><h2>다른 자격증</h2><ul class="cross-links">{cross_rows}</ul></footer>'
        f'</main>'
    )
    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": description,
        "url": canonical,
    }
    return patch_shell(
        title=title, description=description, canonical=canonical,
        prerender_body=body,
        json_ld=json.dumps(ld, ensure_ascii=False, separators=(",", ":")),
        og_image=og_image,
    )

def render_concept_page(exam: dict, concept: dict, og_image: str | None = None) -> str:
    code = exam["code"]
    cid = concept["id"]
    name = concept.get("name_ko") or concept.get("name_en") or cid
    title = f'{name} — {exam["name"]} 핵심 개념'
    canonical = f'{BASE_URL}/concept/{code}/{cid}'
    refs = concept.get("refs") or []
    body_data = concept.get("body") or {}

    # Description prefers AI-generated definition (concise, semantically rich) — falls back to generic.
    if body_data.get("definition"):
        description = truncate(f'{body_data["definition"]} — {exam["name"]} 핵심 개념. 출제 {len(refs)}회.')
    else:
        description = truncate(
            f'{exam["name"]}에서 {len(refs)}회 출제된 핵심 개념 "{name}"의 기출문제와 정리. '
            f'관련 과목: {", ".join(concept.get("subjects") or [])}'
        )

    ref_rows = "".join(
        f'<li><a href="/exam/{code}/{r["session"]}#q{r["qnum"]}">'
        f'{fmt_date_kr(r["session"])} {r["qnum"]}번</a></li>'
        for r in refs
    )
    members = concept.get("members") or []
    members_html = ", ".join(esc(m) for m in members) if members else esc(name)

    body_sections_html = ""
    if body_data:
        sec = lambda label, content: (
            f'<section class="concept-body-section"><h2>{label}</h2>{content}</section>'
            if content else ""
        )
        kp_html = ""
        kps = [k for k in (body_data.get("key_points") or []) if k]
        if kps:
            kp_html = f'<ul class="concept-keypoints">{"".join(f"<li>{esc(k)}</li>" for k in kps)}</ul>'
        body_sections_html = (
            sec("정의", f"<p>{esc(body_data.get('definition') or '')}</p>")
            + sec("직관", f"<p>{esc(body_data.get('intuition') or '')}</p>")
            + sec("핵심 포인트", kp_html)
            + sec("자주 헷갈리는 점", f"<p>{esc(body_data.get('pitfalls') or '')}</p>")
            + sec("작은 예시", f"<p>{esc(body_data.get('example') or '')}</p>")
        )

    body = (
        f'<main id="prerender" class="prerender prerender-concept">'
        f'<header><h1>{esc(name)}</h1>'
        f'<p>{esc(exam["name"])} · 출제 횟수 {len(refs)}회</p></header>'
        + body_sections_html
        + f'<section><h2>유사 표현</h2><p>{members_html}</p></section>'
        + f'<section><h2>출제 기출문제</h2><ul class="refs">{ref_rows}</ul></section>'
        + f'</main>'
    )

    # JSON-LD: DefinedTerm with definition; add BreadcrumbList for navigation depth.
    ld_term = {
        "@context": "https://schema.org",
        "@type": "DefinedTerm",
        "name": name,
        "description": (body_data.get("definition") or description),
        "url": canonical,
        "inDefinedTermSet": exam["name"],
    }
    ld_crumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": SITE_NAME, "item": BASE_URL},
            {"@type": "ListItem", "position": 2, "name": exam["name"],
             "item": f'{BASE_URL}/exam/{code}'},
            {"@type": "ListItem", "position": 3, "name": name, "item": canonical},
        ],
    }
    json_ld_combined = (
        json.dumps(ld_term, ensure_ascii=False, separators=(",", ":"))
        + '</script><script type="application/ld+json">'
        + json.dumps(ld_crumb, ensure_ascii=False, separators=(",", ":"))
    )
    return patch_shell(
        title=title, description=description, canonical=canonical,
        prerender_body=body,
        json_ld=json_ld_combined,
        og_image=og_image,
    )

def render_home() -> str:
    """Home page: SPA shell with a small prerender block listing the exams.

    Crawler sees the exam list and short branding copy; SPA replaces it on hydration.
    """
    exams = load_exams()
    rows = "".join(
        f'<li><a href="/exam/{e["code"]}">{esc(e["name"])}</a> '
        f'<span class="muted">{e.get("sessions", 0)}회차 · {e.get("questions", 0)}문항</span></li>'
        for e in exams
    )
    exam_names = " · ".join(e["name"] for e in exams)
    total_q = sum(e.get("questions", 0) for e in exams)
    total_sessions = sum(e.get("sessions", 0) for e in exams)
    body = (
        f'<main id="prerender" class="prerender prerender-home">'
        f'<header><h1>{SITE_NAME} · 자격증 기출문제 무료 학습 PWA</h1>'
        f'<p>{esc(exam_names)} 기출문제 {total_q:,}문항을 회차별 정답·AI 보강 해설·핵심 개념과 함께 '
        f'모바일에서 무료로 풀이하세요. 로그인·서버·트래킹 없는 PWA.</p></header>'
        f'<section><h2>자격증 ({len(exams)}종)</h2><ul class="exams">{rows}</ul></section>'
        f'</main>'
    )
    # title 은 검색결과에서 60자 내외로 잘려서 핵심 키워드만 노출되도록 짧게.
    title = f'{SITE_NAME} · {len(exams)}개 자격증 기출문제 무료 학습 PWA'
    description = truncate(
        f"{exam_names} 기출문제 {total_q:,}문항·{total_sessions}회차 무료 풀이. "
        "정답·AI 보강 해설·핵심 개념. 모바일 PWA, 로그인·서버 없음."
    )
    ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": BASE_URL,
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{BASE_URL}/exam/{{exam_code}}",
            "query-input": "required name=exam_code",
        },
    }
    return patch_shell(
        title=title, description=description, canonical=f"{BASE_URL}/",
        prerender_body=body,
        json_ld=json.dumps(ld, ensure_ascii=False, separators=(",", ":")),
    )

# ---------------------------------------------------------------------------
# OG images (per-exam) — Pillow-based, paper background + ink title.
# ---------------------------------------------------------------------------

_OG_W, _OG_H = 1200, 630
_OG_PAPER = (245, 235, 217)   # var(--paper)
_OG_INK = (26, 20, 16)        # var(--ink)
_OG_VERMILION = (185, 28, 28) # var(--vermilion)
_OG_SOFT = (124, 111, 92)     # var(--ink-mute)

_FONT_DOWNLOAD_URL = (
    "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/"
    "packages/pretendard/dist/public/static/Pretendard-Bold.otf"
)

def _find_font() -> str | None:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    # Fallback: fetch Pretendard-Bold once at build time. Cached locally.
    bundled = ROOT / "webapp" / "assets" / "og" / "font.ttf"
    if bundled.exists():
        return str(bundled)
    try:
        bundled.parent.mkdir(parents=True, exist_ok=True)
        print(f"[og] downloading {_FONT_DOWNLOAD_URL}")
        with urllib.request.urlopen(_FONT_DOWNLOAD_URL, timeout=20) as r:
            bundled.write_bytes(r.read())
        return str(bundled)
    except Exception as e:
        print(f"[og] font download failed: {e}")
        return None

def write_og_images(exams: list[dict]) -> dict[str, str]:
    """Render one OG PNG per exam. Returns {exam_code: og_image_url}."""
    out: dict[str, str] = {}
    if not _PIL_OK or Image is None or ImageDraw is None or ImageFont is None:
        print("[og] Pillow not installed — skipping per-exam OG (using fallback /og-image.png)")
        return out
    font_path = _find_font()
    if not font_path:
        print("[og] no Korean font found — skipping per-exam OG (using fallback)")
        return out

    og_dir = DIST / "og"
    og_dir.mkdir(parents=True, exist_ok=True)
    big = ImageFont.truetype(font_path, 90)
    sub = ImageFont.truetype(font_path, 36)
    brand = ImageFont.truetype(font_path, 28)

    for exam in exams:
        img = Image.new("RGB", (_OG_W, _OG_H), _OG_PAPER)
        d = ImageDraw.Draw(img)
        # subtle deep-paper bottom band for visual weight
        d.rectangle((0, _OG_H - 90, _OG_W, _OG_H), fill=(235, 223, 197))
        # brand mark (top-left)
        d.text((60, 50), SITE_NAME, font=brand, fill=_OG_VERMILION)
        # tagline (top-right area)
        d.text((60, 100), "STUDY · CERTIFICATION", font=sub, fill=_OG_SOFT)
        # main title
        d.text((60, 220), exam["name"], font=big, fill=_OG_INK)
        # detail
        sub_line = (
            f'{exam.get("sessions", 0)}회차 · {exam.get("questions", 0)}문항 · '
            f'AI 보강 해설'
        )
        d.text((60, 360), sub_line, font=sub, fill=_OG_INK)
        # subjects (one line, truncated)
        subjects = " · ".join(exam.get("subjects") or [])
        if len(subjects) > 36:
            subjects = subjects[:35] + "…"
        d.text((60, 420), subjects, font=sub, fill=_OG_SOFT)
        # footer
        d.text((60, _OG_H - 60), "passcbt.kr · 무료 PWA · 광고 외 트래킹 없음",
               font=brand, fill=_OG_INK)

        path = og_dir / f'{exam["code"]}.png'
        img.save(path, optimize=True)
        out[exam["code"]] = f"{BASE_URL}/og/{exam['code']}.png"
    print(f"[og] wrote {len(out)} per-exam OG images")
    return out

# ---------------------------------------------------------------------------
# sitemap & robots
# ---------------------------------------------------------------------------

def write_sitemaps(exam_to_urls: dict[str, list[tuple[str, float]]]) -> None:
    # Per-exam sitemaps.
    sub_sitemaps: list[str] = []
    for code, urls in exam_to_urls.items():
        out = DIST / f"sitemap-{code}.xml"
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for path, priority in urls:
            lines.append(
                f'  <url><loc>{BASE_URL}{path}</loc>'
                f'<priority>{priority:.1f}</priority></url>'
            )
        lines.append("</urlset>")
        write_file(out, "\n".join(lines) + "\n")
        sub_sitemaps.append(f"sitemap-{code}.xml")

    # Index sitemap.
    idx_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for sm in sub_sitemaps:
        idx_lines.append(f"  <sitemap><loc>{BASE_URL}/{sm}</loc></sitemap>")
    idx_lines.append("</sitemapindex>")
    write_file(DIST / "sitemap.xml", "\n".join(idx_lines) + "\n")

def write_robots() -> None:
    # Whitelist: search engines we want to index us. They can crawl everything.
    # Generic *: allowed to crawl HTML but not /data/ (raw JSON; content already in prerender HTML).
    # Blocklist: SEO/marketing/data-mining bots that consume Edge Requests + bandwidth without
    # bringing visitors. They inflate Vercel costs disproportionately.
    blocked = [
        "AhrefsBot", "SemrushBot", "MJ12bot", "DotBot", "BLEXBot",
        "PetalBot", "DataForSeoBot", "SerpstatBot", "ZoominfoBot",
        "magpie-crawler", "linkfluence", "AwarioBot", "Bytespider",
        "GPTBot", "ClaudeBot", "PerplexityBot", "CCBot", "Amazonbot",
        "Diffbot", "Sogou", "YandexBot",
    ]
    lines = []
    # Friendly allow for major search engines.
    for ua in ("Googlebot", "Googlebot-Image", "Bingbot", "Naverbot", "Yeti", "Daum"):
        lines += [f"User-agent: {ua}", "Allow: /", ""]
    # Default policy: allow but keep raw data out of the index.
    lines += [
        "User-agent: *",
        "Allow: /",
        "Disallow: /data/",
        "Disallow: /api/",
        "Crawl-delay: 5",
        "",
    ]
    # Hard block.
    for ua in blocked:
        lines += [f"User-agent: {ua}", "Disallow: /", ""]
    lines.append(f"Sitemap: {BASE_URL}/sitemap.xml")
    write_file(DIST / "robots.txt", "\n".join(lines) + "\n")

# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    # Copy static assets.
    copy_tree(WEBAPP, DIST / "webapp")
    copy_tree(DATA, DIST / "data")

    # Pull-up the small assets the SPA references at root paths.
    for fname in (
        "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png",
        "apple-touch-icon.png", "og-image.png", "sw.js", "ads.txt",
    ):
        src = WEBAPP / fname
        if src.exists():
            shutil.copy2(src, DIST / fname)

    # Home page: replace dist/index.html (currently from the webapp copy)
    # with the prerender-augmented version.
    write_file(DIST / "index.html", render_home())

    exams = load_exams()
    og_by_exam = write_og_images(exams)
    exam_to_urls: dict[str, list[tuple[str, float]]] = {}

    sessions_total = 0
    for exam in exams:
        code = exam["code"]
        og_image = og_by_exam.get(code)
        sessions = load_sessions(code)
        urls: list[tuple[str, float]] = [(f"/exam/{code}", 0.8)]

        # exam overview page
        write_file(DIST / "exam" / code / "index.html",
                   render_exam_page(exam, sessions, exams, og_image=og_image))

        # session pages
        for s in sessions:
            sd = load_session(code, s["code"])
            if not sd:
                continue
            page, _, _ = render_session_page(exam, s, sd, og_image=og_image)
            write_file(DIST / "exam" / code / s["code"] / "index.html", page)
            urls.append((f'/exam/{code}/{s["code"]}', 0.6))
            sessions_total += 1

        # concept pages (only where available)
        ci = load_concept_index(code)
        if ci:
            for cid, c in ci.items():
                page = render_concept_page(exam, c, og_image=og_image)
                write_file(DIST / "concept" / code / cid / "index.html", page)
                urls.append((f"/concept/{code}/{cid}", 0.5))

        exam_to_urls[code] = urls

    write_sitemaps(exam_to_urls)
    write_robots()

    n_concepts = sum(1 for code in [e["code"] for e in exams]
                     for _ in load_concept_index(code).keys())
    total_urls = sum(len(v) for v in exam_to_urls.values()) + 1  # +home
    print(
        f"built {sessions_total} session pages, {len(exams)} exam pages, "
        f"{n_concepts} concept pages → {total_urls} URLs in sitemap."
    )

if __name__ == "__main__":
    main()

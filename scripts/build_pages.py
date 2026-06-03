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

ADS_SCRIPT = (
    '<script async '
    'src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
    '?client=ca-pub-1443771548671737" crossorigin="anonymous"></script>'
)


def patch_shell(*, title: str, description: str, canonical: str,
                prerender_body: str, json_ld: str = "",
                og_image: str | None = None,
                og_title: str | None = None,
                og_description: str | None = None,
                ads: bool = False) -> str:
    h = SHELL
    og_title = og_title or title
    og_description = og_description or description
    og_image = og_image or f"{BASE_URL}/og-image.png"

    _title_tag = f"<title>{esc(title)}</title>"
    h = _RX_TITLE.sub(lambda _m: _title_tag, h, count=1)

    def replace(name: str, value: str, attr: str = "name") -> None:
        nonlocal h
        new_tag = f'<meta {attr}="{name}" content="{esc(value)}">'
        # lambda 로 raw replacement → \W, \1 등 escape 해석 회피
        h2, n = _RX_META(name, attr).subn(lambda _m: new_tag, h, count=1)
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
    # AdSense: 콘텐츠 풍부 페이지(세션·개념)에만 주입. 홈·exam-overview(네비게이션)엔 미주입.
    if ads:
        inject += ADS_SCRIPT + "\n"
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
        ads=True,  # 세션 페이지 = 문항·해설 전문 → 콘텐츠 풍부, 광고 허용
    )
    return h, title, description

# 자격증별 고유 소개 콘텐츠 (정확·고유 — 중복/빈약 콘텐츠 회피용).
# about: 개요·시행/활용  who: 추천 대상·진로  study: 학습 가이드
EXAM_INTRO = {
    "s2": {
        "about": "사회조사분석사 2급은 설문조사의 기획·설계부터 자료 수집, 통계 분석, 결과 해석까지 조사 전 과정을 수행하는 능력을 검정하는 국가기술자격입니다. 한국산업인력공단이 시행하며, 필기는 조사방법론 Ⅰ·Ⅱ와 사회통계 세 과목의 객관식으로 구성되고 이후 실기(작업형·필답형)를 거칩니다.",
        "who": "시장조사·여론조사 기관, 공공기관의 정책 연구, 기업의 고객·만족도 조사 직무에서 활용도가 높습니다. 사회과학·통계 전공자나 리서치 실무자에게 권장됩니다.",
        "study": "사회통계의 추정·검정과 조사방법론의 타당도·신뢰도 개념이 반복 출제됩니다. 회차를 거듭하며 표본추출·척도·가설검정 유형을 정리하면 효율적입니다.",
    },
    "g1": {
        "about": "공인중개사는 부동산의 매매·임대차 등을 알선하는 국토교통부 소관 국가전문자격으로, 1차 시험은 부동산학개론과 민법 및 민사특별법 두 과목으로 치러집니다. 1·2차를 같은 해에 함께 응시할 수 있으나 최종 합격은 1차 합격이 전제됩니다.",
        "who": "부동산 중개업 개설·등록을 준비하거나 부동산 투자·자산관리 지식을 체계화하려는 분께 적합합니다.",
        "study": "부동산학개론의 수요·공급과 감정평가, 민법의 물권·계약 파트가 핵심입니다. 기출 반복 출제 비중이 높아 회차 풀이가 특히 효과적입니다.",
    },
    "g2": {
        "about": "공인중개사 2차는 실무에 직결되는 공인중개사법령 및 실무, 부동산공법, 부동산공시법 및 세법 세 과목으로 구성됩니다. 1차 합격자(또는 동시 응시 후 1차 합격자)에 한해 최종 합격이 인정됩니다.",
        "who": "중개 실무와 부동산 공법·세무 지식을 함께 갖추려는 예비 공인중개사에게 필수 단계입니다.",
        "study": "공법의 국토계획·건축·정비사업 규정과 공시법·세법의 계산 문제가 까다롭습니다. 법령 개정 사항과 세율 변화에 유의하며 기출로 유형을 익히세요.",
    },
    "iz": {
        "about": "정보처리기사는 소프트웨어 개발 전반의 설계·구현·관리 역량을 검정하는 대표적인 IT 국가기술자격(기사)입니다. 필기는 소프트웨어 설계·개발, 데이터베이스 구축, 프로그래밍 언어 활용, 정보시스템 구축관리 다섯 과목으로 구성됩니다.",
        "who": "소프트웨어 개발자 취업, 공공기관·공기업 응시 및 가산점, 학점은행·경력 인정 등에 폭넓게 쓰입니다.",
        "study": "SQL·정규화, 디자인 패턴, 네트워크·보안 용어가 자주 나옵니다. 개념 암기와 함께 기출 보기 표현을 익히는 것이 점수에 직접 도움이 됩니다.",
    },
    "c1": {
        "about": "컴퓨터활용능력 1급은 대한상공회의소가 시행하는 사무자동화 자격으로, 데이터 처리와 분석 능력을 검정합니다. 필기는 컴퓨터 일반, 스프레드시트 일반, 데이터베이스 일반 세 과목으로 구성되며 이후 실기(스프레드시트·데이터베이스)를 치릅니다.",
        "who": "사무·행정 직무, 데이터 정리·보고 업무를 다루는 직장인과 취업 준비생에게 널리 활용됩니다.",
        "study": "스프레드시트의 함수·차트·매크로와 데이터베이스의 질의 개념이 핵심입니다. 필기 기출은 함정 보기가 많아 회차 반복으로 패턴을 익히는 것이 좋습니다.",
    },
    "sa": {
        "about": "산업안전기사는 사업장의 재해를 예방·관리하는 안전관리자 직무의 국가기술자격(기사)입니다. 안전관리론, 인간공학 및 시스템안전공학, 기계·전기·화학설비 위험방지기술, 건설안전기술 등 여섯 과목으로 폭넓게 출제됩니다.",
        "who": "제조·건설 현장의 안전관리자 선임 요건을 충족하려는 분, 안전 직무로 진출하려는 분께 권장됩니다.",
        "study": "법령·기준 수치와 각 설비별 방지기술이 방대합니다. 자주 나오는 수치·정의를 회차별로 누적 정리하면 합격선 관리에 유리합니다.",
    },
    "kt": {
        "about": "전기기사는 전기 설비의 설계·시공·운용·안전관리를 다루는 전기 분야 대표 국가기술자격(기사)입니다. 전기자기학, 전력공학, 전기기기, 회로이론 및 제어공학, 전기설비기술기준 및 판단기준 다섯 과목으로 구성됩니다.",
        "who": "전기안전관리자 선임, 전기공사·설계 직무, 공기업·발전사 응시를 준비하는 분께 핵심 자격입니다.",
        "study": "회로이론·전력공학의 계산 문제와 기술기준 암기가 병행됩니다. 공식 유도보다 기출 계산 유형을 반복 숙달하는 것이 효율적입니다.",
    },
    "nd": {
        "about": "소방설비기사(기계분야)는 스프링클러·소화설비 등 기계 소방시설의 설계·시공·점검 역량을 검정하는 국가기술자격(기사)입니다. 소방원론, 소방유체역학, 소방관계법규, 소방기계시설의 구조 및 원리 네 과목으로 구성됩니다.",
        "who": "소방시설 설계·감리·점검 업체 종사자, 소방안전관리자 선임을 준비하는 분께 적합합니다.",
        "study": "유체역학 계산과 화재안전기준(NFSC/NFTC)의 수치가 핵심입니다. 법규 개정과 설비별 기준값을 기출과 함께 정리하세요.",
    },
    "k1": {
        "about": "한국사능력검정시험 심화는 국사편찬위원회가 주관하는 시험으로, 성적에 따라 1~3급이 부여됩니다. 선사시대부터 현대까지 전 시대의 사료·유물·사건을 50문항으로 폭넓게 다룹니다.",
        "who": "공무원 응시·승진, 공기업 채용 가산, 교원 임용 등 여러 분야에서 일정 급수 이상을 요구합니다.",
        "study": "시대별 흐름과 핵심 사건·인물, 사료 해석이 반복됩니다. 회차를 풀며 자주 나오는 자료·유물 이미지를 익히면 시간 단축에 도움이 됩니다.",
    },
    "sw": {
        "about": "사회복지사 1급은 사회복지 실천·정책·법제 전반의 전문성을 검정하는 국가자격으로, 보건복지부 소관으로 시행됩니다. 인간행동과 사회환경, 사회복지조사론, 실천론·실천기술론, 지역사회복지론, 정책론·행정론·법제론 등 8과목을 3교시에 걸쳐 치릅니다.",
        "who": "사회복지시설·기관, 공공 복지 행정, 의료·학교 사회복지 등으로 진출하려는 분께 최상위 사회복지 자격입니다.",
        "study": "실천론의 관점·모델과 법제론의 법령 체계가 핵심이며 과목 간 연계가 많습니다. 회차별 사례형 문항을 반복하면 응용력을 키울 수 있습니다.",
    },
}


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
    intro = EXAM_INTRO.get(code, {})
    intro_html = ""
    if intro:
        intro_html = (
            f'<section><h2>{esc(exam["name"])}란?</h2><p>{esc(intro["about"])}</p></section>'
            f'<section><h2>이런 분께 추천합니다</h2><p>{esc(intro["who"])}</p></section>'
            f'<section><h2>학습 가이드</h2><p>{esc(intro["study"])}</p>'
            f'<p>passcbt 에서는 {exam.get("name","")} 기출문제 {exam.get("questions", 0):,}문항을 '
            f'회차별로 무료로 풀이하고, 각 문항의 정답과 AI 보강 해설(핵심 개념·정답 분석·오답 분석)을 '
            f'확인할 수 있습니다.</p></section>'
        )
    body = (
        f'<main id="prerender" class="prerender prerender-exam">'
        f'<header><h1>{esc(title)}</h1>'
        f'<p>총 {exam.get("sessions", 0)}개 회차 · {exam.get("questions", 0)}문항. '
        f'각 회차별 정답과 AI 보강 해설, 핵심 개념을 함께 제공합니다.</p></header>'
        + intro_html
        + f'<section><h2>시험 과목</h2><ul class="subjects">{subj_rows}</ul></section>'
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
        ads=True,  # 개념 페이지 = 정의·핵심포인트·기출 → 콘텐츠 풍부, 광고 허용
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
        f'<section><h2>passcbt 는 어떤 서비스인가요?</h2>'
        f'<p>passcbt 는 국가기술자격·전문자격 시험의 <strong>실제 기출문제 {total_q:,}문항</strong>을 '
        f'CBT(Computer Based Test) 방식 그대로 풀어볼 수 있는 무료 학습 도구입니다. '
        f'{total_sessions}개 회차의 모든 문항에 대해 공식 정답과 함께, 왜 그 보기가 정답인지를 설명하는 '
        f'AI 보강 해설(핵심 개념·정답 분석·오답 분석)을 제공합니다. 회원가입이나 결제가 필요 없으며, '
        f'PWA 로 설치하면 오프라인에서도 학습할 수 있습니다.</p></section>'
        f'<section><h2>이렇게 활용하세요</h2><ul>'
        f'<li><strong>회차별 실전 풀이</strong> — 실제 시험과 동일한 문항 구성으로 시간을 재며 풀이하고 자동 채점받습니다.</li>'
        f'<li><strong>오답 다시보기·별표</strong> — 틀린 문항과 표시한 문항만 모아 반복 학습합니다.</li>'
        f'<li><strong>핵심 개념 정리</strong> — 문항마다 추출된 핵심 개념을 눌러 같은 개념이 출제된 다른 기출과 정의를 함께 봅니다.</li>'
        f'<li><strong>AI 해설</strong> — 정답뿐 아니라 각 오답이 왜 틀렸는지까지 설명해 이해 중심 학습을 돕습니다.</li>'
        f'</ul></section>'
        f'<section><h2>자주 묻는 질문</h2>'
        f'<p><strong>정말 무료인가요?</strong> 네, 모든 문항·해설이 무료이며 로그인이 필요 없습니다.</p>'
        f'<p><strong>해설은 어떻게 만들어지나요?</strong> 공개된 기출문제의 정답을 기준으로, 각 문항의 핵심 개념과 '
        f'정답·오답 근거를 AI 가 정리해 보강합니다.</p>'
        f'<p><strong>어떤 기기에서 쓰나요?</strong> 모바일·PC 브라우저 모두 지원하며, 홈 화면에 설치해 앱처럼 쓸 수 있습니다.</p>'
        f'</section>'
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

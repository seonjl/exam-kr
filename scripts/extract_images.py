"""이미지(gif) 컨텐츠를 구조화 마크다운으로 추출해 JSON에 임베드.

외부 이미지 URL을 제거하고 각 이미지를 LaTeX / 마크다운 테이블 / Mermaid /
평문 중 하나로 변환한 `extras` 필드로 대체한다.

JSON 스키마 변화:
  question_images: [url, ...]  →  question_extras: [{kind, content}, ...]
  choices[].images: [...]       →  choices[].extras:  [...]
  explanation_images: [...]     →  explanation_extras: [...]

사용법:
  python3 extract_images.py --sample 10       # 10개만 돌려 품질 확인
  python3 extract_images.py --all             # 전체
  python3 extract_images.py --stats           # 현재 추출 진척 통계만
  python3 extract_images.py --dry             # 실행하지 않고 프롬프트만 출력

특성:
- `data/.image_cache.json`에 URL → 결과 캐시 (중복 호출 방지)
- circuit breaker: 연속 실패 N회 시 중단
- 스키마 마이그레이션은 캐시가 충분히 찰 때 한 번에 수행 (--apply)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
CACHE_PATH = DATA / ".image_cache.json"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120"

PROMPT = """이 디렉터리의 {filename} 을 Read 도구로 열어서 내용을 구조화 마크다운으로 변환해.

규칙:
- 수식 → $$LaTeX$$ (KaTeX 호환)
- 표 → 마크다운 table (헤더 포함)
- 흐름도·트리·관계 다이어그램 → ```mermaid 블록 (flowchart TD, graph LR 등)
- 단순 한국어·기호·변수 리스트 → 그대로 평문 (공백·기호·줄바꿈 살림)
- 혼합이면 위 형식들을 자연스러운 순서로 조합

아무 설명도 붙이지 말고 변환 결과만 출력.
"""


# ---------- cache ----------
def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


_cache_lock = threading.Lock()


def save_cache(cache: dict) -> None:
    with _cache_lock:
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(CACHE_PATH)


# ---------- collect urls ----------
def collect_urls() -> list[str]:
    urls: list[str] = []
    for p in sorted(DATA.glob("*/*_*.json")):
        if p.name == "sessions.json":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict):  # data/audit/*.json 등 비문항 산출물 스킵
            continue
        for q in d.get("questions", []):
            for u in (q.get("question_images") or []): urls.append(u)
            for c in (q.get("choices") or []):
                for u in (c.get("images") or []): urls.append(u)
            for u in (q.get("explanation_images") or []): urls.append(u)
    return urls


def url_key(url: str) -> str:
    """Canonical cache key — strip query string."""
    return url.split("?", 1)[0]


def resolve_url(url: str) -> str:
    """상대경로 /images/{path} → comcbt CDN 절대 URL 로 해석 (다운로드용)."""
    if url.startswith("/images/"):
        return "https://img.comcbt.com/cbt/data/" + url[len("/images/"):]
    return url


# ---------- detection ----------
def detect_kind(content: str) -> str:
    s = content.strip()
    if "```mermaid" in s:
        return "diagram"
    if "$$" in s or re.search(r"\\frac|\\sum|\\int|\\sqrt|\\alpha|\\beta", s):
        return "formula"
    if re.search(r"^\|.+\|$", s, flags=re.M):
        return "table"
    return "text"


# ---------- claude call ----------
def call_claude_on_image(url: str, *, timeout: int = 120, model: str | None = None) -> str:
    """Download image to a temp dir (cwd-scoped) and ask claude to Read it."""
    with tempfile.TemporaryDirectory(prefix="imgx_") as td:
        tmpdir = Path(td)
        ext = url.rsplit(".", 1)[-1].split("?")[0] or "gif"
        fname = f"img.{ext}"
        fpath = tmpdir / fname

        raw = urllib.request.Request(resolve_url(url), headers={"User-Agent": UA})
        with urllib.request.urlopen(raw, timeout=30) as r:
            fpath.write_bytes(r.read())

        prompt = PROMPT.format(filename=fname)
        cmd = ["claude", "-p", prompt]
        if model:
            cmd[1:1] = ["--model", model]
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, cwd=td, timeout=timeout,
        )
        if r.returncode != 0:
            raise RuntimeError(f"claude failed: {r.stderr.strip()}")
        out = r.stdout.strip()
        if not out:
            raise RuntimeError("empty output")
        return out


# ---------- pipeline ----------
class Breaker:
    def __init__(self, threshold: int = 15):
        self.threshold = threshold
        self._fails = 0
        self._lock = threading.Lock()
        self.tripped = False

    def ok(self):
        with self._lock:
            self._fails = 0

    def bad(self):
        with self._lock:
            self._fails += 1
            if self._fails >= self.threshold:
                self.tripped = True


def process_urls(urls: list[str], *, workers: int = 1, dry: bool = False, model: str | None = None, breaker_threshold: int = 50) -> dict:
    cache = load_cache()
    # dedupe by canonical key, keep first occurrence
    seen = set(); work = []
    for u in urls:
        k = url_key(u)
        if k in seen: continue
        seen.add(k)
        if k not in cache:
            work.append((k, u))
    print(f"추출 대상: {len(work)}개 · 이미 캐시: {len(cache)}개", flush=True)
    if not work or dry:
        if dry and work:
            print("예시 프롬프트:")
            print(PROMPT.format(filename="example.gif"))
        return {"done": 0, "failed": 0, "skipped": len(cache)}

    breaker = Breaker(breaker_threshold)
    done = failed = 0
    lock = threading.Lock()

    def worker(item):
        nonlocal done, failed
        k, u = item
        if breaker.tripped:
            return
        try:
            text = call_claude_on_image(u, model=model)
            kind = detect_kind(text)
            cache[k] = {"kind": kind, "content": text, "ts": int(time.time())}
            breaker.ok()
            with lock:
                done += 1
            if done % 5 == 0:
                save_cache(cache)
            print(f"  ✓ {k.rsplit('/',1)[-1]}  [{kind}] ({len(text)}자)", flush=True)
        except Exception as e:
            breaker.bad()
            with lock:
                failed += 1
            print(f"  ✗ {k.rsplit('/',1)[-1]}  {e}", flush=True)

    if workers <= 1:
        for item in work:
            if breaker.tripped: break
            worker(item)
    else:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(worker, it) for it in work]
            for _ in cf.as_completed(futs):
                if breaker.tripped:
                    for f in futs: f.cancel()
                    break
    save_cache(cache)
    print(f"완료 · 성공 {done} / 실패 {failed}", flush=True)
    return {"done": done, "failed": failed, "tripped": breaker.tripped}


# ---------- apply to JSONs ----------
def apply_cache(cache: dict) -> dict:
    """Rewrite JSON files: replace image URL fields with extras fields.

    Only replaces fields where ALL URLs are in cache (safe partial mode).
    """
    touched = 0; skipped = 0
    for p in sorted(DATA.glob("*/*_*.json")):
        if p.name == "sessions.json": continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict):  # data/audit/*.json 등 비문항 산출물 스킵
            continue
        changed = False
        for q in d.get("questions", []):
            for src_key, dst_key in [
                ("question_images", "question_extras"),
                ("explanation_images", "explanation_extras"),
            ]:
                urls = q.get(src_key)
                if not urls: continue
                extras = [cache.get(url_key(u)) for u in urls]
                if all(extras):
                    q[dst_key] = [{"kind": e["kind"], "content": e["content"]} for e in extras]
                    del q[src_key]
                    changed = True
                else:
                    skipped += 1
            for c in (q.get("choices") or []):
                urls = c.get("images")
                if not urls: continue
                extras = [cache.get(url_key(u)) for u in urls]
                if all(extras):
                    c["extras"] = [{"kind": e["kind"], "content": e["content"]} for e in extras]
                    del c["images"]
                    changed = True
                else:
                    skipped += 1
        if changed:
            p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            touched += 1
    return {"files_updated": touched, "fields_skipped_partial": skipped}


# ---------- CLI ----------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, help="앞 N개 URL만 처리")
    ap.add_argument("--all", action="store_true", help="전체 처리")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--model", default=None, help="claude -p 모델 (sonnet/haiku 등)")
    ap.add_argument("--breaker", type=int, default=50, help="연속 실패 N회 시 중단")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--stats", action="store_true", help="진척 통계만 출력하고 종료")
    ap.add_argument("--apply", action="store_true",
                    help="캐시 기반으로 JSON을 실제로 재작성 (안전: 부분 null이면 스킵)")
    args = ap.parse_args()

    urls = collect_urls()
    paths = sorted({url_key(u) for u in urls})
    cache = load_cache()
    print(f"이미지 참조 총 {len(urls)}개 / 고유 {len(paths)}개 / 캐시된 {len(cache)}개",
          flush=True)

    if args.stats:
        from collections import Counter
        kinds = Counter(v.get("kind","?") for v in cache.values())
        print("kind 분포:", dict(kinds))
        return

    if args.apply:
        r = apply_cache(cache)
        print(f"JSON 업데이트: 파일 {r['files_updated']} · 부분 스킵 필드 {r['fields_skipped_partial']}")
        return

    if args.sample:
        work = paths[:args.sample]
    elif args.all:
        work = paths
    else:
        ap.print_help(); sys.exit(1)

    process_urls(work, workers=args.workers, dry=args.dry, model=args.model, breaker_threshold=args.breaker)


if __name__ == "__main__":
    main()

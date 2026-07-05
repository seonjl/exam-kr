"""이미지 캐시 → extras 적용 (자격증 한정판).

extract_images.py 의 apply_cache 와 동일한 비파괴 치환이지만, 지정한 자격증
디렉터리만 대상으로 한다 (다른 자격증 파일이 파이프라인 진행 중일 때 안전).

사용법:
  python3 apply_image_cache_exams.py c2 nw
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_images import DATA, load_cache, url_key  # noqa: E402


def apply_for_exam(cache: dict, exam: str) -> dict:
    touched = 0
    skipped = 0
    for p in sorted((DATA / exam).glob(f"{exam}_*.json")):
        if p.name == "sessions.json":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            continue
        changed = False
        for q in d.get("questions", []):
            for src_key, dst_key in [
                ("question_images", "question_extras"),
                ("explanation_images", "explanation_extras"),
            ]:
                urls = q.get(src_key)
                if not urls:
                    continue
                extras = [cache.get(url_key(u)) for u in urls]
                if all(extras):
                    q[dst_key] = [{"kind": e["kind"], "content": e["content"]} for e in extras]
                    del q[src_key]
                    changed = True
                else:
                    skipped += 1
            for c in (q.get("choices") or []):
                urls = c.get("images")
                if not urls:
                    continue
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
    return {"exam": exam, "files_updated": touched, "fields_skipped_partial": skipped}


def main() -> None:
    exams = sys.argv[1:]
    if not exams:
        print("usage: apply_image_cache_exams.py <exam> [exam...]")
        sys.exit(1)
    cache = load_cache()
    for ex in exams:
        print(apply_for_exam(cache, ex))


if __name__ == "__main__":
    main()

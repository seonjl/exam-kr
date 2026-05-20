"""각 회차 JSON 최상위에 comcbt 원본 메타데이터를 추가.

- `source_site`: "comcbt.com"
- `source_base_url`: fetch.py 의 DEFAULT_BASE
- `source_dbname`, `source_date`: 이미 dbname/date 로 있음 — 누락 시 채움
- `source_url`: 인덱스 페이지 URL (frameset 구조라 직접 deep link 는 불가)

비파괴 / idempotent — 이미 모든 필드가 있으면 파일을 다시 쓰지 않음.

사용법:
  python3 scripts/add_source_url.py            # 모든 자격증 전체
  python3 scripts/add_source_url.py c1         # 특정 자격증
  python3 scripts/add_source_url.py --check    # 어디까지 채워졌나만 출력
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from exams import EXAMS  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

SITE = "comcbt.com"
BASE_URL = "https://www.comcbt.com/cbt"


def session_files(exam_code: str) -> list[Path]:
    return sorted((DATA / exam_code).glob(f"{exam_code}_*.json"))


def update_file(path: Path, *, dry: bool) -> bool:
    d = json.loads(path.read_text(encoding="utf-8"))
    desired = {
        "source_site": SITE,
        "source_base_url": BASE_URL,
        "source_dbname": d.get("dbname") or path.parent.name,
        "source_date": d.get("date") or path.stem.split("_", 1)[-1],
        "source_url": f"{BASE_URL}/",
    }
    changed = False
    for k, v in desired.items():
        if d.get(k) != v:
            d[k] = v
            changed = True
    if changed and not dry:
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exam_code", nargs="?", default="all",
                    help="자격증 코드 (생략 시 전체)")
    ap.add_argument("--check", action="store_true",
                    help="변경 없이 누락 통계만 출력")
    args = ap.parse_args()

    codes = list(EXAMS.keys()) if args.exam_code == "all" else [args.exam_code]
    grand_changed = grand_total = 0
    for code in codes:
        files = session_files(code)
        if not files:
            print(f"[{code}] 회차 없음, skip")
            continue
        changed = 0
        for p in files:
            if update_file(p, dry=args.check):
                changed += 1
        print(f"[{code}] {changed}/{len(files)} 회차 갱신{' (dry)' if args.check else ''}")
        grand_changed += changed
        grand_total += len(files)
    print(f"=== 총 {grand_changed}/{grand_total} 회차 갱신 ===")


if __name__ == "__main__":
    main()

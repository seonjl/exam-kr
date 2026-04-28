"""해설 텍스트 정리 유틸리티.

해설 본문에서 외부 시스템/플랫폼의 흔적(기여자 태그, 신고 안내문 등)을
제거하고 공백·구분선을 깔끔히 정돈한다.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent / "data"

# Patterns to strip (block-level)
BLOCK_PATTERNS = [
    # "아래와 같은 오류 신고가 있었습니다. 여러분들의 ..." 부터 "[오류 신고 내용]" 블록 포함
    re.compile(r"아래와 같은 오류\s*신고[\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"다수의 오류\s*신고[^\n]*"),
    re.compile(r"참고로 정답 변경은 오류\s*신고[^\n]*"),
    re.compile(r"여러분들의 많은 의견 부탁[^\n]*"),
    re.compile(r"추후 여러분들의 의견을 반영[^\n]*"),
    re.compile(r"여러분들의 의견을 반영하여[^\n]*"),
    re.compile(r"\[오류\s*신고\s*내용\][\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"\[대표\s*오류\s*신고\s*내용\][\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"\[추가\s*오류\s*신고[^\]]*\][\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"\[오류신고[^\]]*\][\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"\[오류\s*신고\][\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"아래는\s*대표\s*오류\s*신고\s*내용[\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"\[관리자\s*입니다[^\]]*\][\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"\[관리자입니다[^\]]*\][\s\S]*?(?=(?:\n{2,}|$))"),
    re.compile(r"오타\s*및\s*오류[^\n]*"),
    re.compile(r"시험지를 스캔[^\n]*"),
    re.compile(r"기출문제 복원에 많은 참여[^\n]*"),
]

# Inline patterns — 외부 플랫폼/원본 사이트 흔적 일반화
INLINE_PATTERNS = [
    re.compile(r"\[해설작성자\s*:[^\]]*\]"),
    re.compile(r"\[추가\s*해설[^\]]*\]"),
    re.compile(r"밀양금성[^\n]*"),
    # 플랫폼/사이트 워터마크류 (구체 명칭 회피)
    re.compile(r"전자문제집[^\n]*"),
    re.compile(r"해설집보니까"),
    re.compile(r"\b해설집\b"),
    re.compile(r"오류\s*신고하신\s*분"),
    re.compile(r"오류\s*신고\s*하신"),
    re.compile(r"해설작성자"),
    re.compile(r"오류\s*신고"),
    re.compile(r"오류신고"),
]


def clean_explanation(text: str) -> str:
    if not text:
        return ""
    s = text
    for pat in BLOCK_PATTERNS:
        s = pat.sub("", s)
    for pat in INLINE_PATTERNS:
        s = pat.sub("", s)
    # Remove leading > leftovers
    s = s.replace("&gt;", "").replace("&lt;", "<")
    s = re.sub(r"^[>\s]+", "", s)
    # Compress whitespace
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # Remove orphan separator lines
    s = re.sub(r"^[-\s]{3,}$", "", s, flags=re.M)
    return s.strip()


def scrub_file(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    count_changed = 0
    for q in d["questions"]:
        orig = q.get("explanation") or ""
        cleaned = clean_explanation(orig)
        if cleaned != orig:
            q["explanation"] = cleaned
            count_changed += 1
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"file": path.name, "changed": count_changed, "total": len(d["questions"])}


def main() -> None:
    # Scan data/<code>/<code>_*.json across all exams
    files = sorted(ROOT.glob("*/*_*.json"))
    files = [f for f in files if not f.name.endswith("sessions.json")]
    total_changed = 0
    for f in files:
        r = scrub_file(f)
        total_changed += r["changed"]
        if r["changed"]:
            print(f"{f.parent.name}/{r['file']}  {r['changed']}/{r['total']}")
    print(f"\n총 {len(files)}회차, {total_changed}문항 정리 완료")


if __name__ == "__main__":
    main()

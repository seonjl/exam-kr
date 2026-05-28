#!/usr/bin/env python3
"""랜덤 샘플링 품질 검토 — 터미널 인터랙티브.

무한루프로 랜덤 문항을 보여주고 1~5점 평가 + 메모 입력.
결과는 data/audit/review_samples.jsonl 에 누적.
"""

import json, glob, random, sys, os
from datetime import datetime

AUDIT_DIR = "data/audit"
OUTPUT_FILE = os.path.join(AUDIT_DIR, "review_samples.jsonl")

# 자격증 목록
EXAM_CODES = ["s2", "g1", "g2", "iz", "sa", "c1", "k1", "kt", "nd"]

# 터미널 색상
C = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "reset": "\033[0m",
}


def load_all_questions():
    """전체 문항 로드 → [(exam_code, session_date, question_dict), ...]"""
    pool = []
    for exam in EXAM_CODES:
        files = sorted(glob.glob(f"data/{exam}/{exam}_*.json"))
        for f in files:
            with open(f) as fh:
                data = json.load(fh)
            for q in data.get("questions", []):
                pool.append((exam, data["date"], q))
    return pool


def show_question(exam, date, q, exam_names):
    name = exam_names.get(exam, exam)
    num = q.get("number", "?")
    subj = q.get("subject", "")
    question = q.get("question", "")
    choices = q.get("choices", [])
    answer = q.get("answer", "?")
    explanation = q.get("explanation", "")
    exp_det = q.get("explanation_detailed", "")
    concepts = q.get("concepts", [])
    concept_ids = q.get("concept_ids", [])
    audit = q.get("explanation_audit", {})

    print(f"\n{'='*70}")
    print(f"{C['bold']}{C['cyan']}[{name}] {date} 회차 — 문항 #{num}{C['reset']}")
    if subj:
        print(f"{C['dim']}과목: {subj}{C['reset']}")
    print(f"{'─'*70}")
    print(f"{C['bold']}{question}{C['reset']}")

    if q.get("question_images"):
        print(f"{C['yellow']}  ⚠ 이미지 문항 ({len(q['question_images'])}개){C['reset']}")

    if choices:
        for i, ch in enumerate(choices):
            marker = f" {C['green']}✓{C['reset']}" if i + 1 == answer else ""
            letter = chr(65 + i)
            print(f"  {C['bold']}{letter}.{C['reset']} {ch}{marker}")

    print(f"{'─'*70}")
    print(f"{C['bold']}원본 해설:{C['reset']}")
    if explanation:
        # 길면 잘라서
        lines = explanation.split("\n")
        for line in lines[:15]:
            print(f"  {line}")
        if len(lines) > 15:
            print(f"  {C['dim']}... ({len(lines)-15}줄 생략){C['reset']}")
    else:
        print(f"  {C['red']}(없음){C['reset']}")

    print(f"\n{C['bold']}AI 상세해설:{C['reset']}")
    if exp_det:
        lines = exp_det.split("\n")
        for line in lines[:20]:
            print(f"  {line}")
        if len(lines) > 20:
            print(f"  {C['dim']}... ({len(lines)-20}줄 생략){C['reset']}")
    else:
        print(f"  {C['red']}(없음){C['reset']}")

    if concepts:
        print(f"\n{C['bold']}추출 개념:{C['reset']} {', '.join(concepts[:10])}")
        if len(concepts) > 10:
            print(f"  {C['dim']}... 외 {len(concepts)-10}개{C['reset']}")
    if concept_ids:
        print(f"{C['bold']}정규화 개념ID:{C['reset']} {', '.join(concept_ids[:8])}")
        if len(concept_ids) > 8:
            print(f"  {C['dim']}... 외 {len(concept_ids)-8}개{C['reset']}")

    if audit:
        score = audit.get("score", "?")
        print(f"{C['dim']}자가감점: {score}/5{C['reset']}")

    print(f"{'='*70}")


def save_review(exam, date, q_num, score, memo):
    os.makedirs(AUDIT_DIR, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(),
        "exam": exam,
        "session_date": date,
        "question_number": q_num,
        "score": score,
        "memo": memo,
    }
    with open(OUTPUT_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def print_stats():
    """누적 통계 출력."""
    if not os.path.exists(OUTPUT_FILE):
        return
    scores = []
    with open(OUTPUT_FILE) as f:
        for line in f:
            r = json.loads(line)
            scores.append(r["score"])
    if not scores:
        return
    avg = sum(scores) / len(scores)
    dist = {}
    for s in scores:
        dist[s] = dist.get(s, 0) + 1
    print(f"\n{C['yellow']}📊 누적: {len(scores)}개 검토, 평균 {avg:.1f}점{C['reset']}")
    bar = ""
    for s in range(1, 6):
        pct = dist.get(s, 0)
        bar += f" {s}:{'█'*pct}{C['dim']}({pct}){C['reset']}"
    print(f"  분포:{bar}")


def main():
    # 자격증 이름 로드
    sys.path.insert(0, "scripts")
    from exams import EXAMS
    exam_names = {k: v["name"] for k, v in EXAMS.items()}

    print(f"{C['bold']}🔍 AI 추출 품질 샘플링 검토{C['reset']}")
    print(f"랜덤 문항 표시 → 1~5점 평가 + 메모")
    print(f"명령: 점수(1-5) | 점수+메모(3 문해설 구림) | s=skip | q=종료 | st=통계\n")

    pool = load_all_questions()
    print(f"전체 {len(pool):,}문항 로드 완료\n")

    random.shuffle(pool)
    idx = 0

    while idx < len(pool):
        exam, date, q = pool[idx]
        show_question(exam, date, q, exam_names)

        try:
            raw = input(f"\n{C['bold']}평가 (1~5, s=skip, q=quit): {C['reset']}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C['yellow']}종료.{C['reset']}")
            break

        if raw.lower() == "q":
            print_stats()
            break
        elif raw.lower() == "st":
            print_stats()
            continue
        elif raw.lower() == "s":
            idx += 1
            continue

        # 점수 파싱: "3" 또는 "3 메모내용"
        parts = raw.split(None, 1)
        try:
            score = int(parts[0])
        except (ValueError, IndexError):
            print(f"  {C['red']}1~5 점수 입력{C['reset']}")
            continue

        if score < 1 or score > 5:
            print(f"  {C['red']}1~5 사이로{C['reset']}")
            continue

        memo = parts[1] if len(parts) > 1 else ""

        save_review(exam, date, q.get("number", 0), score, memo)

        # 점수 피드백
        colors = {1: "red", 2: "red", 3: "yellow", 4: "green", 5: "green"}
        print(f"  {C[colors.get(score,'reset')]}✓ {score}점 기록{C['reset']}")

        if idx % 10 == 9:
            print_stats()

        idx += 1

    print_stats()
    print(f"\n결과: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

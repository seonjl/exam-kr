#!/usr/bin/env python3
"""AI 추출 품질 샘플링 검토 — 무한 반복 모드"""
import json, glob, random, sys

EXAMS = ["s2", "g1", "g2", "iz", "sa", "c1", "k1", "kt", "nd"]
EXAM_NAMES = {
    "s2": "사회조사분석사2급", "g1": "공인중개사1차", "g2": "공인중개사2차",
    "iz": "정보처리기사", "sa": "산업안전기사", "c1": "컴활1급",
    "k1": "한국사심화", "kt": "전기기사", "nd": "소방설비기사",
}

# 전체 문항 로드 (1회)
ALL_Q = []
for exam in EXAMS:
    files = sorted(glob.glob(f"data/{exam}/{exam}_*.json"))
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        date = data.get("date", "")
        for q in data["questions"]:
            ALL_Q.append({
                "exam": exam,
                "date": date,
                "num": q["number"],
                "question": q.get("question", ""),
                "choices": q.get("choices", []),
                "answer": q.get("answer"),
                "explanation": q.get("explanation", ""),
                "explanation_detailed": q.get("explanation_detailed", ""),
                "concepts": q.get("concepts", []),
                "concept_ids": q.get("concept_ids", []),
                "explanation_audit": q.get("explanation_audit"),
                "subject": q.get("subject", ""),
            })

print(f"총 {len(ALL_Q):,}문항 로드 완료\n", flush=True)

def evaluate(q):
    """품질 점수 (0~10) 및 이슈 목록 반환"""
    issues = []
    score = 10
    
    expl = q["explanation_detailed"]
    concepts = q["concepts"]
    cids = q["concept_ids"]
    
    # 해설 길이
    if not expl.strip():
        issues.append("해설 빈문자열")
        score -= 5
    elif len(expl) < 200:
        issues.append(f"해설 너무 짧음 ({len(expl)}자)")
        score -= 2
    elif len(expl) > 2000:
        issues.append(f"해설 너무 김 ({len(expl)}자)")
        score -= 1
    
    # 구조 체크
    if "핵심 개념" not in expl and "핵심개념" not in expl:
        issues.append("핵심개념 섹션 없음")
        score -= 2
    if "정답 분석" not in expl and "정답분석" not in expl:
        issues.append("정답분석 섹션 없음")
        score -= 2
    if "오답 분석" not in expl and "오답분석" not in expl:
        issues.append("오답분석 섹션 없음")
        score -= 1
    
    # 개념 체크
    if not concepts:
        issues.append("concepts 빈배열")
        score -= 2
    if not cids:
        issues.append("concept_ids 빈배열")
        score -= 2
    
    # 보기에 정답 매칭
    choices = q["choices"]
    answer = q["answer"]
    if answer is not None and choices:
        if answer < 1 or answer > len(choices):
            issues.append(f"정답 범위초과 (answer={answer}, 보기수={len(choices)})")
            score -= 3
    
    # 빈 보기
    if choices:
        empty = sum(1 for c in choices if not c.get("text", "").strip())
        if empty == len(choices):
            issues.append("모든 보기가 빈문자열")
            score -= 2
    
    return max(score, 0), issues

def print_sample(q, idx, score, issues):
    exam_name = EXAM_NAMES.get(q["exam"], q["exam"])
    print(f"{'='*60}", flush=True)
    print(f"[#{idx}] {exam_name} {q['date']}회차 Q{q['num']}", flush=True)
    print(f"과목: {q['subject'] or '(없음)'}", flush=True)
    print(f"문제: {q['question'][:100]}{'...' if len(q['question'])>100 else ''}", flush=True)
    
    # 보기
    for i, c in enumerate(q["choices"][:5]):
        txt = c.get("text", "").strip()
        marker = " ◀정답" if q["answer"] == i+1 else ""
        if txt:
            print(f"  {i+1}. {txt[:80]}{marker}", flush=True)
        else:
            has_img = bool(c.get("images") or c.get("image"))
            print(f"  {i+1}. (빔){' [이미지]' if has_img else ''}{marker}", flush=True)
    
    print(f"\n[해설] ({len(q['explanation_detailed'])}자)", flush=True)
    # 섹션별 요약
    expl = q["explanation_detailed"]
    for section in ["핵심 개념", "정답 분석", "오답 분석"]:
        idx_s = expl.find(section)
        if idx_s >= 0:
            chunk = expl[idx_s:idx_s+150].replace('\n', ' ')
            print(f"  {chunk}...", flush=True)
    
    print(f"\n[개념] {q['concepts']}", flush=True)
    print(f"[개념ID] {q['concept_ids']}", flush=True)
    
    audit = q.get("explanation_audit")
    if audit and isinstance(audit, dict):
        print(f"[자가감점] score={audit.get('score','?')} reason={audit.get('reason','')[:100]}", flush=True)
    
    if issues:
        print(f"\n⚠ 이슈: {', '.join(issues)}", flush=True)
    print(f"품질점수: {score}/10", flush=True)

# 메인 루프
mode = sys.argv[1] if len(sys.argv) > 1 else "random"
batch_size = int(sys.argv[2]) if len(sys.argv) > 2 else 10

if mode == "worst":
    # 점수 낮은 순 정렬
    scored = []
    for q in ALL_Q:
        s, iss = evaluate(q)
        scored.append((s, iss, q))
    scored.sort(key=lambda x: x[0])
    
    print(f"=== 최저품질 {batch_size}개 ===\n", flush=True)
    for i, (s, iss, q) in enumerate(scored[:batch_size]):
        print_sample(q, i+1, s, iss)

elif mode == "random":
    random.seed()
    sample = random.sample(ALL_Q, min(batch_size, len(ALL_Q)))
    print(f"=== 랜덤 샘플 {batch_size}개 ===\n", flush=True)
    for i, q in enumerate(sample):
        s, iss = evaluate(q)
        print_sample(q, i+1, s, iss)

elif mode == "stats":
    # 전체 품질 분포
    scores = []
    issue_counts = {}
    for q in ALL_Q:
        s, iss = evaluate(q)
        scores.append(s)
        for issue in iss:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    
    from collections import Counter
    sc = Counter(scores)
    print("=== 전체 품질 점수 분포 ===", flush=True)
    for k in sorted(sc.keys()):
        bar = '#' * (sc[k] // 100)
        print(f"  {k:>2}점: {sc[k]:>5}문항 {bar}", flush=True)
    
    avg = sum(scores) / len(scores)
    print(f"\n  평균: {avg:.1f}점", flush=True)
    print(f"\n=== 이슈 빈도 ===", flush=True)
    for issue, cnt in sorted(issue_counts.items(), key=lambda x: -x[1]):
        print(f"  {issue}: {cnt:,}", flush=True)

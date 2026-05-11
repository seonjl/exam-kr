# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project Context — cbt-reverse / exam.kr

CBT 기출문제 웹앱. 4개 자격증: `s2`(사회조사분석사2급), `g1`(공인중개사1차), `g2`(공인중개사2차), `iz`(정보처리기사). 단일 소스: `scripts/exams.py`.

**데이터 위치**
- 문항: `data/{exam}/{exam}_{YYYYMMDD}.json`
- 정규화 개념: `data/concepts/{exam}/{aliases.json,index.json}`

**파이프라인 (`scripts/`, 모두 idempotent)**
1. `enrich.py` — `explanation_detailed` 생성
2. `extract_concepts.py` — raw `concepts[]` + `explanation_audit`
3. `normalize_concepts.py` — `concept_ids[]` + aliases/index 산출

**규칙**
- 작업은 항상 4개 exam 코드 단위로 사고.
- 스크립트 재실행은 안전 (필드 존재 시 자동 스킵).
- claude CLI 동시성 낮음 → workers 2~4 권장.
- 코드/주석/메모리는 한국어 우선.

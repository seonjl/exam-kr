# CLAUDE.md

cbt-reverse / passcbt.kr — CBT 기출문제 웹앱 + AI 콘텐츠 파이프라인 + 감사 도구.
LLM 보조 코딩 시의 행동 원칙. 사소한 작업은 판단 우선.

---

## 1. 가정을 숨기지 마라

- 가정은 명시. 불확실하면 물어봐라.
- 해석이 두 가지 이상이면 둘 다 제시 — 조용히 한쪽 고르지 마라.
- 더 단순한 방법이 보이면 말해라. 정당하면 반대 의견 내라.
- 막히면 멈춰라. 무엇이 헷갈리는지 이름 붙여 물어라.

## 2. 단순 우선

- 요청 이상 기능 금지.
- 일회용 코드에 추상화 금지.
- 부르지 않은 "유연성/설정 가능성" 금지.
- 불가능한 시나리오에 대한 에러 처리 금지.
- 200줄을 50줄로 줄일 수 있으면 다시 써라.

시니어가 본다면 "과설계" 라 할 코드인가? 그렇다면 단순화.

## 3. 외과적 변경

- 인접 코드/주석/포맷 "개선" 금지.
- 망가지지 않은 것 리팩토링 금지.
- 기존 스타일을 따라라 — 본인이 다르게 하더라도.
- 무관한 죽은 코드는 언급만, 삭제 금지.

당신 변경이 만든 고아만 청소 — 기존 dead code 는 요청 없으면 두라.

검증: 모든 변경 라인이 사용자 요청에 직결되는가?

## 4. 검증 가능한 목표

- "validation 추가" → "잘못된 입력에 대한 테스트 작성 후 통과"
- "버그 수정" → "재현 테스트 → 통과"
- "X 리팩토링" → "전/후 테스트 통과"

다단계 작업은 짧은 계획부터:
```
1. [단계] → verify: [확인]
2. [단계] → verify: [확인]
```

강한 성공 기준은 독립적 루프를 가능하게 한다. 약한 기준 ("동작하게 만들어")는 끊임없는 확인을 요구한다.

---

# 프로젝트 컨텍스트

## 자격증 (`scripts/exams.py` 단일 소스)

현재 등록된 9종 — 작업은 가능한 한 전체 자격증 단위로 사고:

| 코드 | 이름 | 문항/회차 |
|------|------|----------|
| s2 | 사회조사분석사 2급 | 100 |
| g1 | 공인중개사 1차 | 80 |
| g2 | 공인중개사 2차 | 120 |
| iz | 정보처리기사 | 100 |
| sa | 산업안전기사 | 120 |
| c1 | 컴퓨터활용능력 1급 (필기) | 60 |
| k1 | 한국사능력검정시험 심화 | 50 |
| kt | 전기기사 | 100 |
| nd | 소방설비기사 (기계분야) | 80 |

데이터 출처: `comcbt.com/cbt`. fetch.py 의 `DEFAULT_BASE` 상수에 하드코딩 — 환경변수 override 가능.

## 데이터 레이아웃

```
data/
  {exam}/
    {exam}_{YYYYMMDD}.json     문항 (raw + AI 증강 필드)
    sessions.json              회차 manifest
  concepts/
    {exam}/
      aliases.json             원문구 → canonical concept ID
      index.json               canonical 개념 정의
      _cache/                  (gitignore)
  audit/                       감사/정정 산출물
  exams.json                   전체 자격증 manifest (FE 진입점)
```

문항 필드 (AI 가 채우는 부분):
- `explanation` — 원본 사이트 해설 (원본)
- `explanation_detailed` — enrich.py 생성 (핵심개념/정답분석/오답분석)
- `concepts[]` — extract_concepts.py raw 명사구
- `concept_ids[]` — normalize_concepts.py 정규화 ID
- `explanation_audit` — extract 단계 자가 채점
- `known_defect` — audit 가 마킹한 결함 (이미지 누락 등)
- `refetch_log`, `refetch_invalidates_ai` — 재추출 이력

## AI 파이프라인 (`scripts/`)

모두 idempotent — 필드 존재하면 자동 스킵. 중단 후 재실행 안전.

1. **`enrich.py {exam} --workers N`** — `explanation_detailed` 생성
2. **`extract_concepts.py {exam} --workers N`** — `concepts[]` + `explanation_audit`. score < 3 이면 해설 보완.
3. **`normalize_concepts.py {exam}`** — 과목 단위 클러스터링 → `concept_ids` + `data/concepts/{exam}/{aliases,index}.json`

단계 순서는 강제: enrich 끝 → extract → normalize.

호출 방식:
- `claude -p` 서브프로세스 (API 키 불필요).
- 동시성에 약함 → `--workers 2~4` 권장 (4 초과 시 빈 stderr 실패 빈발).
- `call_claude` 에 백오프 retry 3회 내장.
- `--breaker N`: 연속 실패 N회 시 자동 중단 (기본 20, safe launcher 는 50).

## 안전 launcher

여러 자격증을 직렬로 처리하면서 단계 사이 retry 와 idempotent 보장.

- `scripts/run_4exams_safe.sh` — c1/k1/kt/nd 전체 파이프라인 (workers=2, breaker=50, 단계마다 1회 재시도)
- `logs/{name}.log` 에 진행 기록 (gitignore)

다른 머신에서 이어서 진행:
```bash
git clone ...
claude login                # CLI 인증
bash scripts/run_4exams_safe.sh
```
환경변수 불필요. fetch.py 의 DEFAULT_BASE 상수 사용. 미러 사이트면 `FETCH_BASE_URL` 로 override.

## 감사 시스템

`scripts/audit_*.py` — 비파괴 정정 패턴. 원본은 `*_original`, `*_pre_*` 필드에 보존.

대표 워크플로:
1. `audit_iz_full_revalidate.py` — 자격증 전수 B1 스타일 재채점 (problem+choices 만 노출, AI answer/해설 차단)
2. `audit_iz_classify.py` — match / mismatch / defect / vision_false_defect 분류
3. `audit_iz_refetch.py` — 원본 페이지 재추출 후 diff
4. `audit_iz_apply_refetch.py` — 패치 비파괴 적용 (`refetch_log` 보존)

산출물은 `data/audit/`. 사람 검토 큐는 `REVIEW_QUEUE.md` / 자격증별 `*_REVIEW_*.md`.

## 운영 규칙

- **작업 단위는 자격증 코드** — 항상 9종 영향 가능성 점검.
- **idempotent 보장** — 모든 신규 스크립트는 같은 입력에 같은 결과, 부분 진행 후 재실행 OK.
- **비파괴 정정** — 원본 값을 `*_original` / `refetch_log` 등으로 보존 후 롤백 가능 상태 유지.
- **백그라운드 작업** — `nohup ... > logs/X.log 2>&1 &` 패턴. monitor 로 phase 전환만 받기 (개별 문항 라인 폴링 금지).
- **claude CLI 한도** — 장시간 호출 시 usage cap 발동 → circuit breaker. 한 박자 쉬고 재기동 (보통 1~3 시간 후 회복).
- **코드/주석/메모리는 한국어** 우선. 영문 식별자는 그대로.

## FE (`webapp/`)

순수 HTML/JS (빌드 없음). 데이터는 `data/exams.json` 진입점 → 자격증 picker → `data/{exam}/sessions.json` → 회차 → `{exam}_{YYYYMMDD}.json`.

진행 상태 (`localStorage`):
- `progress:{exam}:{session}` → `{ answers, wrongs[], stars[], last, mode }`
- 맞춘 갯수 = `Object.keys(answers).length - wrongs.length`

신규 자격증 추가 시 FE 자동 인식 — 별도 라우팅 코드 불필요. examMark 라벨만 `app.js` 두 곳 갱신.

## 검증이 잘 되고 있다는 신호

- diff 에 불필요 변경 줄어듦.
- 과설계로 재작성하는 일 줄어듦.
- 명확화 질문이 실수 *후* 가 아닌 *전* 에 나옴.

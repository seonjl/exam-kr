# 후속 작업 가이드 (자율 작업 종료 시점)

## 0. 자동 정정 누적 (모두 비파괴)

| 항목 | 건수 | 비고 |
|------|------|------|
| answer 필드 정정 | **18** | 9개 자격증·시기·문항 / 비파괴 (`answer_original` 보존) |
| academic_answer 추가 | **7** | source 분쟁 케이스 — answer 보존 + 학술 정답 별도 기록 |
| 해설 풀 재생성 | **15** | answer 정정 후 자동 풀 재생성 |
| A3 오답 분석 재생성 | **75** | |
| A1 포맷 정정 | **3** | |

총 **118건** 자동 정정 적용.

## 1. 즉시 가능 — 외부 의존 없음

### 1.1 정정 결과 검증
모든 자동 정정은 비파괴 (원본 보존). 검토 후 문제 없으면 사용.
```
data/audit/INTEGRITY.md          ← 종합 무결성 (먼저 보세요)
data/audit/corrections.log.json  ← 적용된 정정 로그
data/audit/known_verified.md     ← A2.known 양차 검증 결과
data/audit/REVIEW_QUEUE.md       ← 검토 보류 케이스
```

### 1.2 academic_answer 정책 결정
7건의 source 분쟁 케이스가 `academic_answer` 필드 추가됨. 웹앱에서:
- 옵션 A: `answer` 만 표시 (source 평가와 동일)
- 옵션 B: `academic_answer.answer` 도 함께 표시하고 "학술적 정답" 주석
- 옵션 C: 향후 시점에 `answer` 를 `academic_answer.answer` 로 교체

### 1.3 롤백
- `q.answer_original` → `q.answer` 로 복원
- `q.explanation_detailed_pre_full_regen` → `q.explanation_detailed` 로 복원
- `q.explanation_detailed_pre_a3` → A3 정정 롤백
- `q.explanation_detailed_pre_a1_fix` → A1 정정 롤백
- `q.academic_answer` 필드 삭제

## 2. 외부 환경 필요 — 데이터 재추출

### 2.1 5번째 선택지 누락 (807건 / 가장 큰 결함)
`scripts/fetch.py:189` 5지선다 버그 — **수정 완료**.

**다음 단계 (사용자가 실행):**
```bash
export FETCH_BASE_URL='https://...'
python3 scripts/fetch.py g1 fetch-all
python3 scripts/fetch.py g2 fetch-all
```

재추출 후 영향받은 문항 `explanation_detailed` 재생성 권장 (5번째 선택지 정보 반영):
```bash
# known_defect 필드 제거 후 enrich/extract_concepts 재실행
```

### 2.2 시각자료 누락 (79건)
이미지 재수집 필요. `data/audit/a8_review.md` 참고.

### 2.3 문제 본문 누락 (1건)
`g2_20071028#2` ㄱ/ㄴ/ㄷ 항목 누락 — 원본 페이지에서 재추출.

## 3. 사람 검토 큐 (`REVIEW_QUEUE.md`)

| 우선순위 | 건수 | 이유 |
|---------|------|------|
| P4 1차 보류 | 1 | `g2_20061029#51` 결격사유 — 법령 시점 민감 |
| P4 확장 보류 | 1 | `g2_20171028#57` 도시개발채권 — 법령 시점 민감 |
| A2.known 비합의 | 3 | `s2_20070805#56` (B1이 source에 동의), 2 inconsistent |

총 **5건** 학술/법령 전문가 검토 후 결정.

## 4. 개념 정규화 분리 권장 (P3 결과)

`data/audit/concepts_review.md` 의 split verdict 3건:
- `iz/ui-design-principles` (17 → 4 subgroups)
- `iz/requirements-process` (15 → 5 subgroups)
- `iz/dfd` (12 → 3 subgroups)

영향 범위 크므로 (aliases.json 30+ entries + 800 iz 문항 concept_ids 일부) 자동 적용 보류. 적용 시:
1. `data/concepts/iz/` 전체 백업
2. 각 split의 subgroups 정의대로 새 canonical ID 생성
3. aliases.json: 멤버 텍스트 → 새 canonical
4. 영향받는 question의 concept_ids 업데이트

## 5. B1 검증 통계 (1,088건 샘플 누적)

| Exam | 샘플 | mismatch | 적용 | mismatch률 추정 |
|------|------|----------|------|----------------|
| s2 | 391 | 11 | 9 | 2.8% |
| g1 | 141 | 4 | 1 | 2.8% |
| g2 | 661 | 30 | 7 | 6.5% |
| iz | 84 | 0 | 0 | 0% |

A2.known 11건 양차 검증: agree_with_ai 7, agree_with_source 1, inconsistent 3.

## 6. 정기 운영

```bash
# 신규 회차 데이터 추가 시
python3 scripts/audit_quality.py            # 자동 검사
python3 scripts/audit_integrity_report.py   # 무결성 갱신
python3 scripts/audit_dashboard.py          # 대시보드
```

audit 스크립트는 모두 idempotent + known_defect 자동 제외.

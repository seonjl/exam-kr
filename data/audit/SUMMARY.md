# AI 콘텐츠 품질 진단 요약

| Exam | 문항 | A2.new | A2.known | A2.multi.new | A2.multi.known | A1 | A3 | A8 |
|------|------|--------|----------|--------------|----------------|----|----|----|
| s2 | 4600 | 0 | 6 | 0 | 2 | 0 | 0 | 0 |
| g1 | 1600 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| g2 | 2400 | 0 | 1 | 0 | 1 | 0 | 0 | 0 |
| iz | 800 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## 검사 항목

- **A1** explanation_detailed 섹션 누락 (핵심 개념/정답 분석/오답 분석)
- **A2.mismatch** AI 결론(단일)과 `answer` 불일치 — 가장 신뢰할 수 있는 후보
- **A2.multi** 결론 표현에 여러 번호 등장 (혼선) — 실제 결론을 사람이 봐야 함
- **A2.no_conc** 정답 분석에서 결론 표현을 찾지 못함
- **A3** 오답 분석이 정답 외 선택지 일부를 다루지 않음
- **A4** `concept_ids[]` 가 index.json 에 없음
- **A7** 이미지 URL 형식 비정상
- **A8** 본문이 시각자료를 시사하지만 첨부 이미지 없음

## explanation_audit 점수 분포

### s2
- 총 4600 / audit 없음 0 / improved 593 (12.9%)
- score: 0=3 1=115 2=475 3=4007

### g1
- 총 1600 / audit 없음 0 / improved 481 (30.1%)
- score: 0=18 1=138 2=325 3=1119

### g2
- 총 2400 / audit 없음 0 / improved 890 (37.1%)
- score: 0=31 1=285 2=574 3=1510

### iz
- 총 800 / audit 없음 0 / improved 73 (9.1%)
- score: 1=11 2=62 3=727

## 개념 정규화 (A5/A6)

| Exam | canonical | singleton | p50 | p90 | max | mixed-subj |
|------|-----------|-----------|-----|-----|-----|------------|
| s2 | 2469 | 901 (36%) | 2 | 7 | 66 | 141 |
| g1 | 1901 | 969 (51%) | 1 | 4 | 21 | 1 |
| g2 | 3283 | 1941 (59%) | 1 | 4 | 16 | 0 |
| iz | 766 | 280 (37%) | 2 | 5 | 14 | 8 |

### 거대 클러스터 Top (과병합 의심)

**s2**
- `stratified-sampling` (66 members) — 층화표집(확률표집)
- `quota-sampling` (44 members) — 할당표본추출
- `coefficient-of-variation` (37 members) — 변동계수와 그 한계
- `semantic-differential-scale` (36 members) — 의미분화척도(어의차이척도)
- `coefficient-of-determination` (36 members) — 결정계수(R²)의 정의와 해석

# 사람 검토 큐 (정정 후보 통합)

자동 정정 미적용 후보들. 우선순위 순. 각 항목은 사람이 학술/법령 근거로 최종 판정 후 적용. (이미 적용된 906건 제외)

## 1순위: B1 1차 보류 케이스 (참고용) (0건 / 원래 2건 중)

B1 1차 6건 중 4건은 적용됨. 나머지: 1건은 AI 해설이 답키와 다른데 재검수가 답키 옳다고 판정 (g2#108, **이미 해설 재생성 적용됨**), 1건은 데이터 결함 (g2#2).

_(해당 없음 — 모두 적용 완료 또는 비대상)_

## 2순위: P4 1차 양차 합의 mismatch (1건 / 원래 2건 중)

P4 sampling 100건에서 발견 → B1 동일 프롬프트 2차 확인. 양차 합의했으나 학술 해석 모호하여 보류.

- `g2_20061029#51`: answer **2** vs AI/재검 **3** — mismatch
  - 근거: 결격사유는 집행종료·면제 후 2년 미경과자이므로 3년은 결격사유 아님

## 3순위: P4 확장 양차 합의 mismatch (1건 / 원래 5건 중)

확장 200건 sampling 에서 발견 → 2차 합의.

- `g2_20171028#57`: answer **1** vs AI/재검 **4** — mismatch
  - 근거: 도시개발채권은 무기명이 아닌 기명식(전자등록 또는 무기명 선택 가능 규정 변경 전 기준 무기명 불가)으로 발행

## 4순위: A2.known — 출처에 이미 오류 마커가 있는 케이스 (10건 / 원래 10건 중)

이미 '오류 신고가 접수된 문제' 마커 등이 박힌 문항. AI가 다른 답으로 결론. 출제자 의도와 학술적 정답이 다른 케이스 다수.

- `s2_20000920#28`: answer **1** vs AI/재검 **2** — A2.multi_mismatch.known
- `s2_20000920#48`: answer **1** vs AI/재검 **3** — A2.mismatch.known
- `s2_20070805#45`: answer **3** vs AI/재검 **2** — A2.mismatch.known
- `s2_20070805#56`: answer **1** vs AI/재검 **3** — A2.mismatch.known
- `s2_20070805#64`: answer **2** vs AI/재검 **3** — A2.multi_mismatch.known
- `s2_20070805#90`: answer **4** vs AI/재검 **2** — A2.mismatch.known
- `s2_20120826#56`: answer **3** vs AI/재검 **4** — A2.mismatch.known
- `s2_20140817#62`: answer **2** vs AI/재검 **4** — A2.mismatch.known
- `g2_20050522#79`: answer **1** vs AI/재검 **2** — A2.multi_mismatch.known
- `g2_20101024#84`: answer **2** vs AI/재검 **1** — A2.mismatch.known

---

## 일괄 처리 가이드

각 후보를 검토 후 진짜 정정이라 판정하면:
```python
# scripts/audit_apply_fixes.py 의 ANSWER_FIXES 리스트에 추가
("<exam>", "<file_label>", <number>, <from>, <to>, "근거"),
```
실행: `python3 scripts/audit_apply_fixes.py` (idempotent)

# passcbt.kr 마케팅 플레이북

`https://www.passcbt.kr` (구도메인: `exam-kr.vercel.app`) 의 트래픽 부트스트랩 + 수익화 전략.

대상 자격증 우선순위:
1. **정보처리기사 (`iz`)** — 메인. CPC 낮고 IT 광고주 단가 높아 ROI 1순위.
2. **공인중개사 1·2차 (`g1`, `g2`)** — 시험일(매년 10월 마지막 주말) 임박할 때만 ON.
3. ~~사회조사분석사 (`s2`)~~ — 시장 작아 광고 제외, 본인 학습용으로 남김.

---

## 1. 측정·트래킹 — UTM 규칙

Vercel Analytics는 URL 의 `utm_*` 파라미터를 자동 캡처해 **Top Sources / Top Pages** 에 분리해서 보여줍니다 (대시보드: vercel.com → project  → Analytics 탭). GA4 없이도 "어떤 채널에서 어디로 들어왔는지" 답이 나옵니다.

### 표준 UTM 스키마

| 파라미터 | 설명 | 값 예시 |
|---|---|---|
| `utm_source` | 매체 식별자 | `naver_search`, `cafe_dokchwisa`, `dcinside`, `everytime`, `okky`, `tistory_blog` |
| `utm_medium` | 채널 유형 | `cpc` (유료 검색), `community` (카페/커뮤니티), `referral` (백링크), `social` (SNS) |
| `utm_campaign` | 캠페인 식별 | `iz_phase1`, `iz_2026_1`, `g1_2026_d-30`, `seed_iz_2026_1_d-7` |
| `utm_term` | 키워드/문맥 | `정보처리기사_cbt`, `D-7_마무리` (옵션) |

### 링크 생성 규칙
- 항상 **회차/카테고리 페이지로 직접 링크** (홈 `/` 보내지 말 것). 이탈 폭증.
- 한글 utm_term 은 그대로 박아도 OK — Vercel Analytics 가 디코드해서 표시.

```
# 검색광고
https://www.passcbt.kr/exam/iz?utm_source=naver_search&utm_medium=cpc&utm_campaign=iz_phase1&utm_term=정보처리기사_cbt

# 커뮤니티 시딩 (특정 카페)
https://www.passcbt.kr/exam/iz/20240517?utm_source=cafe_dokchwisa&utm_medium=community&utm_campaign=iz_2026_1_d-7

# 본인 GitHub README 백링크
https://www.passcbt.kr?utm_source=github_readme&utm_medium=referral&utm_campaign=brand
```

### 6일/2주 후 보는 것 (Vercel Analytics)
1. **Top Sources**: 어디서 클릭이 오는지 (cpc vs community vs referral 비중)
2. **Top Pages**: 들어와서 어느 페이지에 머무르는지
3. **Bounce Rate**: 30 초 미만 이탈률. 60% 넘으면 랜딩 페이지·카피 매칭 실패

---

## 2. 네이버 검색광고 (파워링크) 플레이북

### 사전 준비 (1회, 광고 ON 전)
1. `searchad.naver.com` 가입 (개인 ID 가능)
2. 캠페인 3개 만들고 **게재 OFF** 상태로 셸만 준비:
   - `iz` (정보처리기사) — 항시 운영 가능
   - `g1` (공인중개사 1차) — 시험 D-30 ~ D-1 만 ON
   - `g2` (공인중개사 2차) — 시험 D-30 ~ D-1 만 ON
3. AdSense 검토 통과 알림 받은 후 ON 시작 (안 받고 시작 = 순손해).

### 입찰 원칙
- **노출 위치 5–7위** 목표. 1–4 위는 비쌈, 8위 이하는 클릭률 0 에 수렴.
- **수동 입찰가 고정**, 자동조정 OFF.
- 키워드 매치 타입: **구문일치 (phrase match)** 만. `확장검색` 은 무관 트래픽 폭탄.
- 게재 시간: 19:00–24:00 + 06:00–09:00 (수험생 폰질 시간대)
- 게재 지역: 한국 전국, 모바일 우선

### 정보처리기사 키워드 (메인 — 항시 운영)

#### 그룹 A: "CBT/기출 풀이" — 우리 콘셉트 정확 매칭 (예산 60%)
| 키워드 | 입찰가 | 비고 |
|---|---|---|
| `정보처리기사 cbt` | ₩250 | 핵심 |
| `정보처리기사 필기 cbt` | ₩200 | |
| `정보처리기사 기출 cbt` | ₩200 | |
| `정보처리기사 cbt 무료` | ₩150 | 의도 강함 |
| `정처기 cbt` | ₩150 | 줄임말, 단가 낮음 |

#### 그룹 B: "무료 + 모바일" — 차별점 매칭 (예산 25%)
| 키워드 | 입찰가 |
|---|---|
| `정보처리기사 필기 기출 무료` | ₩300 |
| `정보처리기사 기출문제 무료` | ₩400 |
| `정보처리기사 모바일 기출` | ₩200 |
| `정보처리기사 기출 앱` | ₩250 |

#### 그룹 C: "해설/풀이" — 의도 강함 (예산 15%)
| 키워드 | 입찰가 |
|---|---|
| `정보처리기사 기출 해설` | ₩400 |
| `정보처리기사 필기 해설` | ₩350 |
| `정보처리기사 기출 풀이` | ₩300 |

#### ❌ 절대 입찰 금지
- `정보처리기사` (단독) — CPC ₩2K+, 의도 분산 (학원·교재·일정·뉴스 다 섞임)
- `정보처리기사 필기` — 동일 사유, ₩1K+
- `정보처리기사 학원` — 학원 의도, 우리와 안 맞음

### 공인중개사 키워드 (보조 — 9월–10월 둘째주만 ON)

| 키워드 | 자격증 | 입찰가 |
|---|---|---|
| `공인중개사 1차 cbt` | g1 | ₩400 |
| `공인중개사 2차 cbt` | g2 | ₩400 |
| `공인중개사 1차 기출 무료` | g1 | ₩500 |
| `공인중개사 1차 기출 모바일` | g1 | ₩300 |
| `공인중개사 기출 앱` | g1+g2 | ₩300 |
| `부동산학개론 기출` | g1 (과목별) | ₩400 |
| `민법 공인중개사 기출` | g1 (과목별) | ₩400 |

### 광고 문안 (파워링크 텍스트)

**정보처리기사용**:
```
제목: 정보처리기사 기출 - 폰 풀이
설명: AI 보강 해설·핵심 개념까지. 회차별 정답·오답노트 무료. 광고 외 트래킹 없음.
표시 URL: www.passcbt.kr/exam/iz
```

**공인중개사용**:
```
제목: 공인중개사 1차 기출 - 모바일 풀이
설명: 회차별 정답·해설·오답노트 무료. AI 보강 해설로 핵심 개념까지. 회원가입 없음.
표시 URL: www.passcbt.kr/exam/g1
```

### 연결 URL 매칭 규칙
- `정보처리기사 cbt` → `/exam/iz` (회차 목록)
- `정보처리기사 2024 기출` → `/exam/iz/{최근 회차 코드}` (직접)
- `정보처리기사 기출 해설` → `/exam/iz/{최근 회차 코드}` (해설 강조)
- `공인중개사 1차 cbt` → `/exam/g1`
- `부동산학개론 기출` → `/exam/g1/{최근 회차 코드}` (과목별이지만 회차로 보냄)

---

## 3. 커뮤니티 시딩 플레이북

### 원칙
1. **노골적 광고 금지**. 차단당하면 회복 불가.
2. **개발자 톤**: "공부하려고 만든 건데 폰으로 보기 편해서 공유합니다 — 무료" — 가장 거부감 적음.
3. **시험 D-7 ~ D-1 골든 윈도우** 에만 적극. 평소엔 답글로 자연 노출.
4. **하루 1–2 카페씩 분산**. 같은 글 여러 카페 도배 = 차단.
5. **본인 글 댓글로 추가 정보 다는 척** = 조회수·노출 ↑.

### 자격증별 타겟 커뮤니티

#### 정보처리기사
| 채널 | URL | 시점 | 비고 |
|---|---|---|---|
| 독취사 | `cafe.naver.com/dokchwisa` | D-14, D-7, D-2 | 취준 자격증 글 활발 |
| 자격증 마스터 | `cafe.naver.com/jagyukmaster` | D-7 | 자격증 종합 |
| OKKY 게시판 | `okky.kr/articles` | 상시 (관련 글에 댓글) | 개발자 커뮤니티 |
| DC 정보처리기사 갤러리 | `gall.dcinside.com/mgallery/board/lists?id=informationprocessingengineer` | D-7 | 가벼운 톤으로 |
| 에브리타임 자유게시판 | (학교별 분리) | D-7 | IT학과 학교 위주 |
| 클리앙/뽐뿌 잡담 | `clien.net`, `ppomppu.co.kr` | D-3 | 일반인 IT 관심층 |

#### 공인중개사
| 채널 | URL | 시점 |
|---|---|---|
| 공인중개사 합격을 만드는 사람들 | `cafe.naver.com/wlqksek` | 9월 셋째주, 10월 첫째주 |
| 부동산스터디 | `cafe.naver.com/jaegebal` | 10월 D-7 |
| 자격증 마스터 | `cafe.naver.com/jagyukmaster` | 10월 D-7 |
| 디시 자격증 갤러리 | `gall.dcinside.com/mgallery/board/lists?id=licence` | 10월 D-7 |

### 글 템플릿 (변형해서 사용)

#### 템플릿 A — D-7 마무리용 (추천 시작점)
```
제목: 정보처리기사 D-7 마무리할 때 폰으로 기출 풀기 좋은 사이트 만들었어요

본문:
이번 회차 같이 보는 사람 있으면 참고하세요.
제가 공부하려고 만든 건데 다른 분들도 쓸 수 있게 무료로 풀어뒀습니다.

— 회차별로 100문항 폰 슬라이드로 풀이
— AI로 보강한 해설 + 핵심 개념 태그
— 오답노트, 즐겨찾기 자동 저장 (계정 불필요)
— 회원가입 / 트래킹 없음 (광고만 있음)

링크: https://www.passcbt.kr/exam/iz?utm_source=cafe_dokchwisa&utm_medium=community&utm_campaign=iz_2026_1_d-7

오답 신고 / 개선 제안은 사이트 안에 신고 버튼 있어요. 도움 됐으면 좋겠어요.
```

#### 템플릿 B — 개발자 톤 (OKKY/클리앙용)
```
제목: 자격증 기출문제 풀이 PWA 만들었습니다 (Vercel + 정적 HTML)

본문:
정보처리기사 회차별 기출문제 + AI 보강 해설을 모바일에서 풀이할 수 있는
순수 정적 PWA 만들어봤습니다. 회원가입 / 서버 / 트래킹 없이 localStorage 만 씁니다.

— Stack: Vercel 정적 호스팅, vanilla JS, Pillow 로 OG 이미지 빌드
— 9,400+ 문항 사전 prerender 해서 검색 색인 가능 (회차 페이지 = 단일 HTML)
— PWA 라 폰 홈에 추가하면 앱처럼 동작

원래 제가 공부하려고 시작했는데 다듬어보니 쓸만해서 공유합니다.
링크: https://www.passcbt.kr/?utm_source=okky&utm_medium=community&utm_campaign=launch

피드백 주시면 감사하겠습니다.
```

#### 템플릿 C — 답글용 (자연 노출)
```
관련 질문 글에 댓글로:
"폰으로 풀이할거면 https://www.passcbt.kr/exam/iz?utm_source=cafe_X&utm_medium=community&utm_campaign=reply
도 가볍습니다. 회차별 해설까지 있어요. 무료고 회원가입 없습니다."
```

### 카페별 변형 포인트
- **수만휘/독취사**: 진지한 톤, "합격 후기" 옆에 자연 끼움
- **OKKY/클리앙**: 기술적 디테일 강조 (Stack, PWA, 정적 prerender)
- **에브리타임**: 짧고 캐주얼, "ㅋㅋ 폰으로 풀려고 만들었음 ㄱ"
- **DC**: 가벼운 톤, 줄임말 OK, 노골적 광고 톤 절대 금지

---

## 4. 시험일 기반 캠페인 캘린더

> ⚠️ 정확한 일정은 큐넷(`q-net.or.kr`)에서 확인 후 본인 캘린더에 D-30 / D-7 / D-1 알람 설정.

### 정보처리기사 (`iz`) — 연 3회
- 1회 필기: 매년 **5월 둘째 주말**
- 2회 필기: 매년 **8월 마지막 주말**
- 3회 필기: 매년 **12월 첫째 주말**

각 회차마다:
- **D-30**: 네이버 광고 일 예산 ₩7K → ₩10K 로 증액
- **D-14**: 자격증 마스터 / OKKY 시딩 1차
- **D-7**: 독취사 / 디시 갤러리 시딩 2차 + 광고 일 예산 ₩15K
- **D-2**: 클리앙·뽐뿌 잡담에 답글 시딩
- **D+1**: 광고 OFF (시험 끝난 사람은 안 들어옴), 다음 회차 D-30 까지 기본 일 예산 ₩3K 유지

### 공인중개사 (`g1`, `g2`) — 연 1회
- 필기: 매년 **10월 마지막 주말**

- **9월 1주차**: 캠페인 ON, 일 예산 ₩5K
- **10월 1주차 (D-21)**: 일 예산 ₩10K, 시딩 1차
- **10월 3주차 (D-7)**: 일 예산 ₩20K, 카페 시딩 2차
- **시험 D+1**: OFF, 다음 해 9월까지 휴면

---

## 5. 평가·반복 루프

### Phase 1 (₩30K 테스트, 정보처리기사만, 7일)
**측정 지표 (Vercel Analytics + 네이버 검색광고 대시보드)**:

| 지표 | 보는 곳 | 합격 기준 |
|---|---|---|
| 키워드별 CTR | 네이버 대시보드 | **3% 이상** |
| 키워드별 CPC 평균 | 네이버 대시보드 | **₩300 이하** |
| 클릭 후 평균 체류 | Vercel Analytics, source 필터 | **45초 이상** |
| 클릭 후 PV/세션 | Vercel Analytics | **2 이상** (회차→문항 페이지 이동) |
| Bounce rate | Vercel Analytics | **60% 미만** |

→ 한 키워드라도 4개 지표 이상 통과하면 Phase 2 에서 살림. 통과 못 한 건 OFF.

### Phase 2 (₩140K 본격, 시험 D-30 ~ D+1)
- Phase 1 합격 키워드만 + 입찰가 1.5배 상향
- 매주 월요일 저녁 데이터 점검, 하위 30% 키워드 OFF, 상위 키워드 입찰 ↑
- 일 예산 ₩7K (D-30) → ₩15K (D-7) → ₩20K (D-2)

### Phase 3 (₩30K 잔여)
- AdSense ePM 측정 가능 시점 ⇒ ROAS 계산:
  - `ROAS = (AdSense 수익 from 광고 트래픽) / (네이버 광고비)`
  - **ROAS > 0.4** 면 광고 지속 (장기적으로 organic 색인 가속 효과 더 큼)
  - **ROAS > 0.8** 면 일 예산 1.5배 상향
  - **ROAS < 0.3** 이면 광고 OFF, 커뮤니티 시딩으로만 운영

---

## 6. 빠른 참조 체크리스트

### 광고 시작 전 (1회)
- [ ] AdSense 검토 통과 ← **이거 안 끝나면 시작 금지**
- [ ] Search Console + 네이버 서치어드바이저 색인 진행 중 확인
- [ ] 정보처리기사 회차 페이지 5–10 개 색인 등록 요청 완료
- [ ] 네이버 searchad 가입 + 캠페인 셸 (`iz`) 만들기
- [ ] 본인 캘린더에 D-30 / D-7 / D-1 알람 (자격증별)

### 캠페인 ON 시 (회차마다)
- [ ] UTM 박힌 연결 URL 확인
- [ ] 그룹 A/B/C 입찰가 위 표대로
- [ ] 매치 타입 = 구문일치
- [ ] 일 예산 한도 ₩5K (Phase 1) ~ ₩20K (D-2)
- [ ] 게재 시간 19:00–24:00 + 06:00–09:00

### 매주 월요일 점검
- [ ] Vercel Analytics → Sources 별 PV/체류 확인
- [ ] 네이버 검색광고 → 키워드별 CTR/CPC
- [ ] 하위 30% 키워드 OFF, 상위 입찰 ↑
- [ ] AdSense 통과 후 → ePM 도 보기 시작

### 시험 D+1
- [ ] 광고 일 예산 → 기본값으로 복귀 (₩3K)
- [ ] 다음 회차 D-30 알람 재확인

---

## 7. 안 하는 것 (저예산에 비효율)

- ❌ 인스타/페이스북 광고 — 수험생 의도 매칭 약함
- ❌ YouTube 광고 — CPM 높고 CTR 낮음
- ❌ 구글 디스플레이 네트워크 — 검색 의도 없는 트래픽
- ❌ 카페 유료 광고 (운영자에게 직접 결제) — ₩30–80K/주, 검색광고만 못함
- ❌ 백링크 구매 / 가짜 리뷰 — 구글 SpamBrain 페널티 위험
- ❌ GA4 (지금) — Vercel Analytics 만으로 Phase 1·2 충분. 월 PV 1만+ 넘어가고 funnel·event 분석 필요해질 때 도입.

---

## 부록: 자주 쓰는 UTM 링크 모음 (복붙용)

```
# 정보처리기사 — 검색광고 그룹 A
https://www.passcbt.kr/exam/iz?utm_source=naver_search&utm_medium=cpc&utm_campaign=iz_phase1&utm_term=정보처리기사_cbt

# 정보처리기사 — 커뮤니티 (D-7 시딩, 카페별로 utm_source 만 바꿔서)
https://www.passcbt.kr/exam/iz?utm_source=cafe_dokchwisa&utm_medium=community&utm_campaign=iz_2026_1_d-7
https://www.passcbt.kr/exam/iz?utm_source=cafe_jagyukmaster&utm_medium=community&utm_campaign=iz_2026_1_d-7
https://www.passcbt.kr/exam/iz?utm_source=okky&utm_medium=community&utm_campaign=iz_2026_1_d-7
https://www.passcbt.kr/exam/iz?utm_source=dcinside&utm_medium=community&utm_campaign=iz_2026_1_d-7
https://www.passcbt.kr/exam/iz?utm_source=clien&utm_medium=community&utm_campaign=iz_2026_1_d-7

# 공인중개사 — 검색광고 (10월에만 ON)
https://www.passcbt.kr/exam/g1?utm_source=naver_search&utm_medium=cpc&utm_campaign=g1_2026&utm_term=공인중개사_1차_cbt
https://www.passcbt.kr/exam/g2?utm_source=naver_search&utm_medium=cpc&utm_campaign=g2_2026&utm_term=공인중개사_2차_cbt

# 본인 GitHub README / 블로그 백링크
https://www.passcbt.kr?utm_source=github_readme&utm_medium=referral&utm_campaign=brand
https://www.passcbt.kr?utm_source=tistory&utm_medium=referral&utm_campaign=blog
```

# passcbt.kr · 자격증 기출 학습

사회조사분석사 2급 / 공인중개사 1·2차 / 정보처리기사 / 산업안전기사 기출문제를
모바일에서 슬라이드로 풀이·해설할 수 있는 정적 웹앱.

## 구성

```
webapp/
  index.html             단일 파일 웹앱 (HTML + CSS + JS, 빌드 없음)
  manifest.webmanifest   PWA 매니페스트 (홈 화면 설치 지원)
  icon.svg               앱 아이콘
data/
  exams.json             자격증 인덱스
  <code>/sessions.json   회차 인덱스
  <code>/<code>_YYYYMMDD.json  회차별 문제/보기/정답/해설 JSON
scripts/
  fetch.py               기출 데이터 수집 스크립트 (FETCH_BASE_URL 환경변수 필요)
  scrub.py               해설 텍스트 정리 유틸
  enrich.py              해설 AI 증강 스크립트 (Claude Code CLI 호출)
  extract_concepts.py    문항별 핵심 개념 추출 + 해설 감사·자동 보완
  normalize_concepts.py  raw 개념 phrase → canonical_id 정규화
```

## 실행

```bash
python3 -m http.server 8765 --bind 0.0.0.0
```

- PC: http://localhost:8765/webapp/
- 폰 (같은 와이파이): http://<PC의 LAN IP>:8765/webapp/

폰 브라우저에서 **홈 화면에 추가**하면 네이티브 앱처럼 전체화면으로 열립니다.

## 앱 기능

- **홈**: 자격증 → 회차 → 문제. 진도/완료 상태 표시.
- **즐겨찾기**: 북마크한 문제 모아보기.
- **오답노트**: 풀이 중 틀린 문제 자동 수집.
- **설정**: 테마(자동·밝게·어둡게), 진도 내보내기/가져오기(JSON), 초기화.

### 풀이 화면
- **풀이 모드**: 보기 탭 → 즉시 정답·오답 판정 + 해설 펼침.
- **해설 모드**: 정답·해설 바로 노출. 리뷰용.
- **가로 스와이프**: 이전/다음 문제 (스크롤-스냅, 키보드 ←/→ 지원).
- **문제 패드 시트**: 하단 중앙 버튼 → 100개 번호 그리드에서 정답/오답/북마크 상태 한눈에.
- **엣지 스와이프**: 왼쪽 가장자리에서 오른쪽으로 스와이프 → 뒤로가기.

## 디자인

**한지와 먹 (Hanji & Ink)** — 학자의 서재 미학 기반 warm-paper + 먹 잉크 팔레트.
- 디스플레이 서체: Gowun Batang
- 본문 UI: Pretendard Variable
- 숫자/레이블: Space Mono
- 단일 액센트: 주홍 `#b91c1c` / 정답: 비취 `#3d6b4a` / 인장: `#a04020`
- 종이결 노이즈: SVG `feTurbulence` inline
- 라이트/다크: 시스템 팔레트 자동 감지 + 수동 전환

## 프라이버시

- 진도·북마크·답안은 브라우저 `localStorage` 에만 저장 (서버 전송 없음).
- 계정·로그인 없음. 앱 삭제 또는 설정 → 초기화 시 모두 사라짐.
- 진도 내보내기로 JSON 백업 가능.

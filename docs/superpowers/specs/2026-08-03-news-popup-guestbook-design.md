# 홈 업데이트 뉴스 팝업 + 방명록 (익명 댓글) 설계

2026-08-03. 사용자 요청: "홈화면에서 팝업으로 업데이트뉴스라던가, 유저들이 익명댓글도 쓸수있는것도 하나 만들어줘"
사용자 선택: 방명록은 홈 화면 하나 · 선택적 닉네임 · 뉴스는 news.json 수동 관리.

## ① 업데이트 뉴스 팝업

- **데이터**: `data/news.json` — `{ items: [{ id(증가 정수), date, title, body }] }` 최신순.
  배포 때 운영자(또는 Claude)가 항목을 수동 추가.
- **동작**: 홈 렌더 시 fetch → `localStorage(newsSeen)` 보다 큰 id 가 있으면 기존 시트 UI(showSheet)로
  1회 팝업, 열람 시 seen 갱신. 딥링크로 다른 화면이 위에 있으면 생략(풀이 방해 금지) — 다음 홈 방문 때 노출.
- **재열람**: 홈 하단 "업데이트 소식" 링크.
- 백엔드 없음. `/data/*` 는 max-age=0 이라 배포 즉시 갱신(SW SWR 특성상 최대 1회 방문 지연 허용).

## ② 홈 방명록 (익명 댓글)

- **저장소**: 기존 연결된 Vercel KV(Upstash Redis, presence.js 와 동일 인스턴스). Redis list `gb:items`,
  항목은 `{id, nick, msg, ts}` JSON 문자열. LPUSH + LTRIM 으로 최근 500개 보존.
- **API** `api/comments.js`:
  - `GET` → `{ ok, items }` 최근 30개, warm-instance 30초 캐시 (POST 시 무효화)
  - `POST { nick?, message }` → 201. origin 허용목록 + IP 분당 3회 레이트리밋(feedback.js 패턴),
    닉네임 20자·내용 2~500자 제한
  - `DELETE ?id=&key=` → env `COMMENTS_ADMIN_KEY` 로 스팸 삭제(미설정 시 503)
  - KV env 미설정 시 GET 이 `ok:false` → FE 는 섹션 숨김(presence 패턴)
- **FE**: 홈 examList 아래 `#guestbook` 섹션(기본 hidden) — 목록 + 닉네임(선택)/내용 입력.
  렌더는 `textContent`(XSS 차단). 작성자 표시는 `nick || '익명'`.
- **SEO/AdSense**: 프리렌더에 미포함 — UGC 를 크롤러에 노출하지 않음. 홈은 광고 미로드 화면 유지.
- **SW**: `sw.js` 에 `/api/` 캐시 우회 추가 (기존 cacheFirst 가 GET /api/comments 를 영구 캐시하는 문제 예방).

## 배포/검증

- asset: app.js `?v=35`, app.css `?v=27`, sw `VERSION v37`. vercel.json functions 에 comments 등록.
- 검증: `node --check` 3파일 → 로컬 `build_pages.py` → 푸시 → live `/sw.js` 로 v37 감지 →
  GET/POST `/api/comments` 라이브 확인, 홈에서 방명록·팝업 동작 확인.

## 제외 (YAGNI)

문항별 댓글, 대댓글, 좋아요, 금칙어 필터, 뉴스 자동 생성. 스팸이 실제로 발생하면 금칙어/차단을 추가한다.

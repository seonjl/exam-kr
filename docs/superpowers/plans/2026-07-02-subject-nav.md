# 과목 넘기기 바 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 퀴즈 화면 헤더 아래에 항상 보이는 전용 바를 두어 과목 이전/다음(각 과목 첫 문제로) 이동을 1탭으로 제공한다.

**Architecture:** 순수 클라이언트 SPA(`webapp/app.js` 단일 파일 + `webapp/app.css`). 문항은 가로 페이지 스와이프로 이동하며 `pages.scrollTo({left: idx*clientWidth})` 로 특정 문항 점프. 과목은 `q.subject`("N과목 : 명") 연속 블록. 새 바는 과목 그룹을 계산해 인접 그룹 첫 문항으로 스크롤하고, 기존 문항변경 훅(`updatePositionIndicators`)에서 라벨·버튼상태를 갱신한다.

**Tech Stack:** Vanilla ES module JS, CSS custom properties(테마 토큰). 빌드/유닛테스트 프레임워크 없음 → 검증은 `node --input-type=module --check`(구문) + grep + 브라우저 수동 확인.

---

## File Structure

- Modify: `webapp/app.js` — 헬퍼 4개, openQuiz 템플릿/핸들러, updatePositionIndicators 훅.
- Modify: `webapp/app.css` — `.subject-bar` 스타일.
- Modify: `webapp/index.html`, `webapp/sw.js` — asset 버전 bump.

---

### Task 1: 과목 그룹 헬퍼 + CSS

**Files:**
- Modify: `webapp/app.js` (함수 선언은 hoist 되므로 `function updatePositionIndicators(){` 바로 위에 삽입 — 현재 line 2527 부근)
- Modify: `webapp/app.css` (`.seo-content` 블록 뒤, 아무 안정적 위치)

- [ ] **Step 1: app.js 에 헬퍼 4개 추가**

`function updatePositionIndicators(){` 선언 바로 앞에 삽입:

```javascript
// 과목 넘기기 — 문항 배열을 과목 그룹으로 (첫 등장 순서, 연속 블록).
function subjectGroups(questions){
  const groups = [];
  const seen = new Set();
  (questions || []).forEach((q, idx) => {
    const raw = ((q && q.subject) || '').trim();
    if (!raw) return;
    if (!seen.has(raw)) { seen.add(raw); groups.push({ raw, firstIdx: idx }); }
  });
  return groups;
}
// "1과목 : 사회통계" → "1과목 · 사회통계"
function subjectLabel(raw){
  return (raw || '').replace(/\s*:\s*/, ' · ').trim();
}
// 현재 문항 index 가 속한 과목 그룹 index.
function currentSubjectGroupIndex(groups, idx){
  let gi = 0;
  for (let i = 0; i < groups.length; i++){
    if (groups[i].firstIdx <= idx) gi = i; else break;
  }
  return gi;
}
// 과목바 라벨·버튼상태 갱신. 과목 2개 미만이면 바 숨김.
function updateSubjectBar(){
  const c = state.current; if (!c) return;
  const bar = c.screen.querySelector('#subjectBar'); if (!bar) return;
  const groups = c._subjGroups || [];
  if (groups.length < 2) { bar.hidden = true; return; }
  bar.hidden = false;
  const gi = currentSubjectGroupIndex(groups, c.idx);
  c.screen.querySelector('#subjCur').textContent = subjectLabel(groups[gi].raw);
  c.screen.querySelector('#subjPrev').disabled = gi <= 0;
  c.screen.querySelector('#subjNext').disabled = gi >= groups.length - 1;
}
```

- [ ] **Step 2: app.css 에 `.subject-bar` 스타일 추가**

`.seo-content .aff-disclosure { ... }` 규칙 뒤(또는 파일 내 안정적 위치)에 삽입:

```css
/* 과목 넘기기 바 (퀴즈 화면) */
.subject-bar{
  display:flex; align-items:center; justify-content:space-between;
  gap:8px; padding:6px 12px;
  background:var(--paper);
  border-bottom:1px solid var(--paper-edge);
}
.subject-bar[hidden]{ display:none; }
.sb-cur{
  flex:1; text-align:center;
  font-family:var(--serif); font-weight:700; font-size:13px; color:var(--ink);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.sb-nav{
  display:inline-flex; align-items:center; gap:2px;
  font-size:12px; color:var(--ink-soft);
  background:none; border:none; padding:4px 6px; cursor:pointer;
  white-space:nowrap;
}
.sb-nav svg{ width:16px; height:16px; }
.sb-nav.next svg{ transform:rotate(180deg); }
.sb-nav:disabled{ opacity:.32; cursor:default; }
.sb-nav:active:not(:disabled){ opacity:.6; }
```

- [ ] **Step 3: 구문 검사**

Run: `node --input-type=module --check < webapp/app.js && echo OK`
Expected: `OK` (파싱 성공)

- [ ] **Step 4: 커밋**

```bash
git add webapp/app.js webapp/app.css
git commit -m "feat(quiz): 과목 넘기기 헬퍼·스타일 추가"
```

---

### Task 2: openQuiz 에 과목바 markup + 그룹 계산 + prev/next 핸들러

**Files:**
- Modify: `webapp/app.js` — openQuiz 템플릿(현재 `${renderConceptBanner(examCode)}` 줄, line 1558 부근), state.current 객체(line 1626-1633), 핸들러 배선부(line 1584 부근).

- [ ] **Step 1: 과목바 markup 삽입**

openQuiz 템플릿에서 아래 줄:

```javascript
    ${renderConceptBanner(examCode)}
    <div class="progress"><div class="progress-fill" id="pFill"></div></div>
```

을 다음으로 교체(헤더 → 과목바 → 배너 → 진도바):

```javascript
    <div class="subject-bar" id="subjectBar" hidden>
      <button class="sb-nav" id="subjPrev" type="button" aria-label="이전 과목">${icons.back}<span>이전 과목</span></button>
      <span class="sb-cur" id="subjCur"></span>
      <button class="sb-nav next" id="subjNext" type="button" aria-label="다음 과목"><span>다음 과목</span>${icons.back}</button>
    </div>
    ${renderConceptBanner(examCode)}
    <div class="progress"><div class="progress-fill" id="pFill"></div></div>
```

- [ ] **Step 2: state.current 에 `_subjGroups` 추가**

`state.current = {` 객체(line 1626-1633)의 `studyStartAt: Date.now(),` 줄 뒤에 추가:

```javascript
      _subjGroups: subjectGroups(data.questions),
```

- [ ] **Step 3: prev/next 핸들러 배선**

openQuiz 핸들러 배선부에서 `screen.querySelector('#jumpBtn').onclick = openJumpSheet;` 줄 뒤에 추가:

```javascript
  const goSubject = (delta) => {
    const c = state.current; if (!c) return;
    const groups = c._subjGroups || [];
    if (groups.length < 2) return;
    const gi = currentSubjectGroupIndex(groups, c.idx);
    const t = gi + delta;
    if (t < 0 || t >= groups.length) return;
    const $pages = screen.querySelector('#pages');
    if ($pages) $pages.scrollTo({ left: groups[t].firstIdx * $pages.clientWidth, behavior: 'smooth' });
  };
  screen.querySelector('#subjPrev').onclick = () => goSubject(-1);
  screen.querySelector('#subjNext').onclick = () => goSubject(1);
```

- [ ] **Step 4: 구문 검사**

Run: `node --input-type=module --check < webapp/app.js && echo OK`
Expected: `OK`

- [ ] **Step 5: markup 삽입 확인**

Run: `grep -c 'id="subjectBar"' webapp/app.js`
Expected: `1`

- [ ] **Step 6: 커밋**

```bash
git add webapp/app.js
git commit -m "feat(quiz): 과목바 markup·그룹계산·이전다음 핸들러"
```

---

### Task 3: 문항 변경 시 과목바 갱신 훅

**Files:**
- Modify: `webapp/app.js` — `updatePositionIndicators()` 내부(#quizSub 세팅 줄, line 2534 부근).

- [ ] **Step 1: updatePositionIndicators 에 updateSubjectBar 호출 추가**

아래 줄:

```javascript
  c.screen.querySelector('#quizSub').textContent = q.subject || '';
```

뒤에 추가:

```javascript
  updateSubjectBar();
```

(updatePositionIndicators 는 초기 로드 line 1652 및 스크롤 문항변경 line 1676 에서 호출되므로 최초 표시·경계 넘김 갱신이 모두 처리됨.)

- [ ] **Step 2: 구문 검사**

Run: `node --input-type=module --check < webapp/app.js && echo OK`
Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git add webapp/app.js
git commit -m "feat(quiz): 문항 변경 시 과목바 라벨·버튼상태 갱신"
```

---

### Task 4: asset 버전 bump + 수동 검증

**Files:**
- Modify: `webapp/index.html` (app.js/app.css 쿼리), `webapp/sw.js` (VERSION).

- [ ] **Step 1: 현재 버전 확인**

Run: `grep -oE 'app\.(js|css)\?v=[0-9]+' webapp/index.html; grep "const VERSION" webapp/sw.js`
Expected: 현재 값 출력 (예: app.js?v=22 / app.css?v=19 / v25). 각 +1 로 bump 할 값 결정.

- [ ] **Step 2: 버전 bump**

`webapp/index.html` 의 `app.js?v=N`, `app.css?v=M` 을 각각 N+1, M+1 로, `webapp/sw.js` 의 `const VERSION = 'vK'` 를 vK+1 로 수정. (Edit 로 정확한 문자열 교체)

- [ ] **Step 3: 커밋**

```bash
git add webapp/index.html webapp/sw.js
git commit -m "chore: 과목바 반영 asset 버전 bump"
```

- [ ] **Step 4: 수동 브라우저 검증 (사용자/verify 스킬)**

로컬 서빙(예: `python3 -m http.server` 로 repo 루트) 후 브라우저에서:
1. 다과목 시험(예: iz 5과목) 회차 열기 → 헤더 아래 과목바 표시, 가운데 "1과목 · 소프트웨어 설계".
2. `다음 과목 ›` 탭 → 2과목 첫 문제로 이동, 라벨 "2과목 · …". `‹ 이전 과목` 탭 → 1과목 첫 문제.
3. 좌우 스와이프로 과목 경계를 넘으면 가운데 라벨·버튼 활성상태 자동 갱신.
4. 1과목에서 `‹ 이전 과목` 비활성(dim), 마지막 과목에서 `다음 과목 ›` 비활성.
5. 단일과목/과목없음 세션(있다면) → 과목바 숨김.
6. 라이트·다크 테마에서 스타일 정상.

Expected: 위 6개 모두 통과.

---

## Self-Review 결과

- **Spec coverage:** 배치(전용 바)=Task2, 이전/다음 동작=Task2, 라벨·버튼갱신=Task3, 엣지(첫/끝 비활성·단일과목 숨김)=Task1 updateSubjectBar, 파싱=Task1 subjectLabel, 검증=Task4. 전 항목 커버.
- **Placeholder scan:** 없음 (모든 코드 실물).
- **Type consistency:** `subjectGroups`→`{raw,firstIdx}`, `currentSubjectGroupIndex(groups,idx)`, `updateSubjectBar()`, `_subjGroups`, DOM id `subjectBar/subjPrev/subjNext/subjCur` — Task 전반 일치 확인.

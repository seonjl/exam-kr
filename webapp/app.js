/* ===================================================================
   기출 학습 앱 · 멀티 자격증 지원
   ================================================================== */
const DATA = '/data/';
const STORE = 'examkr.v1.';

// One-time migration from previous STORE prefix. Copies (not moves) so a stale
// build can still read its own data; idempotent via a marker key.
// Wrapped in try/catch — a quota or storage error here must not break module load.
try {
  const OLD = 'cbt.v2.';
  if (OLD !== STORE && localStorage.getItem(STORE + '_migrated') !== '1') {
    let n = 0;
    const oldKeys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(OLD)) oldKeys.push(k);
    }
    for (const k of oldKeys) {
      const newKey = STORE + k.slice(OLD.length);
      if (localStorage.getItem(newKey) === null) {
        try { localStorage.setItem(newKey, localStorage.getItem(k)); n++; }
        catch (e) { console.warn('[migrate] quota for', newKey); break; }
      }
    }
    try { localStorage.setItem(STORE + '_migrated', '1'); } catch {}
    if (n) console.info(`[migrate] copied ${n} keys from ${OLD} to ${STORE}`);
  }
} catch (e) { console.warn('[migrate] skipped:', e); }

// 전역 에러 캡처 — silent crash 추적용 (console-only).
window.addEventListener('error', (e) => {
  console.error(`[ERR] ${e.message} @ ${e.filename}:${e.lineno}:${e.colno}`, e.error);
});
window.addEventListener('unhandledrejection', (e) => {
  console.error(`[REJ]`, e.reason);
});

// AdSense — Auto Ads는 HTML <head>의 adsbygoogle.js 스크립트가 자동 처리.
// 슬롯 ID를 채우면 같은 스크립트를 사용해 수동 슬롯(<ins class="adsbygoogle">)도 함께 활성화.
//   - postAnswer: rendered immediately under the explanation in the quiz screen
//                 (high-attention placement: user is reading the answer/해설).
const ADSENSE = {
  client: 'ca-pub-1443771548671737',
  slots: { homeBanner: '', interstitial: '', postAnswer: '' },
};
function loadAdSense(){ /* no-op — script is loaded synchronously in the page head */ }
function adInsHTML(slot, opts={}){
  if (!ADSENSE.client || !slot) return '';
  const fmt = opts.format || 'auto';
  const fullWidth = opts.fullWidth !== false;
  return `<ins class="adsbygoogle" style="display:block" data-ad-client="${ADSENSE.client}" data-ad-slot="${slot}" data-ad-format="${fmt}"${fullWidth?' data-full-width-responsive="true"':''}></ins>`;
}
function pushAd(rootEl){
  if (!ADSENSE.client || !window.adsbygoogle) return;
  const ins = rootEl?.querySelector('.adsbygoogle:not([data-adsbygoogle-status])');
  if (!ins) return;
  try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch {}
}

const state = {
  exams: [],                  // [{code, name, sessions, questions, ...}]
  examByCode: new Map(),      // examCode → exam meta
  sessionsCache: new Map(),   // examCode → [session meta]
  sessionMap: new Map(),      // examCode → Map(sessionCode → session meta)
  dataCache: new Map(),       // "examCode:sessionCode" → loaded session JSON
  conceptIndex: new Map(),    // examCode → index.json (canonical id → meta)
  tab: 'home',
  currentExam: null,          // selected exam code (for session-list screen)
  current: null,              // { examCode, code, data, idx, mode, screen }
};

/* ---- storage (namespaced by examCode+sessionCode) ---- */
const store = {
  get: k => { try { return JSON.parse(localStorage.getItem(STORE+k) || 'null'); } catch { return null; } },
  set: (k,v) => localStorage.setItem(STORE+k, JSON.stringify(v)),
  del: k => localStorage.removeItem(STORE+k),
};
function progressKey(examCode, sessionCode) { return `progress:${examCode}:${sessionCode}`; }
function progressFor(examCode, sessionCode) {
  return store.get(progressKey(examCode, sessionCode)) || { answers:{}, stars:[], wrongs:[], mode:'practice', last:0 };
}
function saveProgress(examCode, sessionCode, p) { store.set(progressKey(examCode, sessionCode), p); maybeAutoBackup(); }

/* ---- theme ---- */
(function(){
  const saved = store.get('theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
})();
function setTheme(t){
  if (t==='system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', t);
  if (t==='system') store.del('theme'); else store.set('theme', t);
}
function currentTheme(){
  return document.documentElement.getAttribute('data-theme') || 'system';
}

/* ---- font size ---- */
(function(){
  const fs = store.get('fontSize');
  if (fs) document.documentElement.setAttribute('data-fs', fs);
})();
function setFontSize(fs){
  if (fs === 'md') { document.documentElement.removeAttribute('data-fs'); store.del('fontSize'); }
  else { document.documentElement.setAttribute('data-fs', fs); store.set('fontSize', fs); }
}
function currentFontSize(){
  return document.documentElement.getAttribute('data-fs') || 'md';
}

/* ---- auto-backup (every 5min on writes) ---- */
let _lastAutoBackup = 0;
function maybeAutoBackup(){
  const now = Date.now();
  if (now - _lastAutoBackup < 5 * 60 * 1000) return;
  _lastAutoBackup = now;
  try { backupCurrent(); } catch {}
}

/* ---- data ---- */
async function loadExams(){
  if (state.exams.length) return state.exams;
  const r = await fetch(DATA + 'exams.json', { cache: 'no-cache' });
  if (!r.ok) throw new Error('exams.json 없음');
  const j = await r.json();
  state.exams = j.exams;
  state.examByCode = new Map(j.exams.map(e => [e.code, e]));
  return j.exams;
}
async function loadSessions(examCode){
  if (state.sessionsCache.has(examCode)) return state.sessionsCache.get(examCode);
  const r = await fetch(DATA + `${examCode}/sessions.json`, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${examCode}/sessions.json 없음`);
  const j = await r.json();
  state.sessionsCache.set(examCode, j.sessions);
  state.sessionMap.set(examCode, new Map(j.sessions.map(s => [s.code, s])));
  return j.sessions;
}
async function loadSession(examCode, sessionCode){
  const key = `${examCode}:${sessionCode}`;
  if (state.dataCache.has(key)) return state.dataCache.get(key);
  const r = await fetch(DATA + `${examCode}/${examCode}_${sessionCode}.json`, { cache: 'no-cache' });
  if (!r.ok) throw new Error('회차 데이터 없음');
  const d = await r.json();
  if (Array.isArray(d.questions)) {
    d.questions = d.questions.filter(q => !q.hidden);
    d.count = d.questions.length;
  }
  state.dataCache.set(key, d);
  return d;
}

async function loadConceptIndex(examCode){
  if (state.conceptIndex.has(examCode)) return state.conceptIndex.get(examCode);
  try {
    const r = await fetch(DATA + `concepts/${examCode}/index.json`, { cache: 'no-cache' });
    if (!r.ok) throw new Error('no concept index');
    const j = await r.json();
    state.conceptIndex.set(examCode, j);
    return j;
  } catch {
    state.conceptIndex.set(examCode, null);   // negative cache
    return null;
  }
}

/* ---- content renderers (extras) ---- */
const _rendererLoaded = { katex: false, mermaid: false };
async function ensureRenderers(needs = { katex: true, mermaid: true }){
  if (needs.katex && !_rendererLoaded.katex && !window.katex) {
    _rendererLoaded.katex = true;
    await import('https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.mjs').then(m => { window.katex = m.default || m; }).catch(()=>{});
  }
  if (needs.mermaid && !_rendererLoaded.mermaid && !window.mermaid) {
    _rendererLoaded.mermaid = true;
    try {
      const m = await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs');
      window.mermaid = m.default || m;
      window.mermaid.initialize({ startOnLoad: false,
        theme: (document.documentElement.getAttribute('data-theme')==='dark' || matchMedia('(prefers-color-scheme:dark)').matches) ? 'dark' : 'default',
        securityLevel: 'loose',
        fontFamily: "'Pretendard Variable', 'Noto Sans KR', sans-serif",
      });
    } catch { _rendererLoaded.mermaid = false; }
  }
}

function detectSessionRendererNeeds(questions){
  const kinds = new Set();
  const collectKinds = arr => { for (const e of (arr || [])) if (e && e.kind) kinds.add(e.kind); };
  for (const q of questions || []) {
    collectKinds(q.question_extras);
    collectKinds(q.explanation_extras);
    for (const c of (q.choices || [])) collectKinds(c.extras);
    if (typeof q.explanation_detailed === 'string') {
      if (q.explanation_detailed.includes('$$')) kinds.add('formula');
      if (q.explanation_detailed.includes('```mermaid')) kinds.add('diagram');
    }
  }
  return { katex: kinds.has('formula'), mermaid: kinds.has('diagram') };
}

function renderExtra(extra){
  // returns HTML string
  const kind = extra.kind || 'text';
  const raw = extra.content || '';
  if (kind === 'formula') return renderFormula(raw);
  if (kind === 'diagram') return renderDiagram(raw);
  if (kind === 'table')   return renderMarkdown(raw);
  return renderMarkdown(raw); // text / mixed
}

function renderMathBlock(tex){
  const t = (tex || '').trim();
  if (window.katex) {
    try { return window.katex.renderToString(t, { throwOnError: false, displayMode: true }); }
    catch { /* fall through to placeholder */ }
  }
  return `<code class="formula-pending" data-tex="${escapeHtml(t)}">${escapeHtml(t)}</code>`;
}

// Extract $$...$$ to placeholders, escape surrounding text, then re-insert KaTeX HTML.
// Use this anywhere mixed text + math goes through escapeHtml — the naive order
// (escape first, then KaTeX) corrupts the LaTeX inside the dollars; the reverse
// (KaTeX first, then escape) re-escapes the rendered <span class="katex">.
function escapeWithMath(s){
  if (!s) return '';
  const parts = [];
  const tag = `__GSTACKMATH${Date.now()}__`;
  const escaped = s.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => {
    const i = parts.length; parts.push(tex); return `${tag}${i}__`;
  });
  let html = escapeHtml(escaped);
  for (let i = 0; i < parts.length; i++) {
    html = html.split(`${tag}${i}__`).join(renderMathBlock(parts[i]));
  }
  return html;
}

function renderFormula(s){
  return `<div class="extra formula">${(s || '').replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => renderMathBlock(tex))}</div>`;
}

function renderPendingFormulas(scope){
  if (!scope || !window.katex) return;
  scope.querySelectorAll('code.formula-pending').forEach(el => {
    const tex = el.dataset.tex;
    if (!tex) return;
    try {
      const tmp = document.createElement('div');
      tmp.innerHTML = window.katex.renderToString(tex, { throwOnError: false, displayMode: true });
      el.replaceWith(...tmp.childNodes);
    } catch {}
  });
}

function renderDiagram(s){
  const m = s.match(/```mermaid\s*([\s\S]+?)```/);
  if (!m) return `<pre class="extra">${escapeHtml(s)}</pre>`;
  const code = m[1].trim();
  const id = 'mmd_' + Math.random().toString(36).slice(2, 10);
  // Return a placeholder; actual render happens after mount via renderPendingMermaid
  return `<div class="extra diagram"><div class="mmd" data-id="${id}" data-src="${encodeURIComponent(code)}"></div></div>`;
}

function renderMarkdown(s){
  // Minimal markdown: tables, code blocks, preserve newlines + KaTeX $$
  let html = s;
  // code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
    `<pre class="code"><code>${escapeHtml(code)}</code></pre>`);
  // tables
  html = html.replace(/(^\|.+\|\n\|[\s\-:|]+\|\n(?:\|.+\|\n?)+)/gm, (block) => {
    const rows = block.trim().split('\n').map(r =>
      r.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
    );
    const header = rows[0];
    const body = rows.slice(2);
    return `<table class="md"><thead><tr>${header.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>` +
           `<tbody>${body.map(r => `<tr>${r.map(c => `<td>${escapeHtml(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  });
  // plain-ish lines that aren't in a table/code already: escape + render math + line breaks
  // (Math handling lives inside escapeWithMath so the rendered KaTeX HTML doesn't get re-escaped.)
  if (!html.startsWith('<table') && !html.startsWith('<pre')) {
    html = `<div class="extra md">${html.split('\n').map(l => l ? escapeWithMath(l).replace(/&lt;br\s*\/?&gt;/g,'<br>') : '').join('<br>')}</div>`;
  }
  return html;
}

async function renderPendingMermaid(scope){
  if (!scope) return;
  const nodes = scope.querySelectorAll('.mmd[data-src]');
  if (!nodes.length) return;
  await ensureRenderers({ katex: false, mermaid: true });
  if (!window.mermaid) return;
  for (const n of nodes) {
    const code = decodeURIComponent(n.dataset.src);
    const id = n.dataset.id;
    try {
      const { svg } = await window.mermaid.render(id, code);
      n.innerHTML = svg;
    } catch (e) {
      n.innerHTML = `<pre class="code"><code>${escapeHtml(code)}</code></pre>`;
    }
    n.removeAttribute('data-src');
  }
}

/* ---- icons ---- */
const icons = {
  back: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>`,
  fwd:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>`,
  close: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round"><path d="M6 6l12 12M6 18L18 6"/></svg>`,
  more: `<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>`,
  star: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`,
  starFill: `<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`,
  redo: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>`,
  grid: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`,
  chev: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" class="chev"><path d="M9 18l6-6-6-6"/></svg>`,
  share: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v7a2 2 0 002 2h12a2 2 0 002-2v-7"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>`,
  timer: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="8"/><polyline points="12 9 12 13 15 16"/><line x1="9" y1="2" x2="15" y2="2"/></svg>`,
  search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
  filter: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>`,
  send: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`,
};

async function bootUI(){
  try { await loadExams(); } catch {}
}

const MODE_LABEL = { practice: '풀이', review: '해설', exam: '모의시험' };
function updateModeLabel() {
  const c = state.current; if (!c) return;
  const $label = c.screen?.querySelector('#modeLabel');
  if ($label) $label.textContent = MODE_LABEL[c.mode] || '풀이';
}

// PWA install affordance — captured here so it survives module-level reloads.
let _deferredInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  _deferredInstallPrompt = e;
  try { maybeShowPwaBanner(); } catch {}
});
function isStandaloneApp() {
  return window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;
}
function maybeShowPwaBanner() {
  if (isStandaloneApp()) return;
  if (store.get('pwaPromptDismissed')) return;
  if ((store.get('quizVisits') || 0) < 2) return;          // ≥ 3rd quiz visit
  const c = state.current; if (!c?.screen) return;
  if (c.screen.querySelector('.pwa-banner')) return;
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
  if (!_deferredInstallPrompt && !isIOS) return;
  const banner = document.createElement('div');
  banner.className = 'pwa-banner';
  banner.innerHTML = `
    <span class="pwa-text">홈 화면에 추가하면 앱처럼 열려요</span>
    <button class="pwa-add" type="button">추가</button>
    <button class="pwa-close" type="button" aria-label="닫기">✕</button>
  `;
  banner.querySelector('.pwa-close').onclick = () => {
    banner.remove();
    store.set('pwaPromptDismissed', 1);
  };
  banner.querySelector('.pwa-add').onclick = async () => {
    if (_deferredInstallPrompt) {
      _deferredInstallPrompt.prompt();
      try { await _deferredInstallPrompt.userChoice; } catch {}
      _deferredInstallPrompt = null;
      store.set('pwaPromptDismissed', 1);
      banner.remove();
    } else if (isIOS) {
      showSheet('홈 화면에 추가', () => {
        const d = document.createElement('div');
        d.className = 'ios-install';
        d.innerHTML = `
          <p>Safari 에서:</p>
          <ol>
            <li>하단 <b>공유</b> 버튼을 누르세요</li>
            <li>"<b>홈 화면에 추가</b>" 선택</li>
            <li>"<b>추가</b>"를 누르면 끝</li>
          </ol>
          <p class="ios-note">완료 후 홈에서 앱처럼 전체화면으로 열립니다.</p>
        `;
        return d;
      });
      store.set('pwaPromptDismissed', 1);
      banner.remove();
    }
  };
  const nav = c.screen.querySelector('.nav');
  nav?.after(banner);
}

/* ===================================================================
   Tab system
   =================================================================== */
function bindTabs(){
  document.getElementById('tabbar').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    showTab(b.dataset.tab);
  });
}

const tabs = {
  home:     renderHome,
  concepts: renderConcepts,
  stars:    renderStars,
  wrongs:   renderWrongs,
  settings: renderSettings,
};

function showTab(name){
  state.tab = name;
  // Clean any lingering toasts before tearing down the screen — otherwise they
  // hover over the new tab and the user can't dismiss them.
  document.getElementById('toast-action')?.remove();
  // Tab 전환은 stack 을 통째로 재구성한다. 깊은 stack 에서 탭바를 누른 경우
  // history depth > 0 이 남아있으면 이후 back 시 stack/history 가 어긋나 wedge 된다.
  // depth 를 0 으로 anchor 한다.
  if ((history.state?.depth || 0) !== 0) {
    history.replaceState({ type:'home', depth:0 }, '', '/');
  }
  document.querySelectorAll('#tabbar button').forEach(b => b.classList.toggle('on', b.dataset.tab===name));
  const stack = document.getElementById('stack');
  stack.innerHTML = '';
  const screen = document.createElement('section');
  screen.className = 'screen';
  screen.dataset.tab = name;
  stack.appendChild(screen);
  tabs[name](screen);
  document.getElementById('shell').classList.remove('hide-tabs');
}

/* ===================================================================
   HOME — 자격증 피커
   =================================================================== */
async function renderHome(root){
  root.innerHTML = `
    <header class="nav" id="nav">
      <div></div>
      <div class="nav-title">기출</div>
      <button class="icon-btn" id="themeQuick" aria-label="테마">${iconTheme(currentTheme())}</button>
    </header>
    <div class="scroll" id="homeScroll">
      <div class="large-title">
        <div class="kicker">STUDY · CERTIFICATION</div>
        <h1>기출<br><em>연습장</em></h1>
      </div>
      <div id="examList">${[0,1,2,3].map(()=>'<div class="skeleton" style="height:96px;margin:8px 16px"></div>').join('')}</div>
      ${ADSENSE.client && ADSENSE.slots.homeBanner
        ? `<div class="ad-slot ad-slot-banner" id="homeAd">${adInsHTML(ADSENSE.slots.homeBanner)}</div>`
        : ''}
    </div>
  `;
  attachScrollShadow('homeScroll','nav');
  document.getElementById('themeQuick').onclick = openThemeSheet;

  try {
    const exams = await loadExams();
    fillExamPicker(root, exams);
  } catch (e) {
    document.getElementById('examList').innerHTML = emptyCard('목록을 불러오지 못했어요',
      'data/exams.json을 확인해 주세요');
  }
  pushAd(root);
}

function fillExamPicker(root, exams){
  const examMark = { s2:'사조분', g1:'공인1', g2:'공인2', iz:'정처기', sa:'산안기',
                     c1:'컴활1', k1:'한국사', kt:'전기', nd:'소방기' };
  // per-exam correct count from localStorage (맞춘 갯수)
  const correctFor = (code) => {
    let n = 0;
    const prefix = STORE + `progress:${code}:`;
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k.startsWith(prefix)) continue;
      try {
        const p = JSON.parse(localStorage.getItem(k));
        const a = Object.keys(p.answers || {}).length;
        const w = (p.wrongs || []).length;
        n += Math.max(0, a - w);
      } catch {}
    }
    return n;
  };
  root.querySelector('#examList').innerHTML = `
    <div class="section-head"><h2>자격증 선택</h2><span class="meta">${exams.length} EXAMS</span></div>
    <div class="group">
      ${exams.map(e => {
        const correct = correctFor(e.code);
        const mark = examMark[e.code] || '◐';
        return `<button class="row exam-row" data-exam="${e.code}">
          <span class="row-lead exam-mark">${mark}</span>
          <span class="row-body">
            <span class="row-title">${escapeHtml(e.name)}</span>
            <span class="row-sub">${e.sessions}회차 · ${e.questions.toLocaleString()}문항</span>
          </span>
          <span class="row-trail">
            ${correct ? `<span class="pill active">${correct}</span>` : '<span class="pill">—</span>'}
            ${icons.chev}
          </span>
        </button>`;
      }).join('')}
    </div>
  `;
  root.querySelectorAll('.exam-row').forEach(el => {
    el.addEventListener('click', () => openSessionList(el.dataset.exam));
  });
}

/* ===================================================================
   SESSION LIST — push screen from home
   =================================================================== */
async function openSessionList(examCode){
  state.currentExam = examCode;
  if (!_navInternal) pushRoute({ type:'session', exam:examCode });
  const stack = document.getElementById('stack');
  const screen = document.createElement('section');
  screen.className = 'screen enter-right';
  const exam = state.examByCode.get(examCode);
  screen.innerHTML = `
    <header class="nav has-title" id="sessNav">
      <button class="icon-btn" id="sessBack" aria-label="뒤로">${icons.back}</button>
      <div class="nav-title">${escapeHtml(exam ? exam.name : '')}</div>
      <div></div>
    </header>
    <div class="scroll" id="sessScroll">
      <div class="large-title">
        <div class="kicker">${(exam?.name||'').slice(0,6).toUpperCase()} · ARCHIVE</div>
        <h1>${escapeHtml(exam?.name || '')}</h1>
      </div>
      <div class="stat-row" id="sessStats">
        ${['—','—','—'].map((n,i)=>`<div class="stat"><span class="n">${n}</span><span class="l">${['회차','맞춘 문항','완료 회차'][i]}</span></div>`).join('')}
      </div>
      <div id="yearList">${[0,1,2].map(()=>'<div class="skeleton" style="height:140px;margin:4px 16px 20px"></div>').join('')}</div>
    </div>
  `;
  stack.appendChild(screen);
  updateScreenInert();
  attachScrollShadow('sessScroll','sessNav');
  screen.querySelector('#sessBack').onclick = popScreen;
  addEdgeBack(screen);

  try {
    const sessions = await loadSessions(examCode);
    fillSessionList(screen, examCode, sessions);
  } catch (e) {
    screen.querySelector('#yearList').innerHTML = emptyCard('목록을 불러오지 못했어요', e.message || '');
  }
}

function fillSessionList(root, examCode, sessions){
  let correctTotal = 0, done = 0;
  for (const s of sessions){
    const p = progressFor(examCode, s.code);
    const a = Object.keys(p.answers||{}).length;
    const w = (p.wrongs||[]).length;
    correctTotal += Math.max(0, a - w);
    if (s.count && a === s.count) done++;
  }
  const stats = root.querySelectorAll('.stat .n');
  stats[0].textContent = sessions.length;
  stats[1].textContent = correctTotal.toLocaleString();
  stats[2].textContent = done;

  const years = {};
  for (const s of sessions) (years[s.year] = years[s.year] || []).push(s);
  const yrs = Object.keys(years).sort((a,b)=>b-a);
  // compute ordinal within same year (1회, 2회, ...) based on chronological order
  const monthNames = ['', '1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월'];
  root.querySelector('#yearList').innerHTML = yrs.map(y => {
    const ys = years[y].slice().sort((a,b) => a.date.localeCompare(b.date));
    const ord = new Map(ys.map((s,i) => [s.code, ys.length > 1 ? `${i+1}회차` : '정기']));
    return `
    <div class="section-head"><h2>${y}년</h2><span class="meta">${years[y].length} EX</span></div>
    <div class="group">${years[y].map(s => {
      const p = progressFor(examCode, s.code);
      const a = Object.keys(p.answers||{}).length;
      const w = (p.wrongs||[]).length;
      const correct = Math.max(0, a - w);
      const st = s.count && a===s.count ? 'done' : a>0 ? 'active' : '';
      const mn = monthNames[parseInt(s.date.slice(5,7), 10)];
      const day = parseInt(s.date.slice(8,10), 10);
      return `<button class="row" data-code="${s.code}" ${s.count?'':'disabled'}>
        <span class="row-lead">${s.date.slice(5,7)}.${s.date.slice(8,10)}</span>
        <span class="row-body">
          <span class="row-title">${mn} ${day}일</span>
          <span class="row-sub">${ord.get(s.code)} · ${s.count? s.count+'문항':'수집 전'}</span>
        </span>
        <span class="row-trail">
          ${s.count ? `<span class="pill ${st}">${correct}/${s.count}</span>` : '<span class="pill">—</span>'}
          ${icons.chev}
        </span>
      </button>`;
    }).join('')}</div>`;
  }).join('');
  root.querySelectorAll('.row[data-code]').forEach(el => {
    el.addEventListener('click', () => openQuiz(examCode, el.dataset.code));
  });
}

/* ===================================================================
   STARS — 즐겨찾기
   =================================================================== */
async function renderStars(root){
  root.innerHTML = `
    <header class="nav" id="nav">
      <div></div>
      <div class="nav-title">즐겨찾기</div>
      <div></div>
    </header>
    <div class="scroll" id="starsScroll">
      <div class="large-title">
        <div class="kicker">BOOKMARKS</div>
        <h1>다시 볼<br>문제</h1>
      </div>
      <div class="search-bar"><input type="search" id="starsSearch" placeholder="문제 키워드 검색" inputmode="search" autocomplete="off"></div>
      <div id="starsBody"></div>
    </div>
  `;
  attachScrollShadow('starsScroll','nav');

  try {
    await loadExams();
    for (const e of state.exams) await loadSessions(e.code).catch(()=>{});
    const groups = collectAcross('stars');
    const $body = root.querySelector('#starsBody');
    if (groups.length === 0) {
      $body.innerHTML = `
        <div class="empty">
          <span class="ideo">空</span>
          <h4>아직 저장된 문제가 없어요</h4>
          <p>퀴즈 화면의 <b>☆ 북마크</b>로 문제를 추가하세요.</p>
          <button class="r-primary empty-cta" id="starsEmptyCta">지금 풀러 가기</button>
        </div>
      `;
      $body.querySelector('#starsEmptyCta').onclick = () => showTab('home');
      return;
    }
    const renderFiltered = (q) => {
      const filtered = filterGroupsByQuery(groups, q);
      if (!filtered.length) {
        $body.innerHTML = emptyCard('검색 결과 없음', '');
        return;
      }
      renderCollected($body, filtered, '북마크');
    };
    renderFiltered('');
    bindSearch(root.querySelector('#starsSearch'), renderFiltered);
  } catch {}
}

/* ===================================================================
   WRONGS — 오답노트
   =================================================================== */
async function renderWrongs(root){
  root.innerHTML = `
    <header class="nav" id="nav">
      <div></div>
      <div class="nav-title">오답노트</div>
      <div></div>
    </header>
    <div class="scroll" id="wrongsScroll">
      <div class="large-title">
        <div class="kicker">WRONG ANSWERS</div>
        <h1>틀렸던<br>문제</h1>
      </div>
      <div class="search-bar">
        <input type="search" id="wrongsSearch" placeholder="문제 키워드 검색" inputmode="search" autocomplete="off">
        <span class="seg" id="wrongsSort">
          <button data-s="due" class="on">복습 우선</button>
          <button data-s="recent">최근</button>
        </span>
      </div>
      <div id="wrongsBody"></div>
    </div>
  `;
  attachScrollShadow('wrongsScroll','nav');

  try {
    await loadExams();
    for (const e of state.exams) await loadSessions(e.code).catch(()=>{});
    const groups = collectAcross('wrongs');
    const $body = root.querySelector('#wrongsBody');
    if (groups.length === 0) {
      $body.innerHTML = `
        <div class="empty">
          <span class="ideo">空</span>
          <h4>오답이 없어요</h4>
          <p>문제를 풀면 여기에 틀린 문항이 모입니다.</p>
          <button class="r-primary empty-cta" id="wrongsEmptyCta">지금 풀러 가기</button>
        </div>
      `;
      $body.querySelector('#wrongsEmptyCta').onclick = () => showTab('home');
      return;
    }
    let sort = 'due', query = '';
    const re = () => {
      const filtered = filterGroupsByQuery(groups, query);
      const sorted = sort === 'due' ? sortByForgettingCurve(filtered) : filtered;
      renderCollected($body, sorted, '오답', { showDue: sort === 'due' });
    };
    re();
    bindSearch(root.querySelector('#wrongsSearch'), q => { query = q; re(); });
    root.querySelector('#wrongsSort').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      sort = b.dataset.s;
      root.querySelectorAll('#wrongsSort button').forEach(x => x.classList.toggle('on', x.dataset.s === sort));
      re();
    });
  } catch {}
}

function collectAcross(kind){
  const groups = [];
  for (const e of state.exams) {
    const sessions = state.sessionsCache.get(e.code) || [];
    for (const s of sessions) {
      const p = progressFor(e.code, s.code);
      const list = kind === 'stars' ? (p.stars||[]) : (p.wrongs||[]);
      if (!list.length) continue;
      groups.push({
        examCode: e.code, examName: e.name,
        code: s.code, date: s.date,
        nums: list.slice().sort((a,b)=>a-b),
        seenAt: p.seenAt || {},
      });
    }
  }
  // sort: newest first (by session code desc)
  return groups.sort((a,b) => (a.examCode + a.code) < (b.examCode + b.code) ? 1 : -1);
}

function renderCollected($root, groups, kindLabel, opts = {}){
  const showDue = opts.showDue;
  $root.innerHTML = groups.map(g => `
    <div class="section-head">
      <h2>${escapeHtml(g.examName)} · ${g.date}</h2>
      <span class="meta">${g.nums.length} ${kindLabel}</span>
    </div>
    <div class="group">
      ${g.nums.map(n => {
        const ts = g.seenAt?.[n];
        const due = showDue ? dueLabel(ts) : '탭하여 바로 이동';
        return `<button class="row" data-exam="${g.examCode}" data-code="${g.code}" data-num="${n}">
          <span class="row-lead">${String(n).padStart(3,'0')}</span>
          <span class="row-body">
            <span class="row-title">${g.date.slice(2).replace(/-/g,'.')} · ${n}번</span>
            <span class="row-sub">${escapeHtml(due)}</span>
          </span>
          <span class="row-trail">${icons.chev}</span>
        </button>`;
      }).join('')}
    </div>
  `).join('');
  $root.querySelectorAll('.row[data-exam]').forEach(el => {
    el.addEventListener('click', () => openQuiz(el.dataset.exam, el.dataset.code, +el.dataset.num - 1));
  });
}

function dueLabel(ts){
  if (!ts) return '복습할 시간';
  const days = (Date.now() - ts) / 86400000;
  if (days < 1) return '오늘 풀이';
  if (days < 2) return '어제 풀이';
  if (days < 7) return `${Math.floor(days)}일 전`;
  if (days < 30) return `${Math.floor(days/7)}주 전 — 복습 추천`;
  return `${Math.floor(days/30)}개월 전 — 다시 복습`;
}

function bindSearch(input, onChange){
  if (!input) return;
  let t;
  input.addEventListener('input', () => {
    clearTimeout(t);
    t = setTimeout(() => onChange(input.value.trim().toLowerCase()), 180);
  });
}

function filterGroupsByQuery(groups, query){
  if (!query) return groups;
  // Lazy-search through cached session data only — no extra fetches for speed
  const out = [];
  for (const g of groups) {
    const data = state.dataCache.get(`${g.examCode}:${g.code}`);
    if (!data) {
      // Not loaded — keep group but don't filter (acceptable trade-off)
      out.push(g); continue;
    }
    const matchedNums = g.nums.filter(n => {
      const q = data.questions.find(qq => qq.number === n);
      if (!q) return false;
      const text = ((q.question || '') + ' ' + (q.subject || '') +
                    ' ' + (q.choices||[]).map(c => c.text || '').join(' ')).toLowerCase();
      return text.includes(query);
    });
    if (matchedNums.length) out.push({ ...g, nums: matchedNums });
  }
  return out;
}

function sortByForgettingCurve(groups){
  // Flatten, sort by oldest seenAt, regroup
  const items = [];
  for (const g of groups) {
    for (const n of g.nums) {
      items.push({ ...g, n, ts: g.seenAt?.[n] || 0 });
    }
  }
  items.sort((a, b) => a.ts - b.ts);
  const merged = new Map();
  for (const it of items) {
    const key = `${it.examCode}:${it.code}`;
    if (!merged.has(key)) merged.set(key, { ...it, nums: [it.n] });
    else merged.get(key).nums.push(it.n);
  }
  return [...merged.values()].map(g => ({
    examCode: g.examCode, examName: g.examName, code: g.code, date: g.date,
    nums: g.nums, seenAt: g.seenAt,
  }));
}

/* ===================================================================
   SETTINGS — 설정
   =================================================================== */
function renderSettings(root){
  root.innerHTML = `
    <header class="nav" id="nav">
      <div></div>
      <div class="nav-title">설정</div>
      <div></div>
    </header>
    <div class="scroll" id="setScroll">
      <div class="large-title">
        <div class="kicker">PREFERENCES</div>
        <h1>설정</h1>
      </div>

      <div class="section-head"><h2>외형</h2><span class="meta">APPEARANCE</span></div>
      <div class="group">
        <div class="row">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 000 18"/></svg></span>
          <span class="row-body"><span class="row-title">테마</span><span class="row-sub">시스템 · 밝게 · 어둡게</span></span>
          <span class="row-trail">
            <span class="seg" id="themeSeg">
              <button data-t="system">자동</button>
              <button data-t="light">밝게</button>
              <button data-t="dark">어둡게</button>
            </span>
          </span>
        </div>
        <div class="row">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round"><path d="M4 7V5h16v2"/><path d="M9 5v14"/><path d="M15 5v14"/><path d="M7 19h4M13 19h4"/></svg></span>
          <span class="row-body"><span class="row-title">글자 크기</span><span class="row-sub">읽기 편한 크기로</span></span>
          <span class="row-trail">
            <span class="seg" id="fontSeg">
              <button data-fs="sm">작게</button>
              <button data-fs="md">보통</button>
              <button data-fs="lg">크게</button>
            </span>
          </span>
        </div>
      </div>

      <div class="section-head"><h2>학습</h2><span class="meta">STATS</span></div>
      <div class="group">
        <button class="row" id="statsBtn">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 3 5-7"/></svg></span>
          <span class="row-body"><span class="row-title">학습 현황</span><span class="row-sub" id="statsSub">자격증·과목별 진도</span></span>
          <span class="row-trail">${icons.chev}</span>
        </button>
      </div>

      <div class="section-head"><h2>기기 간 동기화</h2><span class="meta">SYNC</span></div>
      <div class="group">
        <button class="row" id="exportBtn">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 5 17 10"/><line x1="12" y1="5" x2="12" y2="15"/></svg></span>
          <span class="row-body"><span class="row-title">내보내기</span><span class="row-sub" id="exportSub">진도·북마크·오답을 JSON 파일로</span></span>
          <span class="row-trail">${icons.chev}</span>
        </button>
        <button class="row" id="importBtn">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9v10a2 2 0 002 2h14a2 2 0 002-2V9"/><polyline points="17 14 12 9 7 14"/><line x1="12" y1="9" x2="12" y2="19"/></svg></span>
          <span class="row-body"><span class="row-title">불러오기</span><span class="row-sub">다른 기기에서 가져온 JSON 파일</span></span>
          <span class="row-trail">${icons.chev}</span>
        </button>
        <button class="row" id="copyCodeBtn">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></span>
          <span class="row-body"><span class="row-title">공유 코드 복사</span><span class="row-sub">클립보드에 Base64로</span></span>
          <span class="row-trail">${icons.chev}</span>
        </button>
        <button class="row" id="pasteCodeBtn">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M9 14l2 2 4-4"/></svg></span>
          <span class="row-body"><span class="row-title">코드로 붙여넣기</span><span class="row-sub">복사한 공유 코드 입력</span></span>
          <span class="row-trail">${icons.chev}</span>
        </button>
      </div>

      <div class="section-head"><h2>관리</h2><span class="meta">MANAGE</span></div>
      <div class="group">
        <button class="row" id="restoreBtn">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></span>
          <span class="row-body"><span class="row-title">직전 상태로 복구</span><span class="row-sub" id="restoreSub">불러오기/초기화 직전 자동 백업</span></span>
          <span class="row-trail">${icons.chev}</span>
        </button>
        <button class="row" id="resetBtn">
          <span class="row-lead icon danger"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg></span>
          <span class="row-body"><span class="row-title" style="color:var(--vermilion)">모든 진도 초기화</span><span class="row-sub">되돌릴 수 없음</span></span>
          <span class="row-trail">${icons.chev}</span>
        </button>
      </div>

      <div class="section-head"><h2>피드백</h2><span class="meta">FEEDBACK</span></div>
      <div class="group">
        <button class="row" id="feedbackBtn" type="button">
          <span class="row-lead icon">${icons.send}</span>
          <span class="row-body"><span class="row-title">의견 보내기</span><span class="row-sub">오류 신고 · 기능 제안</span></span>
          <span class="row-trail">${icons.chev}</span>
        </button>
      </div>

      <div class="section-head"><h2>정보</h2><span class="meta">ABOUT</span></div>
      <div class="group">
        <div class="row">
          <span class="row-lead icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg></span>
          <span class="row-body"><span class="row-title">출제 기관</span><span class="row-sub">한국산업인력공단</span></span>
        </div>
        <div class="row">
          <span class="row-lead">v1</span>
          <span class="row-body"><span class="row-title">버전</span><span class="row-sub">hanji-ink edition</span></span>
        </div>
      </div>
    </div>
  `;
  attachScrollShadow('setScroll','nav');

  // wire theme segmented control
  const seg = root.querySelector('#themeSeg');
  const markSeg = () => seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.t===currentTheme()));
  markSeg();
  seg.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    setTheme(b.dataset.t); markSeg();
  });

  // wire font size segmented control
  const fseg = root.querySelector('#fontSeg');
  const markFs = () => fseg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.fs===currentFontSize()));
  markFs();
  fseg.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    setFontSize(b.dataset.fs); markFs();
  });

  // stats button
  root.querySelector('#statsBtn').onclick = openStats;
  root.querySelector('#feedbackBtn').onclick = () => openFeedbackSheet();
  const $statsSub = root.querySelector('#statsSub');
  const stStats = computeLearnStats();
  if ($statsSub && stStats.totalAnswered > 0) {
    $statsSub.textContent = `정답률 ${stStats.accuracy}% · ${stStats.totalAnswered}문항 풀이`;
  }
  // --- update export sub with stat preview
  const stats = computeStats();
  const $sub = root.querySelector('#exportSub');
  if ($sub) $sub.textContent = `${stats.sessions}회차 · 진도 ${stats.answers} · 별 ${stats.stars}`;
  const $restoreSub = root.querySelector('#restoreSub');
  if ($restoreSub) {
    const b = store.get('_backup');
    $restoreSub.textContent = b ? `자동 백업: ${new Date(b._at).toLocaleString('ko-KR')}` : '자동 백업 없음';
  }

  root.querySelector('#resetBtn').onclick = () => {
    if (!confirm('모든 진도·북마크·오답을 초기화할까요?')) return;
    backupCurrent();
    Object.keys(localStorage).filter(k => k.startsWith(STORE) && !k.endsWith('_backup')).forEach(k => localStorage.removeItem(k));
    toast('초기화 · 복구 가능');
    showTab('settings');
  };
  root.querySelector('#exportBtn').onclick = () => {
    const dump = buildDump();
    const blob = new Blob([JSON.stringify(dump, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const ts = new Date().toISOString().slice(0,16).replace(/[:T]/g,'-');
    a.href = url; a.download = `기출_진도_${ts}.json`; a.click();
    URL.revokeObjectURL(url);
    toast('내보내기 완료');
  };
  root.querySelector('#importBtn').onclick = () => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = 'application/json,.json';
    input.onchange = async () => {
      const f = input.files[0]; if (!f) return;
      try {
        const txt = await f.text();
        const parsed = JSON.parse(txt);
        openImportSheet(parsed);
      } catch { toast('JSON 형식이 아니에요'); }
    };
    input.click();
  };
  root.querySelector('#copyCodeBtn').onclick = async () => {
    const dump = buildDump();
    const code = encodeShareCode(dump);
    try {
      await navigator.clipboard.writeText(code);
      toast(`복사됨 · ${Math.round(code.length/1024)}KB`);
    } catch {
      // fallback for insecure context — show in a prompt
      prompt('아래 코드를 복사하세요 (Ctrl+A → Ctrl+C)', code);
    }
  };
  root.querySelector('#pasteCodeBtn').onclick = async () => {
    let code = '';
    try { code = (await navigator.clipboard.readText()) || ''; } catch {}
    if (!code) code = prompt('복사해 온 공유 코드를 붙여넣으세요', '') || '';
    code = code.trim();
    if (!code) return;
    try {
      const parsed = decodeShareCode(code);
      openImportSheet(parsed);
    } catch { toast('올바른 코드가 아니에요'); }
  };
  root.querySelector('#restoreBtn').onclick = () => {
    const b = store.get('_backup');
    if (!b) { toast('백업이 없어요'); return; }
    if (!confirm('현재 상태를 버리고 백업 시점으로 복구할까요?')) return;
    backupCurrent(); // backup current-current so user can undo the restore
    applyDump(b, { mode: 'replace' });
    toast('복구 완료');
    showTab('settings');
  };
}

/* ===================================================================
   Export / Import helpers
   =================================================================== */
function buildDump(){
  // export 도 import 와 같은 sanitize 를 거친다 — 이전 버전에서 우연히 들어간 알 수 없는
  // key/shape 가 share code/JSON 파일로 흘러나가지 않도록 차단.
  const dump = { _meta: { version: 'v2', exportedAt: Date.now() } };
  for (let i = 0; i < localStorage.length; i++){
    const k = localStorage.key(i);
    if (!k.startsWith(STORE)) continue;
    if (k === STORE + '_backup') continue;
    if (k.startsWith(STORE + '_backup')) continue;  // rotated 백업 슬롯도 제외
    const inner = k.slice(STORE.length);
    if (inner.startsWith('_')) continue;
    const raw = safeParse(localStorage.getItem(k));
    const safe = sanitizeImportEntry(inner, raw);
    if (safe === null) continue;
    dump[inner] = safe;
  }
  return dump;
}

// UTF-8-safe base64 — deprecated escape/unescape 의 현대화.
function encodeShareCode(obj){
  const bytes = new TextEncoder().encode(JSON.stringify(obj));
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
function decodeShareCode(code){
  const bin = atob(code);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return JSON.parse(new TextDecoder().decode(bytes));
}

function safeParse(s){
  try { return JSON.parse(s); } catch { return s; }
}

function computeStats(){
  let sessions = 0, answers = 0, stars = 0, wrongs = 0;
  for (let i = 0; i < localStorage.length; i++){
    const k = localStorage.key(i);
    if (!k.startsWith(STORE + 'progress:')) continue;
    sessions++;
    try {
      const v = JSON.parse(localStorage.getItem(k));
      answers += Object.keys(v.answers || {}).length;
      stars += (v.stars || []).length;
      wrongs += (v.wrongs || []).length;
    } catch {}
  }
  return { sessions, answers, stars, wrongs };
}

function computeStatsFromDump(d){
  let sessions = 0, answers = 0, stars = 0, wrongs = 0;
  for (const k of Object.keys(d)){
    if (!k.startsWith('progress:')) continue;
    sessions++;
    const v = d[k] || {};
    answers += Object.keys(v.answers || {}).length;
    stars += (v.stars || []).length;
    wrongs += (v.wrongs || []).length;
  }
  return { sessions, answers, stars, wrongs };
}

function backupCurrent(){
  // 3-슬롯 rotation: _backup (가장 최근) → _backup2 → _backup3.
  // 현재 UI 는 _backup 만 복구하지만, 슬롯이 남아 있으면 추후 깊은 undo 가 가능.
  const snap = buildDump();
  snap._at = Date.now();
  const prev1 = store.get('_backup');
  const prev2 = store.get('_backup2');
  if (prev2) store.set('_backup3', prev2);
  if (prev1) store.set('_backup2', prev1);
  store.set('_backup', snap);
}

/* ---- learning stats (per-exam, per-subject) ---- */
function computeLearnStats(){
  const perExam = {};   // code → { answered, correct, wrong, sessions:Set }
  const perSubject = {}; // examCode → subject → { answered, correct }
  let totalAnswered = 0, totalCorrect = 0;
  for (let i = 0; i < localStorage.length; i++){
    const k = localStorage.key(i);
    if (!k.startsWith(STORE + 'progress:')) continue;
    const m = k.slice(STORE.length).match(/^progress:([^:]+):(.+)$/);
    if (!m) continue;
    const [, examCode, sessionCode] = m;
    let v; try { v = JSON.parse(localStorage.getItem(k)); } catch { continue; }
    perExam[examCode] = perExam[examCode] || { answered: 0, correct: 0, wrong: 0, sessionCodes: new Set() };
    const ans = v.answers || {};
    const wrongSet = new Set(v.wrongs || []);
    for (const qNum of Object.keys(ans)) {
      perExam[examCode].answered++;
      const wrong = wrongSet.has(+qNum) || wrongSet.has(qNum);
      if (wrong) perExam[examCode].wrong++; else perExam[examCode].correct++;
      totalAnswered++;
      if (!wrong) totalCorrect++;
    }
    perExam[examCode].sessionCodes.add(sessionCode);
    // subject breakdown — needs the loaded session data; skip if not cached
    const dataKey = `${examCode}:${sessionCode}`;
    const data = state.dataCache.get(dataKey);
    if (data) {
      perSubject[examCode] = perSubject[examCode] || {};
      for (const q of data.questions) {
        const a = ans[q.number];
        if (a == null) continue;
        const subj = (q.subject || '기타').replace(/^\d+과목\s*:\s*/, '').trim() || '기타';
        const s = perSubject[examCode][subj] = perSubject[examCode][subj] || { answered: 0, correct: 0 };
        s.answered++;
        if (a === q.answer) s.correct++;
      }
    }
  }
  const accuracy = totalAnswered ? Math.round(totalCorrect * 100 / totalAnswered) : 0;
  return { perExam, perSubject, totalAnswered, totalCorrect, accuracy };
}

async function openStats(){
  // Load all sessions of exams with progress to enable subject breakdown
  const codes = Object.keys((function(){
    const seen = {};
    for (let i = 0; i < localStorage.length; i++){
      const k = localStorage.key(i);
      const m = k && k.startsWith(STORE + 'progress:') && k.slice(STORE.length).match(/^progress:([^:]+):(.+)$/);
      if (m) seen[m[1]] = (seen[m[1]] || new Set()).add(m[2]);
    }
    return seen;
  })());
  await loadExams().catch(()=>{});
  for (const code of codes) {
    const sessSet = (function(){
      const out = new Set();
      for (let i = 0; i < localStorage.length; i++){
        const k = localStorage.key(i);
        const m = k && k.startsWith(STORE + 'progress:' + code + ':');
        if (m) out.add(k.slice(STORE.length + ('progress:' + code + ':').length));
      }
      return out;
    })();
    for (const sc of sessSet) {
      try { await loadSession(code, sc); } catch {}
    }
  }

  const stack = document.getElementById('stack');
  const screen = document.createElement('section');
  screen.className = 'screen enter-right';
  const st = computeLearnStats();
  const examRows = state.exams.map(e => {
    const x = st.perExam[e.code]; if (!x) return '';
    const acc = x.answered ? Math.round(x.correct * 100 / x.answered) : 0;
    return `<div class="row">
      <span class="row-lead exam-mark">${({s2:'사조분',g1:'공인1',g2:'공인2',iz:'정처기',sa:'산안기'})[e.code] || '◐'}</span>
      <span class="row-body"><span class="row-title">${escapeHtml(e.name)}</span>
        <span class="row-sub">${x.sessionCodes.size}회차 · ${x.answered}문항 · 정답률 ${acc}%</span></span>
      <span class="row-trail"><span class="pill ${acc>=70?'active':''}">${acc}%</span></span>
    </div>`;
  }).join('') || '<div class="empty">아직 풀이한 문항이 없어요</div>';

  const subjectRows = Object.entries(st.perSubject).flatMap(([examCode, subs]) =>
    Object.entries(subs).map(([subj, s]) => {
      const acc = s.answered ? Math.round(s.correct * 100 / s.answered) : 0;
      return `<div class="row">
        <span class="row-lead">${({s2:'사조',g1:'공1',g2:'공2',iz:'정처'})[examCode] || ''}</span>
        <span class="row-body"><span class="row-title" style="font-size:14px">${escapeHtml(subj)}</span>
          <span class="row-sub">${s.answered}문항 · 정답 ${s.correct}</span></span>
        <span class="row-trail"><span class="pill ${acc>=70?'active':acc<50?'warn':''}">${acc}%</span></span>
      </div>`;
    })
  ).sort((a,b) => {
    const m = (s) => +(s.match(/(\d+)%<\/span/)?.[1] || 100);
    return m(a) - m(b);
  }).join('');

  screen.innerHTML = `
    <header class="nav has-title" id="statsNav">
      <button class="icon-btn" id="statsBack" aria-label="뒤로">${icons.back}</button>
      <div class="nav-title">학습 현황</div>
      <div></div>
    </header>
    <div class="scroll" id="statsScroll">
      <div class="large-title">
        <div class="kicker">PERFORMANCE</div>
        <h1>${st.accuracy}<small style="font-size:36px;opacity:.7">%</small></h1>
        <div class="row-sub" style="text-align:center;margin-top:-12px">총 ${st.totalAnswered}문항 · 정답 ${st.totalCorrect}</div>
      </div>
      <div class="section-head"><h2>자격증별</h2></div>
      <div class="group">${examRows}</div>
      ${subjectRows ? `<div class="section-head"><h2>약점 과목 (정답률 낮은 순)</h2></div><div class="group">${subjectRows}</div>` : ''}
    </div>
  `;
  stack.appendChild(screen);
  updateScreenInert();
  attachScrollShadow('statsScroll', 'statsNav');
  screen.querySelector('#statsBack').onclick = popScreen;
  addEdgeBack(screen);
  history.pushState({ type:'stats', depth: (history.state?.depth || 0)+1 }, '', '/stats');
}

// 알 수 없는 key / 비정상 shape 가 localStorage 에 침투해 향후 stored XSS / quota 공격으로 이어지지 않도록
// import 경로에서 한 번 거른다. null 을 돌려주면 그 entry 는 skip.
function sanitizeImportEntry(k, v){
  if (!/^(theme|fontSize|swipeHintSeen|expPref|progress:[A-Za-z0-9_:-]+)$/.test(k)) return null;
  if (k === 'theme')    return typeof v === 'string' && /^(light|dark|system)$/.test(v) ? v : null;
  if (k === 'fontSize') return typeof v === 'string' && /^(sm|md|lg)$/.test(v) ? v : null;
  if (k === 'swipeHintSeen') return (typeof v === 'number' || typeof v === 'string') ? v : null;
  if (k === 'expPref')  return (typeof v === 'string' || (v && typeof v === 'object' && !Array.isArray(v))) ? v : null;
  // progress:*
  if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
  const out = {};
  if (v.answers && typeof v.answers === 'object' && !Array.isArray(v.answers)){
    const ans = {};
    for (const [qk, qv] of Object.entries(v.answers)){
      if (/^\d+$/.test(qk) && typeof qv === 'number' && Number.isFinite(qv)) ans[qk] = qv;
    }
    out.answers = ans;
  }
  if (Array.isArray(v.stars))  out.stars  = v.stars.filter(n => Number.isInteger(n));
  if (Array.isArray(v.wrongs)) out.wrongs = v.wrongs.filter(n => Number.isInteger(n));
  if (typeof v.mode === 'string' && /^(practice|review|exam)$/.test(v.mode)) out.mode = v.mode;
  if (typeof v.last === 'number' && Number.isFinite(v.last)) out.last = v.last;
  return out;
}

function applyDump(dump, { mode }){
  // Returns stats of what changed.
  if (mode === 'replace'){
    backupCurrent();
    Object.keys(localStorage).filter(k => k.startsWith(STORE) && k !== STORE + '_backup').forEach(k => localStorage.removeItem(k));
    for (const [k, v] of Object.entries(dump)){
      if (k.startsWith('_')) continue;
      const safe = sanitizeImportEntry(k, v);
      if (safe === null) continue;
      localStorage.setItem(STORE + k, typeof safe === 'string' ? safe : JSON.stringify(safe));
    }
    return;
  }
  // merge mode: per-key union
  backupCurrent();
  for (const [k, v] of Object.entries(dump)){
    if (k.startsWith('_')) continue;
    const safe = sanitizeImportEntry(k, v);
    if (safe === null) continue;
    const storeKey = STORE + k;
    const raw = localStorage.getItem(storeKey);
    if (!raw){
      localStorage.setItem(storeKey, typeof safe === 'string' ? safe : JSON.stringify(safe));
      continue;
    }
    if (k.startsWith('progress:')){
      const local = safeParse(raw) || {};
      const incoming = safe || {};
      const localN = Object.keys(local.answers || {}).length;
      const incomingN = Object.keys(incoming.answers || {}).length;
      // For answer conflicts, prefer the side with more total progress (assumed newer session).
      // Start with less-progressed side, overwrite with more-progressed.
      const answers = incomingN >= localN
        ? Object.assign({}, local.answers || {}, incoming.answers || {})
        : Object.assign({}, incoming.answers || {}, local.answers || {});
      const merged = {
        answers,
        stars:  [...new Set([...(local.stars ||[]), ...(incoming.stars ||[])])].sort((a,b)=>a-b),
        wrongs: [...new Set([...(local.wrongs||[]), ...(incoming.wrongs||[])])].sort((a,b)=>a-b),
        mode: incomingN > localN ? (incoming.mode || local.mode || 'practice') : (local.mode || 'practice'),
        last: Math.max(local.last || 0, incoming.last || 0),
      };
      localStorage.setItem(storeKey, JSON.stringify(merged));
    } else {
      // theme / expPref — keep local (user's current device preference)
    }
  }
}

function openFeedbackSheet(ctx = {}){
  // ctx may be empty (settings page) or { examCode, sessionCode, qnum } (per-question report)
  const { examCode, sessionCode, qnum } = ctx;
  const ctxLabel = examCode && sessionCode && qnum
    ? `${examCode} · ${sessionCode} · ${qnum}번 문항`
    : '일반 의견';
  showSheet('의견 보내기', () => {
    const d = document.createElement('div');
    d.innerHTML = `
      <div class="feedback-sheet">
        <p class="fb-ctx">${escapeHtml(ctxLabel)}</p>
        <textarea id="fbText" rows="5" maxlength="4000" placeholder="해설 오류, 오타, 개선 제안 등을 자유롭게 적어주세요."></textarea>
        <div class="fb-foot">
          <span class="fb-help">제출 시 GitHub Issue로 자동 등록됩니다. 개인정보는 보내지 않아요.</span>
          <button class="big-action submit" id="fbSubmit">제출</button>
        </div>
      </div>
    `;
    const $text = d.querySelector('#fbText');
    const $submit = d.querySelector('#fbSubmit');
    setTimeout(() => $text.focus(), 50);
    $submit.onclick = async () => {
      const message = $text.value.trim();
      if (message.length < 5) { toast('5자 이상 적어주세요'); return; }
      $submit.disabled = true; $submit.textContent = '전송 중…';
      try {
        const r = await fetch('/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            exam_code: examCode || null,
            session_code: sessionCode || null,
            qnum: qnum || null,
            page_url: location.href,
            message,
            user_agent: navigator.userAgent,
          }),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          toast(err.error || '제출 실패 — 다시 시도해주세요');
          $submit.disabled = false; $submit.textContent = '제출';
          return;
        }
        closeSheet();
        toast('의견 접수됐어요. 감사합니다!');
      } catch {
        toast('네트워크 오류 — 다시 시도해주세요');
        $submit.disabled = false; $submit.textContent = '제출';
      }
    };
    return d;
  });
}

function openImportSheet(dump){
  const s = computeStatsFromDump(dump);
  const cur = computeStats();
  showSheet('불러오기 미리보기', () => {
    const d = document.createElement('div');
    d.innerHTML = `
      <div class="import-preview">
        <div class="ip-row"><span>현재</span><b>${cur.sessions}회차 · 진도 ${cur.answers}</b></div>
        <div class="ip-row"><span>가져올 데이터</span><b>${s.sessions}회차 · 진도 ${s.answers}</b></div>
        <div class="ip-hint">
          <strong>합치기</strong>: 기존 데이터 유지, 새 항목만 추가 (답안은 둘 다 보존, 많이 푼 쪽 기준).<br>
          <strong>덮어쓰기</strong>: 기존을 모두 지우고 가져온 데이터로 교체.
        </div>
      </div>
      <div class="sheet-action-row">
        <button class="big-action merge" id="mergeBtn">합치기</button>
        <button class="big-action replace" id="replaceBtn">덮어쓰기</button>
      </div>
      <div class="ip-foot">어느 쪽이든 직전 상태는 자동 백업되며 '직전 상태로 복구'로 되돌릴 수 있어요.</div>
    `;
    d.querySelector('#mergeBtn').onclick = () => {
      applyDump(dump, { mode: 'merge' });
      closeSheet(); toast('합치기 완료'); showTab('settings');
    };
    d.querySelector('#replaceBtn').onclick = () => {
      if (!confirm('기존 진도를 모두 지우고 덮어쓸까요? (자동 백업됨)')) return;
      applyDump(dump, { mode: 'replace' });
      closeSheet(); toast('덮어쓰기 완료'); showTab('settings');
    };
    return d;
  });
}

/* ===================================================================
   QUIZ screen — push onto stack
   =================================================================== */
async function openQuiz(examCode, sessionCode, startIdx){
  if (!_navInternal) pushRoute({ type:'quiz', exam:examCode, session:sessionCode });
  document.getElementById('shell').classList.add('hide-tabs');
  const stack = document.getElementById('stack');
  const screen = document.createElement('section');
  screen.className = 'screen enter-right';
  stack.appendChild(screen);
  updateScreenInert();

  screen.innerHTML = `
    <header class="nav has-title" id="quizNav">
      <button class="icon-btn" id="quizBack" aria-label="뒤로">${icons.back}</button>
      <div class="quiz-nav-title" id="quizTitle">
        <span class="d">${sessionCode.slice(0,4)}.${sessionCode.slice(4,6)}.${sessionCode.slice(6,8)}</span>
        <span class="s" id="quizSub">불러오는 중</span>
      </div>
      <div class="nav-actions">
        <span class="quiz-timer" id="quizTimer" hidden></span>
        <button class="icon-btn" id="quizShareBtn" aria-label="공유">${icons.share}</button>
        <button class="mode-chip" id="quizModeBtn" aria-label="모드 변경"><span id="modeLabel">풀이</span><svg class="mode-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg></button>
      </div>
    </header>
    <div class="progress"><div class="progress-fill" id="pFill"></div></div>
    <div class="pages-wrap">
      <div class="pages" id="pages">
        ${[0,1].map(()=>`<div class="page">${'<div class="skeleton"></div>'.repeat(4)}</div>`).join('')}
      </div>
      <button class="page-nav prev" id="pagePrev" type="button" aria-label="이전 문제" hidden>${icons.back}</button>
      <button class="page-nav next" id="pageNext" type="button" aria-label="다음 문제" hidden>${icons.back}</button>
      <div class="swipe-hint" id="swipeHint" hidden aria-hidden="true">
        <span class="sh-icon">${icons.back}</span>
        <span class="sh-text">좌우로 쓸어서 다음 문제</span>
        <span class="sh-icon flip">${icons.back}</span>
      </div>
    </div>
    <div class="quiz-foot">
      <button class="foot-btn star" id="starBtn">${icons.star}<span>북마크</span></button>
      <button class="jump" id="jumpBtn"><span class="jump-icon">${icons.grid}</span><span id="jumpNum">1</span><span class="slash">/</span><span id="jumpTot">—</span></button>
      <button class="foot-btn" id="redoBtn">${icons.redo}<span>다시</span></button>
    </div>
  `;

  screen.querySelector('#quizBack').onclick = popScreen;
  screen.querySelector('#quizModeBtn').onclick = openModeSheet;
  screen.querySelector('#quizShareBtn').onclick = shareCurrent;
  screen.querySelector('#redoBtn').onclick = confirmRedo;
  screen.querySelector('#starBtn').onclick = toggleStar;
  screen.querySelector('#jumpBtn').onclick = openJumpSheet;
  const $prev = screen.querySelector('#pagePrev');
  const $next = screen.querySelector('#pageNext');
  const stepPage = (dir) => {
    const $pages = screen.querySelector('#pages');
    if (!$pages) return;
    $pages.scrollBy({ left: dir * $pages.clientWidth, behavior: 'smooth' });
  };
  $prev.onclick = () => stepPage(-1);
  $next.onclick = () => stepPage(1);

  // First-launch swipe hint (mobile users may not realize swipe works).
  // One-shot per user: localStorage flag stops repeats. Auto-dismiss on
  // any first scroll/click/key, or after 5s.
  if (!store.get('swipeHintSeen')) {
    const $hint = screen.querySelector('#swipeHint');
    const $pages = screen.querySelector('#pages');
    if ($hint && $pages) {
      $hint.hidden = false;
      requestAnimationFrame(() => $hint.classList.add('visible'));
      const dismiss = () => {
        if ($hint.hidden) return;
        $hint.classList.remove('visible');
        $hint.classList.add('fading');
        setTimeout(() => { $hint.hidden = true; }, 320);
        store.set('swipeHintSeen', 1);
        $pages.removeEventListener('scroll', dismiss, { passive: true });
        screen.removeEventListener('touchstart', dismiss, true);
        screen.removeEventListener('click', dismiss, true);
        document.removeEventListener('keydown', dismiss, true);
      };
      $pages.addEventListener('scroll', dismiss, { passive: true });
      screen.addEventListener('touchstart', dismiss, true);
      screen.addEventListener('click', dismiss, true);
      document.addEventListener('keydown', dismiss, true);
      setTimeout(dismiss, 5000);
    }
  }

  try {
    const data = await loadSession(examCode, sessionCode);
    const p = progressFor(examCode, sessionCode);
    state.current = {
      examCode, code: sessionCode, data,
      idx: startIdx != null ? startIdx : (p.last || 0),
      mode: p.mode || 'practice',
      examMin: p.examMin || 90,
      screen,
    };
    updateModeLabel();
    store.set('quizVisits', (store.get('quizVisits') || 0) + 1);
    setTimeout(() => { try { maybeShowPwaBanner(); } catch {} }, 1500);

    const $pages = screen.querySelector('#pages');
    _hydratedQs.clear();
    _explainBodyCache.clear();
    $pages.innerHTML = data.questions.map((q,i) => renderPageSkeleton(i)).join('');
    hydrateWindow(state.current.idx);

    // concept index 백그라운드 로드 — 도착하면 hydrated 페이지의 chip 라벨 갱신
    loadConceptIndex(examCode).then(() => {
      if (state.current && state.current.code === sessionCode) refreshConceptChips();
    });

    if (state.current.mode === 'exam') startExamTimer();
    requestAnimationFrame(() => {
      $pages.scrollTo({ left: state.current.idx * $pages.clientWidth, behavior: 'instant' });
      updatePositionIndicators();
      // Kick off lazy loading of renderers — only what this session actually needs
      const needs = detectSessionRendererNeeds(data.questions);
      state.current._needsMermaid = needs.mermaid;
      state.current._needsKatex = needs.katex;
      if (needs.katex || needs.mermaid) {
        ensureRenderers(needs).then(() => {
          if (needs.katex) renderPendingFormulas($pages);
          if (needs.mermaid) renderPendingMermaid($pages);
        });
      }
    });

    let t; $pages.addEventListener('scroll', () => {
      clearTimeout(t); t = setTimeout(() => {
        // Guard against firing after the screen was popped or replaced —
        // state.current may be null or pointing at a different session.
        if (!state.current || state.current.code !== sessionCode) return;
        const i = Math.round($pages.scrollLeft / $pages.clientWidth);
        if (i !== state.current.idx) {
          state.current.idx = i;
          const pr = progressFor(examCode, sessionCode); pr.last = i;
          saveProgress(examCode, sessionCode, pr);
          hydrateWindow(i);
          updatePositionIndicators();
        }
      }, 90);
    });

    $pages.addEventListener('click', onChoiceClick);
    addEdgeBack(screen);
    document.addEventListener('keydown', onKey);
    screen.querySelector('#jumpTot').textContent = data.questions.length;
  } catch (e) {
    screen.querySelector('#pages').innerHTML = emptyCard('회차 데이터를 찾을 수 없어요', e.message || '');
  }
}

/* ===================================================================
   CONCEPTS — 자격증별 개념 목록 (탭)
   =================================================================== */
async function renderConcepts(root){
  root.innerHTML = `
    <header class="nav" id="nav">
      <div></div>
      <div class="nav-title">개념</div>
      <div></div>
    </header>
    <div class="scroll" id="conceptsScroll">
      <div class="large-title">
        <div class="kicker">STUDY · CONCEPTS</div>
        <h1>개념<br><em>공부하기</em></h1>
      </div>
      <div id="conceptsExamList">${[0,1,2,3].map(()=>'<div class="skeleton" style="height:96px;margin:8px 16px"></div>').join('')}</div>
    </div>
  `;
  attachScrollShadow('conceptsScroll','nav');

  try {
    const exams = await loadExams();
    fillConceptsExamPicker(root, exams);
  } catch (e) {
    document.getElementById('conceptsExamList').innerHTML = emptyCard('목록을 불러오지 못했어요',
      'data/exams.json을 확인해 주세요');
  }
}

function fillConceptsExamPicker(root, exams){
  const examMark = { s2:'사조분', g1:'공인1', g2:'공인2', iz:'정처기', sa:'산안기',
                     c1:'컴활1', k1:'한국사', kt:'전기', nd:'소방기' };
  root.querySelector('#conceptsExamList').innerHTML = `
    <div class="section-head"><h2>자격증 선택</h2><span class="meta">${exams.length} EXAMS</span></div>
    <div class="group">
      ${exams.map(e => {
        const mark = examMark[e.code] || '◐';
        return `<button class="row exam-row" data-exam="${e.code}">
          <span class="row-lead exam-mark">${mark}</span>
          <span class="row-body">
            <span class="row-title">${escapeHtml(e.name)}</span>
            <span class="row-sub" id="conceptsCount-${e.code}">개념 불러오는 중…</span>
          </span>
          <span class="row-trail">${icons.chev}</span>
        </button>`;
      }).join('')}
    </div>
  `;
  // lazy-fill counts (background, no blocking)
  for (const e of exams) {
    loadConceptIndex(e.code).then(idx => {
      const el = root.querySelector(`#conceptsCount-${e.code}`);
      if (!el) return;
      if (!idx) { el.textContent = '개념 데이터 없음'; return; }
      const total = Object.keys(idx).length;
      const withBody = Object.values(idx).filter(m => m && m.body).length;
      el.textContent = `${total.toLocaleString()}개 개념 · 본문 ${withBody.toLocaleString()}개`;
    }).catch(()=>{});
  }
  root.querySelectorAll('.exam-row').forEach(el => {
    el.addEventListener('click', () => openConceptList(el.dataset.exam));
  });
}

async function openConceptList(examCode){
  state.currentExam = examCode;
  if (!_navInternal) pushRoute({ type:'concept-list', exam:examCode });
  const stack = document.getElementById('stack');
  const screen = document.createElement('section');
  screen.className = 'screen enter-right';
  const exam = state.examByCode.get(examCode);
  screen.innerHTML = `
    <header class="nav has-title" id="clNav">
      <button class="icon-btn" id="clBack" aria-label="뒤로">${icons.back}</button>
      <div class="nav-title">${escapeHtml(exam?.name || '개념')}</div>
      <div></div>
    </header>
    <div class="scroll" id="clScroll">
      <div class="large-title">
        <div class="kicker">${escapeHtml((exam?.name||'').slice(0,6).toUpperCase())} · CONCEPTS</div>
        <h1>개념 목록</h1>
      </div>
      <div class="search-bar"><input type="search" id="clSearch" placeholder="개념명 검색 (한글/영문)" inputmode="search" autocomplete="off"></div>
      <div id="clBody"><div class="skeleton" style="height:80px;margin:8px 16px"></div></div>
    </div>
  `;
  stack.appendChild(screen);
  updateScreenInert();
  attachScrollShadow('clScroll','clNav');
  screen.querySelector('#clBack').onclick = popScreen;
  addEdgeBack(screen);

  const idx = await loadConceptIndex(examCode);
  const $body = screen.querySelector('#clBody');
  if (!idx) {
    $body.innerHTML = emptyCard('개념 데이터를 불러오지 못했어요', '');
    return;
  }
  const all = Object.values(idx);
  // group by primary subject
  const bySubj = new Map();
  for (const m of all) {
    const s = (m.subjects && m.subjects[0]) || '기타';
    if (!bySubj.has(s)) bySubj.set(s, []);
    bySubj.get(s).push(m);
  }
  // sort each group by ref count desc, name asc
  for (const list of bySubj.values()) {
    list.sort((a,b) => ((b.refs?.length||0) - (a.refs?.length||0)) || a.name_ko.localeCompare(b.name_ko, 'ko'));
  }
  const subjects = Array.from(bySubj.keys()).sort((a,b) => a.localeCompare(b, 'ko'));

  const renderList = (q) => {
    const ql = (q||'').trim().toLowerCase();
    const html = subjects.map((subj, si) => {
      const list = bySubj.get(subj);
      const filtered = ql
        ? list.filter(m =>
            (m.name_ko && m.name_ko.toLowerCase().includes(ql)) ||
            (m.name_en && m.name_en.toLowerCase().includes(ql)))
        : list;
      if (!filtered.length) return '';
      // collapse all by default; auto-open only while searching
      const open = !!ql;
      const rowsHtml = filtered.map(m => {
        const snip = m.body && m.body.definition ? firstSentence(m.body.definition) : '';
        const enLine = m.name_en ? `<span class="concept-list-en">${escapeHtml(m.name_en)}</span>` : '';
        const snipLine = snip ? `<span class="concept-list-snippet">${escapeHtml(snip)}</span>` : '';
        const draftPill = m.body ? '' : ' <span class="pill subtle">초안</span>';
        return `<button class="row concept-list-row" data-cid="${escapeHtml(m.id)}">
          <span class="row-body">
            <span class="row-title">${escapeHtml(m.name_ko)}${draftPill}</span>
            ${enLine}
            ${snipLine}
          </span>
          <span class="row-trail">
            <span class="pill">${(m.refs?.length||0)}</span>
            ${icons.chev}
          </span>
        </button>`;
      }).join('');
      return `
        <details class="concept-subj" ${open ? 'open' : ''}>
          <summary>
            <span class="concept-subj-name">${escapeHtml(subj)}</span>
            <span class="concept-subj-count">${filtered.length.toLocaleString()}</span>
          </summary>
          <div class="group">${rowsHtml}</div>
        </details>
      `;
    }).join('');
    $body.innerHTML = html || emptyCard('검색 결과 없음', '');
    $body.querySelectorAll('.concept-list-row').forEach(b => {
      b.addEventListener('click', () => openConcept(examCode, b.dataset.cid).catch(()=>{}));
    });
  };
  renderList('');
  bindSearch(screen.querySelector('#clSearch'), renderList);
}

/* ===================================================================
   CONCEPT detail + practice
   =================================================================== */
async function openConcept(examCode, conceptId){
  if (!_navInternal) pushRoute({ type:'concept', exam:examCode, id:conceptId });
  const stack = document.getElementById('stack');
  const screen = document.createElement('section');
  screen.className = 'screen enter-right';
  screen.dataset.kind = 'concept';
  screen.dataset.exam = examCode;
  screen.innerHTML = `
    <header class="nav has-title" id="conceptNav">
      <button class="icon-btn" id="conceptBack" aria-label="뒤로">${icons.back}</button>
      <div class="nav-title" id="conceptNavTitle">개념</div>
      <div></div>
    </header>
    <div class="scroll" id="conceptScroll">
      <div class="concept-loading">${'<div class="skeleton"></div>'.repeat(4)}</div>
    </div>
    <button class="page-nav prev" id="conceptPrev" type="button" aria-label="이전 개념" hidden>${icons.back}</button>
    <button class="page-nav next" id="conceptNext" type="button" aria-label="다음 개념" hidden>${icons.back}</button>
  `;
  stack.appendChild(screen);
  updateScreenInert();
  screen.querySelector('#conceptBack').onclick = popScreen;
  addEdgeBack(screen);
  addConceptSwipe(screen);

  const $prev = screen.querySelector('#conceptPrev');
  const $next = screen.querySelector('#conceptNext');
  $prev.onclick = () => {
    const id = screen.dataset.prev;
    if (id) navigateConcept(screen, examCode, id);
  };
  $next.onclick = () => {
    const id = screen.dataset.next;
    if (id) navigateConcept(screen, examCode, id);
  };

  await fillConceptScreen(screen, examCode, conceptId);
}

function computeConceptSiblings(idx, conceptId){
  const meta = idx[conceptId];
  if (!meta) return { prev: null, next: null, pos: 0, total: 0, subject: '' };
  const subject = (meta.subjects && meta.subjects[0]) || '기타';
  const all = Object.values(idx)
    .filter(m => ((m.subjects && m.subjects[0]) || '기타') === subject)
    .sort((a,b) => ((b.refs?.length||0) - (a.refs?.length||0)) || (a.name_ko||'').localeCompare(b.name_ko||'', 'ko'));
  const i = all.findIndex(m => m.id === conceptId);
  return {
    prev: i > 0 ? all[i-1] : null,
    next: i >= 0 && i < all.length - 1 ? all[i+1] : null,
    pos: i + 1,
    total: all.length,
    subject,
  };
}

function navigateConcept(screen, examCode, newId){
  history.replaceState(
    { ...history.state, type:'concept', exam:examCode, id:newId },
    '', `/concept/${examCode}/${encodeURIComponent(newId)}`
  );
  fillConceptScreen(screen, examCode, newId).catch(()=>{});
}

async function fillConceptScreen(screen, examCode, conceptId){
  screen.dataset.cid = conceptId;
  const $body  = screen.querySelector('#conceptScroll');
  const $title = screen.querySelector('#conceptNavTitle');
  const $prev  = screen.querySelector('#conceptPrev');
  const $next  = screen.querySelector('#conceptNext');
  $body.innerHTML = `<div class="concept-loading">${'<div class="skeleton"></div>'.repeat(4)}</div>`;

  const idx = await loadConceptIndex(examCode);
  const meta = idx && idx[conceptId];
  if (!meta) {
    $body.innerHTML = emptyCard('개념을 찾을 수 없어요', conceptId);
    $prev.hidden = true; $next.hidden = true;
    screen.dataset.prev = ''; screen.dataset.next = '';
    return;
  }

  const sib = computeConceptSiblings(idx, conceptId);
  screen.dataset.prev = sib.prev?.id || '';
  screen.dataset.next = sib.next?.id || '';
  // quiz 와 동일 패턴: 항상 노출 + 경계에서 disabled
  $prev.hidden = false; $prev.disabled = !sib.prev;
  $next.hidden = false; $next.disabled = !sib.next;

  $title.textContent = meta.name_ko;
  const examShort = ({ s2:'사조분', g1:'공인1', g2:'공인2', iz:'정처기', sa:'산안기' })[examCode] || examCode;
  const subjList = (meta.subjects || []).join(' · ');
  const refs = meta.refs || [];
  const refsHtml = refs.map(r => `
    <button class="row concept-ref" data-exam="${examCode}" data-sess="${r.session}" data-q="${r.qnum}">
      <span class="row-lead exam-mark">${examShort}</span>
      <span class="row-body">
        <span class="row-title">${r.session.slice(0,4)}.${r.session.slice(4,6)}.${r.session.slice(6,8)} · ${r.qnum}번</span>
        <span class="row-sub">모아풀기에서 풀기</span>
      </span>
      <span class="row-trail">${icons.chev || '›'}</span>
    </button>
  `).join('');

  const pagerHtml = sib.total > 1
    ? `<div class="concept-pager-bar">
         <span class="kicker">${escapeHtml(sib.subject)}</span>
         <span class="pos">${sib.pos} <span>/</span> ${sib.total}</span>
       </div>`
    : '';

  $body.innerHTML = `
    ${pagerHtml}
    <div class="large-title">
      <div class="kicker">${escapeHtml(examShort)} · CONCEPT</div>
      <h1>${escapeHtml(meta.name_ko)}</h1>
      ${meta.name_en ? `<div class="concept-en">${escapeHtml(meta.name_en)}</div>` : ''}
      <div class="concept-meta">${escapeHtml(subjList)} · ${refs.length}문항 등장</div>
    </div>

    ${renderConceptBody(meta.body)}

    <div class="section-head">
      <h2>이 개념을 사용한 문제</h2>
      <span class="meta">${refs.length} 문항</span>
    </div>
    <div class="concept-actions">
      <button class="r-primary" id="conceptPracticeBtn" ${refs.length === 0 ? 'disabled' : ''}>
        ${refs.length}문제 모아 풀기
      </button>
    </div>
    <div class="concept-refs">${refsHtml || '<div class="empty">관련 문제 없음</div>'}</div>
  `;
  $body.scrollTop = 0;

  $body.querySelector('#conceptPracticeBtn')?.addEventListener('click', () => {
    openConceptPractice(examCode, conceptId).catch(e => {
      console.error(e); toast('연습 모드 시작 실패');
    });
  });
  $body.querySelectorAll('.concept-ref').forEach(b => {
    b.addEventListener('click', () => {
      const sc = b.dataset.sess, qn = +b.dataset.q;
      openConceptPractice(examCode, conceptId, { session: sc, qnum: qn }).catch(e => {
        console.error(e); toast('연습 모드 시작 실패');
      });
    });
  });
}

function addConceptSwipe(screen){
  let startX = 0, startY = 0, tracking = false, decided = false, dir = null;
  screen.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) { tracking = false; return; }
    const t = e.touches[0];
    if (t.clientX < 24) { tracking = false; return; }   // edge: leave to addEdgeBack
    startX = t.clientX; startY = t.clientY;
    tracking = true; decided = false; dir = null;
  }, { passive: true });
  screen.addEventListener('touchmove', e => {
    if (!tracking || decided) return;
    const t = e.touches[0];
    const dx = Math.abs(t.clientX - startX);
    const dy = Math.abs(t.clientY - startY);
    if (dx < 8 && dy < 8) return;
    dir = dx > dy ? 'h' : 'v';
    decided = true;
  }, { passive: true });
  screen.addEventListener('touchend', e => {
    const wasH = tracking && decided && dir === 'h';
    tracking = false;
    if (!wasH) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - startX;
    if (Math.abs(dx) < 60) return;
    const exam = screen.dataset.exam;
    if (dx < 0 && screen.dataset.next) navigateConcept(screen, exam, screen.dataset.next);
    else if (dx > 0 && screen.dataset.prev) navigateConcept(screen, exam, screen.dataset.prev);
  });
}

document.addEventListener('keydown', (e) => {
  if (e.target && e.target.matches && e.target.matches('input, textarea, select, [contenteditable]')) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const top = document.querySelector('#stack > .screen:last-child');
  if (!top || top.dataset.kind !== 'concept') return;
  const exam = top.dataset.exam;
  if (e.key === 'ArrowRight' && top.dataset.next) {
    e.preventDefault(); navigateConcept(top, exam, top.dataset.next);
  } else if (e.key === 'ArrowLeft' && top.dataset.prev) {
    e.preventDefault(); navigateConcept(top, exam, top.dataset.prev);
  }
});

async function openConceptPractice(examCode, conceptId, startRef){
  // 가상 세션: refs 의 (session, qnum) 들에서 question 들을 모아 새 questions 배열을 만든다.
  // startRef = { session, qnum } 이 주어지면 해당 문제로 시작.
  if (!_navInternal) pushRoute({ type:'concept-practice', exam:examCode, id:conceptId });
  const idx = await loadConceptIndex(examCode);
  const meta = idx && idx[conceptId];
  if (!meta || !(meta.refs || []).length) { toast('관련 문제가 없어요'); return; }

  // 필요한 회차 모두 로드
  const sessSet = Array.from(new Set(meta.refs.map(r => r.session)));
  const sessions = await Promise.all(sessSet.map(sc => loadSession(examCode, sc).catch(() => null)));
  const sessionMap = new Map(sessSet.map((sc, i) => [sc, sessions[i]]));

  // refs 순서대로 question 객체 모으기
  const questions = [];
  for (const r of meta.refs) {
    const data = sessionMap.get(r.session);
    if (!data) continue;
    const q = (data.questions || []).find(qq => qq.number === r.qnum);
    if (q) {
      // 원본 질문 그대로 — 별도 _origin 표시
      questions.push({ ...q, _originSession: r.session });
    }
  }
  if (!questions.length) { toast('문제 데이터를 불러오지 못했어요'); return; }

  let startIdx;
  if (startRef && startRef.session && startRef.qnum != null) {
    const i = questions.findIndex(q => q._originSession === startRef.session && q.number === startRef.qnum);
    if (i >= 0) startIdx = i;
  }

  // 가상 세션 데이터 구성
  const virtData = {
    exam: state.examByCode.get(examCode)?.name || examCode,
    dbname: examCode,
    date: `concept-${conceptId}`,
    label: meta.name_ko,
    count: questions.length,
    questions,
  };
  const virtSessionCode = `c-${conceptId}`;
  state.dataCache.set(`${examCode}:${virtSessionCode}`, virtData);

  // openQuiz 가 다시 pushRoute 하지 않도록 잠시 navInternal flag 켠다
  const wasInternal = _navInternal;
  _navInternal = true;
  try {
    await openQuiz(examCode, virtSessionCode, startIdx);
  } finally {
    _navInternal = wasInternal;
  }
  // quiz nav title 을 개념 모드용으로 덮어쓰기 (회차 코드가 'c-...' 라 기본 포맷이 깨짐)
  const $title = state.current?.screen.querySelector('.quiz-nav-title');
  if ($title) {
    $title.querySelector('.d').textContent = meta.name_ko;
    $title.querySelector('.s').textContent = `개념 모아 풀기 · ${meta.refs.length}문제`;
  }
}

function updateScreenInert(){
  const screens = document.querySelectorAll('#stack > .screen');
  const top = screens[screens.length - 1];
  // 만약 비활성 처리할 화면 안에 포커스가 남아 있으면 inert 적용 전에 blur.
  // (aria-hidden 동시 적용은 브라우저 콘솔 경고를 유발하므로 inert 만 사용)
  if (top && document.activeElement && top.contains(document.activeElement) === false) {
    try { document.activeElement.blur(); } catch {}
  }
  screens.forEach(s => {
    if (s === top) {
      s.removeAttribute('inert');
      s.removeAttribute('aria-hidden');
    } else {
      if (s.contains(document.activeElement)) {
        try { document.activeElement.blur(); } catch {}
      }
      s.setAttribute('inert', '');
      s.removeAttribute('aria-hidden');
    }
  });
}

function popScreen(){
  // User-initiated back (button/edge swipe/Esc): drive via history so URL stays in sync.
  // popstate handler will then call doPopScreen.
  if ((history.state?.depth || 0) > 0) {
    history.back();
  } else {
    doPopScreen();
  }
}

function doPopScreen(immediate = false){
  const stack = document.getElementById('stack');
  if (stack.children.length <= 1) return;
  const last = stack.lastElementChild;

  // 퀴즈 화면이 실제로 사라지는 경우에만 quiz state 를 해제한다.
  // 퀴즈 위에 쌓인 concept 등을 pop 하면 quiz state 는 유지되어야 한다
  // (그래야 보기 클릭/스크롤 핸들러가 계속 작동).
  const poppingQuiz = state.current && state.current.screen === last;

  document.getElementById('shell').classList.remove('hide-tabs');
  if (poppingQuiz) {
    stopExamTimer();
    document.removeEventListener('keydown', onKey);
    state.current = null;
  }

  const finish = () => {
    last.remove();
    updateScreenInert();
    const top = stack.lastElementChild;
    if (top) {
      if (top.dataset.tab) {
        showTab(top.dataset.tab);
      } else if (state.currentExam) {
        loadSessions(state.currentExam).then(s => fillSessionList(top, state.currentExam, s)).catch(()=>{});
      }
    }
    if (stack.children.length <= 1) showInterstitialAd();
  };

  if (immediate) {
    finish();
    return;
  }

  last.classList.remove('enter-right');
  last.classList.add('exit-right');
  // animationend 누락(브라우저별 reduced-motion·hidden 등) 대비 fallback
  let done = false;
  const safe = () => { if (done) return; done = true; finish(); };
  last.addEventListener('animationend', safe, { once: true });
  setTimeout(safe, 400);
}

/* Ad management */
let _adCooldown = 0;
function showInterstitialAd(){
  if (!ADSENSE.client || !ADSENSE.slots.interstitial) return;
  const now = Date.now();
  if (now - _adCooldown < 120000) return;
  _adCooldown = now;
  const el = document.createElement('div');
  el.className = 'ad-slot-interstitial';
  el.innerHTML = `<span class="ad-label">ADVERTISEMENT</span>
    <div class="ad-container">${adInsHTML(ADSENSE.slots.interstitial, { format:'rectangle', fullWidth:false })}</div>
    <button class="ad-close">닫기</button>`;
  el.querySelector('.ad-close').onclick = () => el.remove();
  document.body.appendChild(el);
  pushAd(el);
}

function renderExtras(arr){
  if (!arr || !arr.length) return '';
  return `<div class="extras">${arr.map(e => renderExtra(e)).join('')}</div>`;
}
function renderImagesFallback(arr, label){
  if (!arr || !arr.length) return '';
  const lbl = label || '문항 이미지';
  return arr.map((src, i) => `<div class="qimg"><img src="${src}" loading="lazy" alt="${escapeHtml(lbl)} ${i+1}"></div>`).join('');
}

function renderPageSkeleton(i){
  return `<article class="page" data-qi="${i}"></article>`;
}

function renderQuestionInner(q, i, total){
  const subj = escapeHtml(q.subject || '');
  const qExtras = renderExtras(q.question_extras) || renderImagesFallback(q.question_images, `문제 ${q.number} 이미지`);
  const choicesHtml = (q.choices || []).map((c, ci) => {
    const num = ['①','②','③','④'][ci] || (ci+1);
    const extras = renderExtras(c.extras) ||
                   (c.images || []).map((s, ii) => `<img src="${s}" loading="lazy" alt="보기 ${num} 이미지${(c.images.length>1)?' '+(ii+1):''}">`).join('');
    return `
      <button class="choice" data-qi="${i}" data-ci="${ci+1}">
        <span class="num">${num}</span>
        <span class="body">${escapeHtml(c.text||'')}${extras}</span>
      </button>`;
  }).join('');
  const rate = (q.pass_rate!=null) ? `<span class="passrate">정답률 <b>${q.pass_rate}%</b></span>` : '';
  return `<div class="subject-pill">${subj}</div>
      <div class="qnum">${q.number}<small>· ${i+1}/${total}</small></div>
      <div class="qbody">${escapeHtml(q.question)}</div>
      ${qExtras}
      <div class="qmeta">${rate}</div>
      <div class="choices">${choicesHtml}</div>
      <div class="explain-slot"></div>`;
}

const HYDRATION_RADIUS = 2;
const _hydratedQs = new Set();

function hydratePage(idx){
  if (_hydratedQs.has(idx)) return;
  const c = state.current; if (!c) return;
  const qs = c.data && c.data.questions; if (!qs || idx < 0 || idx >= qs.length) return;
  const page = c.screen.querySelector(`.page[data-qi="${idx}"]`);
  if (!page) return;
  const q = qs[idx];
  page.innerHTML = renderQuestionInner(q, idx, qs.length);
  _hydratedQs.add(idx);
  applyAnswerForPage(page, q);
}

function hydrateWindow(centerIdx){
  for (let i = centerIdx - HYDRATION_RADIUS; i <= centerIdx + HYDRATION_RADIUS; i++) hydratePage(i);
  const c = state.current; if (!c) return;
  const $pages = c.screen.querySelector('#pages');
  if (c._needsKatex && window.katex) renderPendingFormulas($pages);
  if (c._needsMermaid && window.mermaid) renderPendingMermaid($pages);
}

function applyAnswerForPage(page, q){
  const c = state.current; if (!c) return;
  const p = progressFor(c.examCode, c.code);
  const review = c.mode === 'review';
  const picked = p.answers[q.number];
  if (review) { markChoices(page, q, q.answer); renderExplain(page, q, true); }
  else if (picked) { markChoices(page, q, picked); renderExplain(page, q, false); }
  else {
    page.querySelectorAll('.choice').forEach(b => b.classList.remove('picked','correct','wrong'));
    const slot = page.querySelector('.explain-slot');
    if (slot) slot.innerHTML = '';
  }
}

function applyAnswers(){
  const c = state.current; if (!c) return;
  for (const idx of _hydratedQs) {
    const page = c.screen.querySelector(`.page[data-qi="${idx}"]`);
    if (page) applyAnswerForPage(page, c.data.questions[idx]);
  }
  updatePositionIndicators();
}

function markChoices(page, q, picked){
  page.querySelectorAll('.choice').forEach(b => {
    const ci = +b.dataset.ci;
    b.classList.remove('picked','correct','wrong');
    if (ci === q.answer) b.classList.add('correct');
    else if (ci === picked && picked !== q.answer) b.classList.add('wrong');
  });
}

function cleanExplanation(s){
  if (!s) return '';
  s = s.replace(/^[>\s]+/, '');
  s = s.replace(/\n{3,}/g, '\n\n');
  return s.trim();
}
function formatDetailed(raw){
  if (!raw) return '';
  // Turn section headings into bold separators
  const lines = raw.split(/\r?\n/);
  const out = [];
  for (const ln of lines) {
    const t = ln.trim();
    if (/^(핵심 개념|정답 분석|오답 분석|참고)$/.test(t)) {
      out.push(`<h5>${t}</h5>`);
    } else if (t) {
      // bullets starting with ①②③④- •
      out.push(`<p>${escapeWithMath(t)}</p>`);
    } else {
      out.push('');
    }
  }
  return out.join('\n');
}

const _explainBodyCache = new Map();
function renderExplain(page, q, force){
  const slot = page.querySelector('.explain-slot');
  const hasDetailed = !!q.explanation_detailed;
  const hasExtras = !!(q.explanation_extras && q.explanation_extras.length);
  const hasBasic = !!(q.explanation || hasExtras || (q.explanation_images||[]).length);
  if (!force && !hasDetailed && !hasBasic) { slot.innerHTML=''; return; }

  // default: show detailed if available, toggle to basic
  const pref = store.get('expPref') || (hasDetailed ? 'detailed' : 'basic');
  const cur = pref === 'detailed' && !hasDetailed ? 'basic' :
              pref === 'basic'    && !(q.explanation || '').trim() ? 'detailed' : pref;

  const cacheKey = `${state.current?.code || ''}::${q.number}::${cur}`;
  let cached = _explainBodyCache.get(cacheKey);
  if (!cached) {
    const imgs = hasExtras ? renderExtras(q.explanation_extras)
                 : (q.explanation_images || []).map((s, i) => `<img src="${s}" loading="lazy" alt="해설 이미지 ${i+1}">`).join('');
    const basicText = escapeHtml(cleanExplanation(q.explanation) || '').trim();
    const detailedHtml = formatDetailed(q.explanation_detailed || '');
    cached = { basicText, detailedHtml, imgs };
    _explainBodyCache.set(cacheKey, cached);
  }
  const { basicText, detailedHtml, imgs } = cached;

  const toggle = hasDetailed && basicText ? `
    <div class="explain-switch">
      <button data-exp="detailed" class="${cur==='detailed'?'on':''}">상세 해설</button>
      <button data-exp="basic" class="${cur==='basic'?'on':''}">간단 해설</button>
    </div>` : '';

  const body = cur === 'detailed' && hasDetailed
    ? `<div class="explain-body detailed">${detailedHtml}${imgs}</div>`
    : `<div class="explain-body">${basicText || '(해설 없음)'}${imgs}</div>`;

  const label = toggle
    ? ''
    : `<span class="explain-label">${cur==='detailed' ? '상세 해설' : '문제 해설'}</span>`;
  const chips = renderConceptChips(q);
  const ad = ADSENSE.client && ADSENSE.slots.postAnswer
    ? `<div class="ad-slot ad-slot-explain">${adInsHTML(ADSENSE.slots.postAnswer)}</div>`
    : '';
  const feedback = `<div class="explain-feedback">
    <button class="report-btn" type="button">이 해설에 오류가 있나요?</button>
  </div>`;

  slot.innerHTML = `<section class="explain">
    ${label}
    ${toggle}
    ${body}
    ${chips}
    ${ad}
    ${feedback}
  </section>`;

  const sw = slot.querySelector('.explain-switch');
  if (sw) sw.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    store.set('expPref', b.dataset.exp);
    renderExplain(page, q, force);
  });
  const reportBtn = slot.querySelector('.report-btn');
  if (reportBtn) reportBtn.onclick = () => openFeedbackSheet({
    examCode: state.current?.examCode,
    sessionCode: state.current?.code,
    qnum: q.number,
  });
  if (ad) pushAd(slot);
}

function refreshConceptChips(){
  // conceptIndex 가 늦게 도착했을 때, 이미 hydrated 된 chip 들의 라벨만 갱신.
  const c = state.current; if (!c) return;
  const idx = state.conceptIndex.get(c.examCode);
  if (!idx) return;
  c.screen.querySelectorAll('.concept-chip[data-cid]').forEach(el => {
    const meta = idx[el.dataset.cid];
    if (meta && meta.name_ko) el.textContent = meta.name_ko;
  });
}

function renderConceptBody(body){
  if (!body || !body.definition) {
    return `
      <div class="concept-body-placeholder">
        <span class="ideo">未</span>
        <p>개념 본문은 곧 추가됩니다.<br><small>정의·직관·핵심 공식·자주 헷갈리는 점·작은 예시</small></p>
      </div>`;
  }
  const kp = (body.key_points || []).filter(Boolean);
  const sec = (label, kicker, content) => content ? `
    <section class="concept-section">
      <div class="concept-section-head"><span class="kicker">${kicker}</span><h3>${label}</h3></div>
      <div class="concept-section-body">${content}</div>
    </section>` : '';
  const kpHtml = kp.length ? `<ul class="concept-keypoints">${kp.map(p => `<li>${escapeHtml(p)}</li>`).join('')}</ul>` : '';
  return `
    <div class="concept-body">
      ${sec('정의', 'DEFINITION', `<p>${escapeHtml(body.definition)}</p>`)}
      ${sec('직관', 'INTUITION', `<p>${escapeHtml(body.intuition || '')}</p>`)}
      ${sec('핵심 포인트', 'KEY POINTS', kpHtml)}
      ${sec('자주 헷갈리는 점', 'PITFALLS', `<p>${escapeHtml(body.pitfalls || '')}</p>`)}
      ${sec('작은 예시', 'EXAMPLE', `<p>${escapeHtml(body.example || '')}</p>`)}
    </div>`;
}

function renderConceptChips(q){
  const ids = q.concept_ids || [];
  if (!ids.length) return '';
  const examCode = state.current?.examCode;
  if (!examCode) return '';
  const idx = state.conceptIndex.get(examCode);
  // 인덱스가 아직 안 왔으면 raw concepts 기반으로 폴백 표기 (id만)
  const items = ids.map(id => {
    const meta = idx && idx[id];
    const label = (meta && meta.name_ko) || id;
    return `<a class="concept-chip" data-cid="${escapeHtml(id)}" href="/concept/${examCode}/${encodeURIComponent(id)}">${escapeHtml(label)}</a>`;
  }).join('');
  return `<div class="concept-chips">
    <span class="concept-chips-label">관련 개념</span>
    ${items}
  </div>`;
}

function onChoiceClick(e){
  const b = e.target.closest('.choice'); if (!b) return;
  const c = state.current;
  if (!c) return;  // quiz state 가 사라진 상태 — 방어적 가드
  if (c.mode === 'review') return;
  const qi = +b.dataset.qi;
  const ci = +b.dataset.ci;
  const q = c.data.questions[qi];
  const p = progressFor(c.examCode, c.code);
  if (p.answers[q.number]) return;
  p.answers[q.number] = ci;
  p.last = qi;
  p.wrongs = p.wrongs || [];
  p.seenAt = p.seenAt || {};
  p.seenAt[q.number] = Date.now();
  if (ci !== q.answer && !p.wrongs.includes(q.number)) p.wrongs.push(q.number);
  saveProgress(c.examCode, c.code, p);
  const page = b.closest('.page');
  markChoices(page, q, ci);
  renderExplain(page, q, false);
  updatePositionIndicators();
  haptic(ci === q.answer ? 'correct' : 'wrong');
  const isWrong = ci !== q.answer;
  toast(isWrong ? '오답' : '정답', isWrong ? 'wrong' : 'correct');
  maybeShowCompletion(c, p);
}

function toggleStar(){
  const c = state.current; if (!c) return;
  const p = progressFor(c.examCode, c.code);
  const q = c.data.questions[c.idx];
  p.stars = p.stars || [];
  const i = p.stars.indexOf(q.number);
  const btn = c.screen.querySelector('#starBtn');
  if (i>=0) { p.stars.splice(i,1); btn.classList.remove('on'); btn.querySelector('svg').outerHTML = icons.star; toast('북마크 해제'); }
  else {
    p.stars.push(q.number);
    btn.classList.add('on');
    btn.querySelector('svg').outerHTML = icons.starFill;
    if (!store.get('seen:firstStar')) {
      store.set('seen:firstStar', 1);
      toastAction('즐겨찾기에 저장됨', '모아보기', () => showTab('stars'));
    } else {
      toast('북마크');
    }
  }
  saveProgress(c.examCode, c.code, p);
}

function confirmRedo(){
  const c = state.current; if (!c) return;
  const p = progressFor(c.examCode, c.code);
  if (Object.keys(p.answers || {}).length === 0 && (p.wrongs || []).length === 0) {
    toast('이미 비어있어요'); return;
  }
  const snap = JSON.parse(JSON.stringify(p));
  p.answers = {}; p.wrongs = []; p.last = 0;
  saveProgress(c.examCode, c.code, p);
  applyAnswers();
  c.screen.querySelector('#pages').scrollTo({ left: 0, behavior: 'smooth' });
  toastAction('초기화됨', '되돌리기', () => {
    saveProgress(c.examCode, c.code, snap);
    applyAnswers();
    toast('복원됨');
  }, { duration: 7000 });
}

function updatePositionIndicators(){
  const c = state.current; if (!c) return;
  const p = progressFor(c.examCode, c.code);
  const i = c.idx;
  const q = c.data.questions[i];
  const total = c.data.questions.length;
  c.screen.querySelector('#jumpNum').textContent = i+1;
  c.screen.querySelector('#quizSub').textContent = q.subject || '';
  c.screen.querySelector('#pFill').style.width = ((i+1)/total*100).toFixed(1) + '%';
  const starBtn = c.screen.querySelector('#starBtn');
  const starred = (p.stars||[]).includes(q.number);
  starBtn.classList.toggle('on', starred);
  starBtn.querySelector('svg').outerHTML = starred ? icons.starFill : icons.star;
  const $prev = c.screen.querySelector('#pagePrev');
  const $next = c.screen.querySelector('#pageNext');
  if ($prev) { $prev.hidden = false; $prev.disabled = i <= 0; }
  if ($next) { $next.hidden = false; $next.disabled = i >= total - 1; }
}

function onKey(e){
  const c = state.current; if (!c) return;
  const pages = c.screen.querySelector('#pages'); if (!pages) return;
  if (e.key === 'ArrowRight') { e.preventDefault(); pages.scrollBy({left: pages.clientWidth, behavior:'smooth'}); }
  if (e.key === 'ArrowLeft')  { e.preventDefault(); pages.scrollBy({left:-pages.clientWidth, behavior:'smooth'}); }
  if (e.key === 'Escape')     { popScreen(); }
}

function addEdgeBack(screen){
  let startX = 0, tracking = false, startT = 0;
  screen.addEventListener('touchstart', e => {
    if (e.touches[0].clientX < 18) { tracking = true; startX = e.touches[0].clientX; startT = Date.now(); }
  }, { passive: true });
  screen.addEventListener('touchmove', e => {
    if (!tracking) return;
    const dx = e.touches[0].clientX - startX;
    if (dx > 10) screen.style.transform = `translate3d(${Math.min(dx, window.innerWidth)}px,0,0)`;
  }, { passive: true });
  screen.addEventListener('touchend', e => {
    if (!tracking) return;
    const dx = (e.changedTouches[0]?.clientX || 0) - startX;
    const dt = Date.now() - startT;
    screen.style.transform = '';
    tracking = false;
    if (dx > window.innerWidth * 0.35 || (dx > 80 && dt < 250)) popScreen();
  });
}

/* ===================================================================
   Sheets (jump / mode / theme)
   =================================================================== */
function openJumpSheet(){
  const c = state.current; if (!c) return;
  const p = progressFor(c.examCode, c.code);
  const total = c.data.questions.length;
  // Build subject chips
  const subjMap = new Map();
  c.data.questions.forEach((q, idx) => {
    const subj = (q.subject || '').replace(/^\d+과목\s*:\s*/, '').trim();
    if (!subj) return;
    if (!subjMap.has(subj)) subjMap.set(subj, idx);
  });
  showSheet('문제 바로가기', () => {
    const wrap = document.createElement('div');
    if (subjMap.size > 1) {
      const chips = document.createElement('div');
      chips.className = 'subj-chips';
      for (const [subj, firstIdx] of subjMap) {
        const c2 = document.createElement('button');
        c2.className = 'chip';
        c2.textContent = subj;
        c2.onclick = () => {
          closeSheet();
          const pages = state.current.screen.querySelector('#pages');
          pages.scrollTo({ left: firstIdx * pages.clientWidth, behavior: 'smooth' });
        };
        chips.appendChild(c2);
      }
      wrap.appendChild(chips);
    }
    const body = document.createElement('div');
    body.className = 'numpad';
    for (let i=1; i<=total; i++){
      const q = c.data.questions[i-1];
      const picked = p.answers[q.number];
      const done = picked != null;
      const wrong = done && picked !== q.answer;
      const cls = [
        done && !wrong ? 'done' : '',
        wrong ? 'wrong' : '',
        (p.stars||[]).includes(q.number) ? 'starred' : '',
      ].join(' ').trim();
      const b = document.createElement('button');
      b.className = cls;
      b.textContent = i;
      b.onclick = () => {
        closeSheet();
        const pages = c.screen.querySelector('#pages');
        pages.scrollTo({ left: (i-1) * pages.clientWidth, behavior: 'smooth' });
      };
      body.appendChild(b);
    }
    wrap.appendChild(body);
    return wrap;
  });
}

function openModeSheet(){
  const c = state.current; if (!c) return;
  showSheet('풀이 설정', () => {
    const div = document.createElement('div');
    div.innerHTML = `
      <div class="sheet-row">
        <span class="l">모드</span>
        <span class="seg" id="m">
          <button data-m="practice">풀이</button>
          <button data-m="review">해설</button>
          <button data-m="exam">모의시험</button>
        </span>
      </div>
      <div class="sheet-row exam-mins" hidden>
        <span class="l">시간</span>
        <span class="seg" id="mins">
          <button data-min="60">60분</button>
          <button data-min="90">90분</button>
          <button data-min="150">150분</button>
        </span>
      </div>
      <div class="sheet-row">
        <span class="l">재도전</span>
        <button class="r" id="sheetRedo">답안 초기화</button>
      </div>
    `;
    const minsRow = div.querySelector('.exam-mins');
    const mark = () => {
      div.querySelectorAll('#m button').forEach(b => b.classList.toggle('on', b.dataset.m === state.current.mode));
      minsRow.hidden = state.current.mode !== 'exam';
    };
    const markMins = () => div.querySelectorAll('#mins button').forEach(b => b.classList.toggle('on', +b.dataset.min === (state.current.examMin || 90)));
    mark(); markMins();
    div.querySelector('#m').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      state.current.mode = b.dataset.m;
      const p = progressFor(state.current.examCode, state.current.code); p.mode = b.dataset.m;
      saveProgress(state.current.examCode, state.current.code, p);
      if (b.dataset.m === 'exam') {
        state.current.examMin = state.current.examMin || 90;
        startExamTimer();
      } else {
        stopExamTimer();
      }
      mark(); applyAnswers(); updateModeLabel();
    });
    div.querySelector('#mins').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      state.current.examMin = +b.dataset.min;
      const p = progressFor(state.current.examCode, state.current.code);
      p.examMin = state.current.examMin;
      saveProgress(state.current.examCode, state.current.code, p);
      markMins();
      startExamTimer();
    });
    div.querySelector('#sheetRedo').onclick = () => { closeSheet(); confirmRedo(); };
    return div;
  });
}

/* ---- share / completion / exam timer ---- */
function legacyCopy(text){
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch { return false; }
}
async function shareCurrent(){
  const c = state.current; if (!c) { toast('퀴즈에서 공유하세요'); return; }
  const exam = state.examByCode.get(c.examCode);
  const url = `${location.origin}/exam/${c.examCode}/${c.code}`;
  const text = `${exam?.name || ''} ${c.code.slice(0,4)}.${c.code.slice(4,6)}.${c.code.slice(6,8)} 기출`;
  if (navigator.share) {
    try { await navigator.share({ title: 'passcbt.kr', text, url }); }
    catch { /* user cancel — silent */ }
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    toast('링크 복사됨');
  } catch {
    if (legacyCopy(url)) toast('링크 복사됨');
    else toast('복사 실패 — 주소창에서 직접 복사해주세요');
  }
}

function maybeShowCompletion(c, p){
  const total = c.data.questions.length;
  const answered = Object.keys(p.answers || {}).length;
  if (answered < total) return;
  if (c._completionShown) return;
  c._completionShown = true;
  showCompletion(c, p);
}

function showCompletion(c, p){
  const total = c.data.questions.length;
  const wrongs = (p.wrongs || []).length;
  const correct = total - wrongs;
  const pct = Math.round(correct * 100 / total);
  stopExamTimer();
  showSheet(c.mode === 'exam' ? '모의시험 결과' : '풀이 완료', () => {
    const div = document.createElement('div');
    div.innerHTML = `
      <div class="completion">
        <div class="comp-pct">${pct}<small>%</small></div>
        <div class="comp-line">${correct} / ${total} 정답${wrongs ? ` · 오답 ${wrongs}` : ''}</div>
        ${wrongs ? `<button class="r-primary" id="compReview">틀린 문제 다시 보기</button>` : ''}
        <div class="comp-actions">
          <button class="r-soft" id="compRedo">다시 풀기</button>
          <button class="r-soft" id="compShare">공유</button>
          <button class="r-soft" id="compExit">목록으로</button>
        </div>
      </div>
    `;
    div.querySelector('#compReview')?.addEventListener('click', () => {
      closeSheet();
      const wrongIdx = c.data.questions.findIndex(q => (p.wrongs||[]).includes(q.number));
      if (wrongIdx >= 0) {
        const $pages = c.screen.querySelector('#pages');
        $pages.scrollTo({ left: wrongIdx * $pages.clientWidth, behavior: 'smooth' });
      }
    });
    div.querySelector('#compRedo').onclick = () => { closeSheet(); confirmRedo(); };
    div.querySelector('#compShare').onclick = () => { closeSheet(); shareCurrent(); };
    div.querySelector('#compExit').onclick = () => { closeSheet(); popScreen(); };
    return div;
  });
}

let _examTimerId = null;
function startExamTimer(){
  stopExamTimer();
  const c = state.current; if (!c) return;
  const min = c.examMin || 90;
  c.examEndAt = Date.now() + min * 60 * 1000;
  const el = c.screen.querySelector('#quizTimer');
  if (!el) return;
  el.hidden = false;
  const tick = () => {
    const left = Math.max(0, c.examEndAt - Date.now());
    const m = Math.floor(left / 60000);
    const s = Math.floor((left % 60000) / 1000);
    el.textContent = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    el.classList.toggle('warn', left > 0 && left < 5 * 60000);
    if (left <= 0) {
      stopExamTimer();
      const p = progressFor(c.examCode, c.code);
      maybeShowCompletion(c, p);
    }
  };
  tick();
  _examTimerId = setInterval(tick, 1000);
}
function stopExamTimer(){
  if (_examTimerId) { clearInterval(_examTimerId); _examTimerId = null; }
  const c = state.current;
  const el = c?.screen?.querySelector('#quizTimer');
  if (el) { el.hidden = true; el.classList.remove('warn'); }
}

function openThemeSheet(){
  showSheet('표시', () => {
    const div = document.createElement('div');
    div.innerHTML = `<div class="sheet-row">
      <span class="l">화면</span>
      <span class="seg" id="tseg">
        <button data-t="system">자동</button>
        <button data-t="light">밝게</button>
        <button data-t="dark">어둡게</button>
      </span>
    </div>
    <div class="sheet-row">
      <span class="l">글자 크기</span>
      <span class="seg" id="fseg">
        <button data-fs="sm">작게</button>
        <button data-fs="md">보통</button>
        <button data-fs="lg">크게</button>
      </span>
    </div>`;
    const markT = () => div.querySelectorAll('#tseg button').forEach(b => b.classList.toggle('on', b.dataset.t === currentTheme()));
    const markF = () => div.querySelectorAll('#fseg button').forEach(b => b.classList.toggle('on', b.dataset.fs === currentFontSize()));
    markT(); markF();
    div.querySelector('#tseg').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      setTheme(b.dataset.t); markT();
      // update quick icon
      const q = document.getElementById('themeQuick');
      if (q) q.innerHTML = iconTheme(currentTheme());
    });
    div.querySelector('#fseg').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      setFontSize(b.dataset.fs); markF();
      // 설정 페이지의 동일 segment 도 동기화
      const otherSeg = document.getElementById('fontSeg');
      if (otherSeg) otherSeg.querySelectorAll('button').forEach(b2 => b2.classList.toggle('on', b2.dataset.fs===currentFontSize()));
    });
    return div;
  });
}

function showSheet(title, bodyFn){
  closeSheet();
  const bg = document.createElement('div');
  bg.className = 'sheet-backdrop';
  bg.onclick = closeSheet;
  document.body.appendChild(bg);
  const sheet = document.createElement('div');
  sheet.className = 'sheet';
  sheet.innerHTML = `<div class="sheet-handle"></div><h2>${title}</h2>`;
  sheet.appendChild(bodyFn());
  document.body.appendChild(sheet);
}
function closeSheet(){
  document.querySelectorAll('.sheet, .sheet-backdrop').forEach(el => {
    el.classList.add('closing');
    el.addEventListener('animationend', () => el.remove(), { once: true });
    // ensure removal even if anim conflicts
    setTimeout(()=>el.remove(), 500);
  });
}

/* ===================================================================
   Helpers
   =================================================================== */
function iconTheme(t){
  if (t==='dark') return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  if (t==='light') return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>';
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 000 18"/></svg>';
}
function escapeHtml(s){
  return (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}
function firstSentence(s){
  const t = (s||'').trim();
  if (!t) return '';
  const m = t.match(/^[^.。!?]*[.。!?]/);
  const out = m ? m[0] : t;
  return out.length > 110 ? out.slice(0, 108).trim() + '…' : out;
}
function emptyCard(title, sub){
  return `<div class="empty"><span class="ideo">空</span><h4>${title}</h4><p>${sub || ''}</p></div>`;
}
let toastTimer;
function toast(msg, kind){
  let t = document.getElementById('toast');
  if (!t) { t = document.createElement('div'); t.id='toast'; t.className='toast'; document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.remove('correct', 'wrong');
  if (kind) t.classList.add(kind);
  t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 1300);
}
function toastAction(msg, btnLabel, onClick, opts = {}){
  // Toast with action button. By default auto-dismisses after `duration` ms
  // and includes a close [✕] button. Pass { persistent: true } for sticky
  // toasts that only dismiss on action click (e.g. SW update prompt).
  const { duration = 5000, persistent = false, kind } = opts;
  let t = document.getElementById('toast-action');
  if (t) t.remove();
  t = document.createElement('div');
  t.id = 'toast-action';
  t.className = 'toast-action' + (kind ? ' ' + kind : '');
  const closeHtml = persistent ? '' : '<button class="toast-close" type="button" aria-label="닫기">✕</button>';
  t.innerHTML = `<span class="toast-msg">${escapeHtml(msg)}</span><button class="toast-act" type="button">${escapeHtml(btnLabel)}</button>${closeHtml}`;
  let dismissed = false;
  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    t.classList.remove('show');
    setTimeout(() => t.remove(), 240);
  };
  t.querySelector('.toast-act').onclick = () => { try { onClick(); } finally { dismiss(); } };
  if (!persistent) {
    t.querySelector('.toast-close')?.addEventListener('click', dismiss);
    setTimeout(dismiss, duration);
  }
  document.body.appendChild(t);
  requestAnimationFrame(() => t.classList.add('show'));
}
function haptic(kind){
  if (!navigator.vibrate) return;
  if (kind === 'correct') navigator.vibrate(10);
  else if (kind === 'wrong') navigator.vibrate([20, 30, 20]);
  else if (kind === 'tap') navigator.vibrate(8);
}
function attachScrollShadow(scrollId, navId){
  const s = document.getElementById(scrollId);
  const n = document.getElementById(navId);
  if (!s || !n) return;
  s.addEventListener('scroll', () => n.classList.toggle('is-scrolled', s.scrollTop > 4), { passive: true });
}

/* ===================================================================
   Router — path-based, syncs with screen stack
   =================================================================== */
let _navInternal = false;

function pathForState(s) {
  if (!s) return '/';
  if (s.type === 'session')          return `/exam/${s.exam}`;
  if (s.type === 'quiz')             return `/exam/${s.exam}/${s.session}`;
  if (s.type === 'concept-list')     return `/concepts/${s.exam}`;
  if (s.type === 'concept')          return `/concept/${s.exam}/${encodeURIComponent(s.id)}`;
  if (s.type === 'concept-practice') return `/concept/${s.exam}/${encodeURIComponent(s.id)}/practice`;
  return '/';
}

function pushRoute(state) {
  const path = pathForState(state);
  if (location.pathname === path) {
    // 같은 path 로 화면 재구성 시 history.state 의 type/payload 가 stale 로 남아
    // 이후 popstate 에서 depth 계산이 어긋날 수 있다 — depth 는 유지하고 state 만 보강.
    const curDepth = history.state?.depth || 0;
    history.replaceState({ ...state, depth: curDepth }, '', path);
    return;
  }
  const depth = (history.state?.depth || 0) + 1;
  history.pushState({ ...state, depth }, '', path);
}

// SPA 내 링크 — concept-chip 등 a[href^="/"] 클릭은 풀 reload 없이 처리
document.addEventListener('click', (e) => {
  const a = e.target.closest('a.concept-chip');
  if (!a) return;
  const href = a.getAttribute('href') || '';
  if (!href.startsWith('/')) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
  e.preventDefault();
  const m = href.match(/^\/concept\/([^/]+)\/([^/?#]+)/);
  if (!m) return;
  const examCode = m[1];
  const id = decodeURIComponent(m[2]);
  openConcept(examCode, id).catch(()=>{});
});

// 진행 중인 animated pop 수 — animationend 까지 stack.children.length 가 즉시 줄지 않아
// 이 사이에 들어오는 다음 popstate 가 excess 를 잘못 계산하는 race 가 발생한다.
// 카운터로 logical depth 를 보정해 차단.
let _popsInFlight = 0;

window.addEventListener('popstate', () => {
  // Browser back/forward — pop visible screens to match URL depth.
  const targetDepth = history.state?.depth || 0;
  const stack = document.getElementById('stack');
  _navInternal = true;
  const haveDepth = (stack.children.length - 1) - _popsInFlight;
  let excess = haveDepth - targetDepth;
  if (excess > 0) {
    while (excess > 1 && stack.children.length > 1 + _popsInFlight) {
      doPopScreen(true);   // immediate: synchronous remove
      excess--;
    }
    if (excess === 1 && stack.children.length > 1 + _popsInFlight) {
      _popsInFlight++;
      doPopScreen();        // animated final pop
      setTimeout(() => { _popsInFlight = Math.max(0, _popsInFlight - 1); }, 410);
    }
  } else if (excess < 0) {
    // History 가 stack 보다 깊다 — showTab 등으로 stack 이 한 번에 갈렸을 때 발생.
    // 현재 URL 은 유지한 채 depth 만 stack 에 맞게 re-anchor 해서 wedge 방지.
    const cur = history.state || {};
    history.replaceState({ ...cur, depth: haveDepth }, '', location.pathname + location.search);
  }
  _navInternal = false;
});

async function initRoute() {
  const segs = location.pathname.split('/').filter(Boolean);
  history.replaceState({ type: 'home', depth: 0 }, '', '/');
  if (segs.length === 0) return;

  // Cold-load deep link: 중간 단계 (예: home → sessionList → quiz) 는 stack 만 쌓고
  // history entry 는 마지막 도달 단계 한 번만 push. 뒤로가기 횟수가 표준 SPA 와 일치한다.
  _navInternal = true;
  let final = null;
  try {
    if (segs[0] === 'exam' && segs[1]) {
      await loadExams().catch(()=>{});
      if (!state.examByCode.has(segs[1])) return;
      await openSessionList(segs[1]);
      final = { type:'session', exam: segs[1] };
      if (segs[2]) {
        try {
          await loadSessions(segs[1]);
          if (state.sessionMap.get(segs[1])?.has(segs[2])) {
            // segs[3] = optional 1-based question number for deep-link prerender
            const qn = segs[3] ? parseInt(segs[3], 10) : NaN;
            const startIdx = Number.isFinite(qn) && qn > 0 ? qn - 1 : undefined;
            await openQuiz(segs[1], segs[2], startIdx);
            final = { type:'quiz', exam: segs[1], session: segs[2] };
          }
        } catch {}
      }
    } else if (segs[0] === 'concept' && segs[1] && segs[2]) {
      await loadExams().catch(()=>{});
      if (!state.examByCode.has(segs[1])) return;
      const id = decodeURIComponent(segs[2]);
      await openConcept(segs[1], id);
      final = { type:'concept', exam: segs[1], id };
      if (segs[3] === 'practice') {
        await openConceptPractice(segs[1], id);
        final = { type:'concept-practice', exam: segs[1], id };
      }
    } else if (segs[0] === 'concepts' && segs[1]) {
      await loadExams().catch(()=>{});
      if (!state.examByCode.has(segs[1])) return;
      showTab('concepts');
      await openConceptList(segs[1]);
      final = { type:'concept-list', exam: segs[1] };
    }
  } finally {
    _navInternal = false;
  }
  if (final) pushRoute(final);
}

/* ---- boot (at end so all const bindings are live) ---- */
loadAdSense();
await bootUI();
bindTabs();
showTab('home');
await initRoute();

// Prerender takeover: static HTML files served at /exam/... and /concept/... include
// a <main id="prerender"> block carrying the SEO-visible content. By the time we
// reach this line the SPA has rendered the equivalent screens into #stack, so we
// drop the prerender DOM to free memory and keep the live DOM canonical.
document.getElementById('prerender')?.remove();

// expose select helpers for debugging / external automation
window.__examkr = {
  openImportSheet, applyDump, buildDump, computeStats, backupCurrent,
  // Force-show the PWA install banner regardless of gates (visits, dismissed,
  // beforeinstallprompt availability). Useful for QA/screenshots/demos.
  // Native install action becomes a no-op alert; iOS instruction sheet works.
  previewPwaBanner: () => {
    store.del('pwaPromptDismissed');
    store.set('quizVisits', 99);
    if (!_deferredInstallPrompt) {
      _deferredInstallPrompt = {
        prompt: () => alert('[preview] 실제 native install 다이얼로그가 여기 열립니다.'),
        userChoice: Promise.resolve({ outcome: 'dismissed' }),
      };
    }
    try { maybeShowPwaBanner(); } catch (e) { console.error(e); }
  },
};

// ── Presence (지금 N명 학습 중) ──────────────────────────────────────────
// /api/presence 가 KV 미연결이면 ok:false 를 반환 — 그 경우 chip 을 숨김.
// 60초 heartbeat. 탭이 hidden 인 동안은 일시정지.
(() => {
  const chip = document.getElementById('presence-chip');
  const pop = document.getElementById('presence-pop');
  if (!chip || !pop) return;
  const elActive = document.getElementById('presence-active-n');
  const elActiveBig = document.getElementById('presence-active-big');
  const elToday = document.getElementById('presence-today-n');

  // 무료 티어 부담 줄이기 위해 5분 간격. 정확도는 비핵심 (체감용).
  const HEARTBEAT_MS = 300_000;
  // 첫 표시까지 30초 후 한 번 더 refresh — KV cold start 가 비어있는 케이스 보정
  const REFRESH_AFTER_MS = 30_000;
  let timer = null;
  let lastActive = null;
  let popTimer = null;
  let aborted = false;

  function fmt(n) {
    return new Intl.NumberFormat('ko-KR').format(n);
  }
  function bump(el) {
    if (!el) return;
    el.classList.remove('is-bumped');
    // reflow → restart animation
    void el.offsetWidth;
    el.classList.add('is-bumped');
  }
  function apply(data) {
    if (!data || data.ok === false) {
      chip.hidden = true;
      pop.hidden = true;
      return;
    }
    // 최소 표시 임계: 활성 1명 이상 (자기 자신 포함). 한산할 때 0명 표시 방지.
    if (data.active < 1) {
      chip.hidden = true;
      return;
    }
    const changed = lastActive !== null && lastActive !== data.active;
    elActive.textContent = fmt(data.active);
    elActiveBig.textContent = fmt(data.active);
    elToday.textContent = fmt(data.today);
    if (changed) { bump(elActive); bump(elActiveBig); }
    lastActive = data.active;
    chip.hidden = false;
  }

  async function ping(initial = false) {
    if (aborted || document.hidden) return;
    try {
      const r = await fetch('/api/presence', {
        method: initial ? 'GET' : 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!r.ok) throw new Error('http ' + r.status);
      const data = await r.json();
      apply(data);
    } catch (e) {
      // Silent fail — chip stays hidden if first call failed.
      if (lastActive === null) chip.hidden = true;
    }
  }

  function start() {
    if (timer) return;
    // 첫 호출도 POST — 본인을 즉시 등록해 chip 노출 지연 제거.
    ping(false);
    timer = setInterval(() => ping(false), HEARTBEAT_MS);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  // 클릭 시 상세 카드 토글 (자동 3초 후 닫힘)
  chip.addEventListener('click', (e) => {
    e.stopPropagation();
    if (popTimer) { clearTimeout(popTimer); popTimer = null; }
    if (pop.hidden) {
      pop.hidden = false;
      popTimer = setTimeout(() => { pop.hidden = true; }, 3500);
    } else {
      pop.hidden = true;
    }
  });
  document.addEventListener('click', (e) => {
    if (!pop.hidden && !pop.contains(e.target) && e.target !== chip) {
      pop.hidden = true;
      if (popTimer) { clearTimeout(popTimer); popTimer = null; }
    }
  });

  // 탭 가시성에 따라 heartbeat on/off
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop(); else start();
  });
  window.addEventListener('pagehide', () => { aborted = true; stop(); });

  start();
})();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', async () => {
    try {
      const reg = await navigator.serviceWorker.register('/sw.js');
      const promptUpdate = (sw) => {
        toastAction('새 버전이 있어요', '새로고침', () => {
          sw.postMessage('SKIP_WAITING');
        }, { persistent: true });
      };
      if (reg.waiting) promptUpdate(reg.waiting);
      reg.addEventListener('updatefound', () => {
        const sw = reg.installing;
        if (!sw) return;
        sw.addEventListener('statechange', () => {
          if (sw.state === 'installed' && navigator.serviceWorker.controller) {
            promptUpdate(sw);
          }
        });
      });
      let reloaded = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (reloaded) return; reloaded = true;
        location.reload();
      });
    } catch {}
  });
}

// /api/comments — 홈 방명록 (익명 댓글)
//
// GET    /api/comments             → 200 { ok, items: [{id, nick, msg, ts}] } 최근 30개
// POST   /api/comments             → 201 { ok, item } — body { nick?, message }
// DELETE /api/comments?id=..&key=..→ 200 { ok } — 운영 삭제 (env COMMENTS_ADMIN_KEY)
//
// 저장: Vercel KV (Upstash Redis REST) — presence.js 와 같은 인스턴스.
//   KV_REST_API_URL / KV_REST_API_TOKEN — Vercel KV 연결 시 자동 주입
//   COMMENTS_ADMIN_KEY (optional)      — 삭제용 관리 키. 없으면 DELETE 503.
// env 가 없으면 GET 이 ok:false 반환 — UI 는 방명록 섹션을 숨긴다 (presence 패턴).

const KV_URL = process.env.KV_REST_API_URL;
const KV_TOKEN = process.env.KV_REST_API_TOKEN;

const KEY = "gb:items";
const MAX_KEEP = 500;   // LTRIM 보존 상한
const PAGE = 30;        // GET 반환 개수
const NICK_MAX = 20;
const MSG_MIN = 2;
const MSG_MAX = 500;

// 단일 IP 스팸 방지 — feedback.js 와 같은 warm-instance 레이트리밋
const RATE_WINDOW_MS = 60_000;
const RATE_LIMIT = 3;
const _rate = new Map();

// GET 결과 warm-instance 캐시 (POST 시 무효화)
const CACHE_MS = 30_000;
let _cache = null;
let _cacheAt = 0;

const ALLOWED_HOSTS = new Set([
  "passcbt.kr", "www.passcbt.kr",
  "exam-kr.vercel.app", "exam.kr",
  "localhost", "127.0.0.1",
]);

const safeLine = (s, max) =>
  String(s == null ? "" : s).replace(/[\r\n\t]+/g, " ").trim().slice(0, max);

function checkOrigin(req) {
  const raw = req.headers.origin || req.headers.referer || "";
  if (!raw) return false;
  try {
    return ALLOWED_HOSTS.has(new URL(raw).hostname);
  } catch { return false; }
}

function checkRate(req) {
  const ip = (req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown";
  const now = Date.now();
  const arr = (_rate.get(ip) || []).filter((t) => now - t < RATE_WINDOW_MS);
  if (arr.length >= RATE_LIMIT) return false;
  arr.push(now);
  _rate.set(ip, arr);
  return true;
}

async function kvPipe(commands) {
  if (!KV_URL || !KV_TOKEN) return null;
  try {
    const r = await fetch(`${KV_URL}/pipeline`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${KV_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(commands),
    });
    if (!r.ok) {
      console.warn("[comments] kv pipeline fail", r.status);
      return null;
    }
    return (await r.json()).map((o) => o.result);
  } catch (e) {
    console.warn("[comments] kv error", e.message);
    return null;
  }
}

function parseItems(raw) {
  return (raw || []).map((s) => {
    try { return JSON.parse(s); } catch { return null; }
  }).filter(Boolean);
}

async function handleGet(res) {
  if (!KV_URL) return res.status(200).json({ ok: false, items: [] });
  const now = Date.now();
  if (_cache && now - _cacheAt < CACHE_MS) return res.status(200).json(_cache);
  const results = await kvPipe([["lrange", KEY, 0, PAGE - 1]]);
  if (!results) return res.status(200).json(_cache || { ok: false, items: [] });
  _cache = { ok: true, items: parseItems(results[0]) };
  _cacheAt = now;
  return res.status(200).json(_cache);
}

async function handlePost(req, res) {
  if (!checkOrigin(req)) return res.status(403).json({ error: "forbidden origin" });
  if (!checkRate(req)) return res.status(429).json({ error: "잠시 후 다시 시도해주세요." });
  if (!KV_URL) return res.status(503).json({ error: "방명록이 아직 설정되지 않았어요." });

  let payload = req.body;
  if (typeof payload === "string") {
    try { payload = JSON.parse(payload); }
    catch { return res.status(400).json({ error: "invalid json" }); }
  }
  payload = payload || {};

  const nick = safeLine(payload.nick, NICK_MAX);
  const msg = safeLine(payload.message, MSG_MAX);
  if (msg.length < MSG_MIN) {
    return res.status(400).json({ error: `내용을 ${MSG_MIN}자 이상 입력해주세요.` });
  }

  const item = {
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
    nick,
    msg,
    ts: Date.now(),
  };
  const results = await kvPipe([
    ["lpush", KEY, JSON.stringify(item)],
    ["ltrim", KEY, 0, MAX_KEEP - 1],
  ]);
  if (!results) return res.status(502).json({ error: "저장 실패. 잠시 후 다시 시도해주세요." });
  _cache = null;   // 다음 GET 이 fresh 목록을 읽도록
  return res.status(201).json({ ok: true, item });
}

async function handleDelete(req, res) {
  const adminKey = process.env.COMMENTS_ADMIN_KEY;
  if (!adminKey) return res.status(503).json({ error: "admin key not configured" });
  const url = new URL(req.url, "http://x");
  if (url.searchParams.get("key") !== adminKey) {
    return res.status(403).json({ error: "forbidden" });
  }
  const id = url.searchParams.get("id") || "";
  if (!id) return res.status(400).json({ error: "id required" });
  const results = await kvPipe([["lrange", KEY, 0, MAX_KEEP - 1]]);
  if (!results) return res.status(502).json({ error: "kv unavailable" });
  const target = (results[0] || []).find((s) => {
    try { return JSON.parse(s).id === id; } catch { return false; }
  });
  if (!target) return res.status(404).json({ error: "not found" });
  await kvPipe([["lrem", KEY, 1, target]]);
  _cache = null;
  return res.status(200).json({ ok: true });
}

module.exports = async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "GET") return handleGet(res);
  if (req.method === "POST") return handlePost(req, res);
  if (req.method === "DELETE") return handleDelete(req, res);
  return res.status(405).json({ error: "method not allowed" });
};

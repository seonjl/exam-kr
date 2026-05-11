// POST /api/presence — 클라이언트가 60초마다 호출하는 heartbeat. 응답에 현재 카운트.
// GET  /api/presence — read-only. 헤더만 보고 카운트 반환 (heartbeat 없음).
//
// 데이터 저장: Vercel KV (Upstash Redis REST API).
// 필요한 env vars:
//   KV_REST_API_URL          — Vercel KV 연결 시 자동 주입
//   KV_REST_API_TOKEN        — Vercel KV 연결 시 자동 주입
//   PRESENCE_SALT (optional) — IP/UA 해시 솔트
//
// env 가 없으면 ok:false 반환 — UI 는 chip 을 숨김. 배포 무관하게 작동.

const crypto = require("crypto");

const KV_URL = process.env.KV_REST_API_URL;
const KV_TOKEN = process.env.KV_REST_API_TOKEN;
const SALT = process.env.PRESENCE_SALT || "passcbt-default-salt";

const ACTIVE_KEY = "p:active";
const ACTIVE_TTL_MS = 480_000;  // 8분 (heartbeat 5분 + 3분 여유) — 무료 티어 커버 위해 완화
const DAILY_TTL_SEC = 172_800;  // 2 days
const COUNT_CACHE_MS = 30_000;  // 카운트 조회 결과를 warm instance 메모리에 30초 캐시

// warm-instance 메모리 — Fluid Compute 인스턴스 재사용 시 캐시 유효
let _cached = null;     // { active, today, ok }
let _cachedAt = 0;

const ALLOWED_HOSTS = new Set([
  "passcbt.kr", "www.passcbt.kr",
  "exam-kr.vercel.app", "exam.kr",
  "localhost", "127.0.0.1",
]);

function todayKey() {
  // KST 기준 날짜
  const d = new Date(Date.now() + 9 * 3600_000);
  return `p:day:${d.toISOString().slice(0, 10)}`;
}

function clientHash(req) {
  const ip = (req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown";
  const ua = req.headers["user-agent"] || "";
  return crypto.createHash("sha256")
    .update(`${ip}|${ua}|${SALT}`)
    .digest("hex").slice(0, 16);
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
      console.warn("[presence] kv pipeline fail", r.status);
      return null;
    }
    const arr = await r.json();
    return arr.map(o => o.result);
  } catch (e) {
    console.warn("[presence] kv error", e.message);
    return null;
  }
}

// 캐시된 카운트 반환. 30초 이내라면 KV 호출 없이 즉시 응답.
async function getCountsCached() {
  if (!KV_URL) return { active: 0, today: 0, ok: false };
  const now = Date.now();
  if (_cached && now - _cachedAt < COUNT_CACHE_MS) return _cached;
  const tk = todayKey();
  const results = await kvPipe([
    ["zremrangebyscore", ACTIVE_KEY, 0, now - ACTIVE_TTL_MS],
    ["zcard", ACTIVE_KEY],
    ["pfcount", tk],
  ]);
  if (!results) return _cached || { active: 0, today: 0, ok: false };
  const [, active, today] = results;
  _cached = { active: Number(active) || 0, today: Number(today) || 0, ok: true };
  _cachedAt = now;
  return _cached;
}

// heartbeat — 자기 자신 등록 + 즉시 fresh 카운트 반환. 한 pipeline 6 commands.
async function heartbeat(hash) {
  if (!KV_URL) return { active: 0, today: 0, ok: false };
  const now = Date.now();
  const tk = todayKey();
  const results = await kvPipe([
    ["zadd", ACTIVE_KEY, now, hash],
    ["pfadd", tk, hash],
    ["expire", tk, DAILY_TTL_SEC],
    ["zremrangebyscore", ACTIVE_KEY, 0, now - ACTIVE_TTL_MS],
    ["zcard", ACTIVE_KEY],
    ["pfcount", tk],
  ]);
  if (!results) return _cached || { active: 0, today: 0, ok: false };
  const active = Number(results[4]) || 0;
  const today = Number(results[5]) || 0;
  const fresh = { active, today, ok: true };
  _cached = fresh;
  _cachedAt = now;
  return fresh;
}

function checkOrigin(req) {
  const raw = req.headers.origin || req.headers.referer || "";
  if (!raw) return true; // SSR/direct call OK
  try {
    const u = new URL(raw);
    return ALLOWED_HOSTS.has(u.hostname);
  } catch {
    return false;
  }
}

module.exports = async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  // CORS — same-origin only (browsers don't enforce for same-origin, this is for clarity)
  const origin = req.headers.origin;
  if (origin && ALLOWED_HOSTS.has(new URL(origin).hostname)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
  }
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");

  if (req.method === "OPTIONS") return res.status(204).end();

  if (req.method === "GET") {
    return res.status(200).json(await getCountsCached());
  }

  if (req.method !== "POST") return res.status(405).end();

  if (!checkOrigin(req)) {
    return res.status(403).json({ error: "forbidden origin" });
  }

  const hash = clientHash(req);
  return res.status(200).json(await heartbeat(hash));
};

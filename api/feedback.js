// POST /api/feedback
// Body: { exam_code?, session_code?, qnum?, page_url?, message, user_agent? }
//
// Forwards user feedback to a GitHub Issue. Token + repo are read from
// Vercel project env vars (never reaches the client):
//   FEEDBACK_GITHUB_REPO   "owner/repo"
//   FEEDBACK_GITHUB_TOKEN  fine-grained PAT with Issues: read+write on that repo
//
// Returns:
//   201 { ok: true, url } — issue created
//   400 { error }         — validation failed
//   502 { error }         — GitHub API failed
//   503 { error }         — env not configured

const TRUNC = 4000;
const MIN = 5;

const safeLine = (s) =>
  String(s == null ? "" : s)
    .replace(/[\r\n]+/g, " ")
    .slice(0, 200);

// Allowed origins for cross-site abuse prevention. Anyone POSTing from
// outside these hosts is rejected — stops naive scripted spam where the
// attacker doesn't bother spoofing Origin/Referer.
const ALLOWED_HOSTS = new Set(["exam-kr.vercel.app", "exam.kr"]);

// Per-IP rate limit using shared warm-instance memory (Fluid Compute).
// Distributed attacks across many IPs can bypass; this stops single-IP spam.
const RATE_WINDOW_MS = 60_000;
const RATE_LIMIT = 5;
const _rate = new Map();

function checkOrigin(req) {
  const raw = req.headers.origin || req.headers.referer || "";
  if (!raw) return false;
  try {
    const host = new URL(raw).host;
    return ALLOWED_HOSTS.has(host);
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

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }
  if (!checkOrigin(req)) {
    res.status(403).json({ error: "forbidden origin" });
    return;
  }
  if (!checkRate(req)) {
    res.status(429).json({ error: "잠시 후 다시 시도해주세요." });
    return;
  }

  // Vercel parses JSON automatically when Content-Type is application/json,
  // but accept a raw string just in case.
  let payload = req.body;
  if (typeof payload === "string") {
    try { payload = JSON.parse(payload); }
    catch { res.status(400).json({ error: "invalid json" }); return; }
  }
  payload = payload || {};

  const text =
    typeof payload.message === "string" ? payload.message.trim().slice(0, TRUNC) : "";
  if (text.length < MIN) {
    res.status(400).json({ error: "내용을 5자 이상 입력해주세요." });
    return;
  }

  const repo = process.env.FEEDBACK_GITHUB_REPO;
  const token = process.env.FEEDBACK_GITHUB_TOKEN;
  if (!repo || !token) {
    console.error("[feedback] env vars FEEDBACK_GITHUB_REPO/TOKEN missing");
    res.status(503).json({ error: "피드백 채널이 아직 설정되지 않았어요." });
    return;
  }

  const examCode = safeLine(payload.exam_code);
  const sessionCode = safeLine(payload.session_code);
  const qnum = safeLine(payload.qnum);
  const ctx =
    examCode && sessionCode && qnum
      ? `[${examCode}/${sessionCode} #${qnum}]`
      : "[exam.kr]";
  const summary = text.split("\n")[0].slice(0, 60);
  const title = `${ctx} ${summary}`.slice(0, 200);

  const body = [
    `**페이지**: ${safeLine(payload.page_url) || "-"}`,
    `**자격증/회차/문항**: ${examCode || "-"} / ${sessionCode || "-"} / ${qnum || "-"}`,
    `**브라우저**: ${safeLine(payload.user_agent) || "-"}`,
    `**시간**: ${new Date().toISOString()}`,
    "",
    "---",
    "",
    text,
  ].join("\n");

  let ghResp;
  try {
    ghResp = await fetch(`https://api.github.com/repos/${repo}/issues`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "exam-kr-feedback",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        title,
        body,
        labels: ["user-feedback"],
      }),
    });
  } catch (e) {
    console.error("[feedback] fetch failed", e);
    res.status(502).json({ error: "GitHub 연결 실패. 잠시 후 다시 시도해주세요." });
    return;
  }

  if (!ghResp.ok) {
    const errText = await ghResp.text().catch(() => "");
    console.error("[feedback] GitHub API failed", ghResp.status, errText);
    res.status(502).json({ error: "제출이 실패했어요. 잠시 후 다시 시도해주세요." });
    return;
  }

  const issue = await ghResp.json().catch(() => ({}));
  res.status(201).json({ ok: true, url: issue.html_url });
};

// Shared by the paywall functions. Files starting with "_" are not routes on Vercel.
// Ported from msp-house-index / unit-turns-mpls (product-paywall skill), with one change:
// there is no webhook (the B&M Stripe account is at its 16-endpoint cap, 2026-10-17), so
// the buyer's password is shown on the return page once Stripe says the session paid, and
// it rides in the Stripe invoice footer. Every session carries product + handler metadata
// so the shared stripe-router can route a password email to it later.
//
// The password is stateless: XXXX-XXXX-XXXX = a 5-char nonce minted at checkout + a 7-char
// HMAC of it under ACCESS_SECRET. A password we never issued fails without a network call;
// one we issued unlocks once Stripe has a paid session for its nonce.
const crypto = require("crypto");
const TOOL = require("../public/offer.json");

const SITE = process.env.SITE_URL || TOOL.site;
const PRODUCT = TOOL.product;
const ALPHA = "23456789BCDFGHJKMNPQRSTVWXYZ";

async function stripe(path, { method = "GET", form } = {}) {
  const k = process.env.STRIPE_SECRET_KEY;
  if (!k) throw new Error("STRIPE_SECRET_KEY is not set");
  const r = await fetch(`https://api.stripe.com/v1/${path}`, {
    method,
    headers: { Authorization: `Bearer ${k}`, ...(form ? { "Content-Type": "application/x-www-form-urlencoded" } : {}) },
    body: form ? new URLSearchParams(form).toString() : undefined,
  });
  const j = await r.json();
  if (!r.ok) throw new Error(`stripe ${path}: ${j.error?.message || r.status}`);
  return j;
}

const chars = (buf, n) => Array.from(buf.subarray(0, n), (b) => ALPHA[b % ALPHA.length]).join("");
function mac(nonce, domain = "") {
  const s = process.env.ACCESS_SECRET;
  if (!s) throw new Error("ACCESS_SECRET is not set");
  return chars(crypto.createHmac("sha256", s).update(domain + PRODUCT + ":" + nonce).digest(), 7);
}
function newPassword() {
  const nonce = chars(crypto.randomBytes(5), 5);
  const raw = nonce + mac(nonce);
  return { nonce, password: `${raw.slice(0, 4)}-${raw.slice(4, 8)}-${raw.slice(8)}` };
}
const same = (a, b) => a.length === b.length && crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
function checkPassword(pw) {
  const raw = String(pw || "").toUpperCase().replace(/[^0-9A-Z]/g, "");
  if (raw.length !== 12) return null;
  const nonce = raw.slice(0, 5), tail = raw.slice(5);
  if (same(tail, mac(nonce))) return { nonce, kind: "paid" };
  if (same(tail, mac(nonce, "comp:"))) return { nonce, kind: "comp" };
  return null;
}

const paid = new Map();
const LAUNCH = 1792281600; // 2026-10-18
const unlocked = (s) => s.metadata?.product === PRODUCT && s.payment_status === "paid";

async function nonceIsPaid(nonce) {
  if (paid.get(nonce)) return true;
  try {
    const q = encodeURIComponent(`metadata['pw_nonce']:'${nonce}' AND metadata['product']:'${PRODUCT}' AND status:'succeeded'`);
    const s = await stripe(`payment_intents/search?query=${q}&limit=1`);
    if (s.data?.length) return paid.set(nonce, true), true;
  } catch (e) { console.error("[pw] search failed:", e.message); }
  let after = "";
  for (let page = 0; page < 20; page++) {
    const l = await stripe(`checkout/sessions?status=complete&limit=100&created[gte]=${LAUNCH}${after}`);
    if (l.data.find((s) => s.metadata?.pw_nonce === nonce && unlocked(s))) return paid.set(nonce, true), true;
    if (!l.has_more) break;
    after = `&starting_after=${l.data[l.data.length - 1].id}`;
  }
  return false;
}

// Is this request unlocked? -> { ok, kind } ; never throws.
async function access(req) {
  const pw = req.headers["x-password"] || (req.body && req.body.pw) || "";
  if (!pw) return { ok: false };
  const c = checkPassword(pw);
  if (!c) return { ok: false, bad: true };
  if (c.kind === "comp") return { ok: true, kind: "comp" };
  try { return (await nonceIsPaid(c.nonce)) ? { ok: true, kind: "paid" } : { ok: false, unpaid: true }; }
  catch (e) { console.error("[access]", e.message); return { ok: false, error: true }; }
}

async function mailgun(fields) {
  const { MAILGUN_API_KEY, MAILGUN_DOMAIN } = process.env;
  if (!MAILGUN_API_KEY || !MAILGUN_DOMAIN) throw new Error("Mailgun is not configured");
  const r = await fetch(`https://api.mailgun.net/v3/${MAILGUN_DOMAIN}/messages`, {
    method: "POST",
    headers: { Authorization: "Basic " + Buffer.from("api:" + MAILGUN_API_KEY).toString("base64") },
    body: new URLSearchParams(fields),
  });
  const out = await r.text();
  if (!r.ok) throw new Error(`mailgun ${r.status}: ${out.slice(0, 200)}`);
  return JSON.parse(out).id || "";
}

// The password email, sent once per session by the webhook (via the shared stripe-router).
// The session's metadata.pw_emailed marker is written before the send so a retry backs off.
async function sendPasswordOnce(session, { who }) {
  if (!unlocked(session)) return { sent: false, why: "not ours or not paid" };
  const fresh = await stripe(`checkout/sessions/${session.id}`);
  if (fresh.metadata?.pw_emailed) return { sent: false, why: "already emailed " + fresh.metadata.pw_emailed };
  const mark = (v) => stripe(`checkout/sessions/${session.id}`, { method: "POST", form: { "metadata[pw_emailed]": v } });
  await mark(`${new Date().toISOString()} by ${who}`);
  const to = fresh.customer_details?.email, pw = fresh.metadata.password;
  const link = `${SITE}/?pw=${encodeURIComponent(pw)}`;
  const from = process.env.MAILGUN_FROM || "aidan@brickandmortar.dev";
  const text = [`Thanks for buying ${TOOL.name}.`, ``, `Your password: ${pw}`, ``, `Open it unlocked: ${link}`, ``,
    `That link unlocks it on whatever device you open it on. Elsewhere, go to ${SITE} and enter the password under "Have a password?".`, ``,
    `Your receipt comes separately from Stripe. Reply to this email with any question.`, ``, `Aidan`, `Brick & Mortar`].join("\n");
  try {
    await mailgun({ from: `Aidan at Brick & Mortar <${from}>`, to, subject: `Your password for ${TOOL.name}`, text, "h:Reply-To": from });
  } catch (e) { await mark("").catch(() => {}); throw e; }
  await mailgun({ from: `${TOOL.name} <${from}>`, to: process.env.NOTIFY_EMAIL || "aidan@brickandmortar.dev",
    subject: `Sale: ${TOOL.name}, $${(fresh.amount_total || 0) / 100} from ${to}`,
    text: `${to} bought ${TOOL.name}. Session ${fresh.id}. Password ${pw} emailed by the ${who}.` }).catch((e) => console.error("[pw] notice:", e.message));
  return { sent: true };
}

module.exports = { sendPasswordOnce, SITE, PRODUCT, TOOL, stripe, newPassword, checkPassword, nonceIsPaid, unlocked, access, mac };

// GET /api/data?n=<slug> -> the full corrective action plan for one nonprofit: every finding's
// draft (root cause, steps, owner, monitoring, the 200.511(c) paragraph) and the agency page.
// Password in x-password (or ?pw=), minted at checkout (./checkout.js) or issued by hand
// (scripts/issue_password.py). GET /api/data with no n -> {ok:true}: the page checks a
// password before it keeps it.
const fs = require("fs");
const path = require("path");
const { checkPassword, nonceIsPaid } = require("./_lib");
const { view } = require("./_view");
let PASSES = null;

module.exports = async (req, res) => {
  const pw = req.headers["x-password"] || req.query.pw;
  const ok = checkPassword(pw);
  if (!ok) return res.status(401).json({ error: "That password didn't match. Check the email from Brick & Mortar, or reply to it for help." });
  try {
    if (ok.kind === "paid" && !(await nonceIsPaid(ok.nonce))) return res.status(402).json({ error: "That password's payment hasn't gone through. If you just paid, wait a minute and try again." });
  } catch (e) {
    console.error("[data] paid check:", e.message);
    return res.status(502).json({ error: "Couldn't check the password right now. Try again in a minute." });
  }
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("X-Access", ok.kind);
  if (!req.query.n) {
    if (ok.kind === "comp") { try { PASSES ??= JSON.parse(fs.readFileSync(path.join(__dirname, "_full", "passes.json"), "utf8")); } catch { PASSES = {}; } }
    console.log(`[unlock] ${ok.kind} ${ok.kind === "comp" ? PASSES[ok.nonce] || ok.nonce : ok.nonce}`);
    return res.status(200).json({ ok: true });
  }
  try {
    const v = view(req.query.n, true);
    if (!v) return res.status(404).json({ error: "No nonprofit by that name has a finding on file." });
    res.status(200).json(v);
  } catch (e) {
    console.error("[data]", e.message);
    res.status(500).json({ error: "Couldn't load that audit. Try again in a minute." });
  }
};

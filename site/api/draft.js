// POST /api/draft {n, ref} -> one finding's drafted CAP, made on demand for an audit that was
// not pre-drafted at build time. Paid or comp password only (the free paragraph is always a
// pre-drafted one). Same prompt and schema as scripts/draft.py (site/api/_prompt.json). The
// model reasons over the finding text; every number on the page comes from the finding or is a
// bracketed blank (prompt rule 2).
const Anthropic = require("@anthropic-ai/sdk");
const { access } = require("./_lib");
const { raw } = require("./_view");
const PROMPT = require("./_prompt.json");
const { allowedNumbers, scrub } = require("./_guard");

const client = new Anthropic();
const made = new Map(); // report|ref -> draft, per warm instance
const hits = new Map(); // ip -> timestamps: a spend brake, not security
function limited(ip, cap) {
  const now = Date.now(), h = (hits.get(ip) || []).filter((t) => now - t < 3600e3);
  h.push(now); hits.set(ip, h);
  return h.length > cap;
}

const money = (x) => (typeof x === "number" ? "$" + Math.round(x).toLocaleString("en-US") : "");
// Mirrors scripts/prompt.py user_content(): keep the two in step.
function content(a, f) {
  const progs = f.programs.map((p) => `- ${p.name || "(program not named)"} (ALN ${p.aln}, ${p.agency}); ${p.direct ? "direct from the federal agency" : "passed through " + (p.passthrough.join(", ") || "an unnamed pass-through")}${typeof p.expended === "number" ? `; amount expended this year: ${money(p.expended)}` : ""}`).join("\n");
  const sev = [["material weakness", f.material_weakness], ["significant deficiency", f.significant_deficiency], ["questioned costs", f.questioned_costs], ["modified opinion", f.modified_opinion]].filter((x) => x[1]).map((x) => x[0]);
  const contact = `${a.contact.name}, ${a.contact.title}`.replace(/^, |, $/g, "") || "[name, title]";
  return [
    `ORGANIZATION: ${a.name}, ${a.city}, Minnesota. Audit year ${a.year} (fiscal year ending ${a.fy_end}).${typeof a.expended === "number" ? ` Total federal expended: ${money(a.expended)}.` : ""}`,
    `FILED CONTACT (the responsible person): ${contact}`,
    `AUDITOR: ${a.auditor.firm}`,
    `FINDING ${f.ref}. Compliance requirement: ${f.requirement_names.join(", ") || f.requirement}. Severity flags: ${sev.join(", ") || "none beyond the finding itself"}. Repeat finding: ${f.repeat ? "yes, prior " + f.prior_refs.join(", ") : "no"}.`,
    `PROGRAMS THE FINDING SITS ON:\n${progs || "- (none listed)"}`,
    `THE AUDITOR'S FINDING TEXT:\n${f.text || "(the auditor filed the text only in the PDF; draft from the requirement and flags above and say so in what_failed)"}`,
    `THE CAP THE ORGANIZATION ALREADY FILED FOR THIS FINDING:\n${f.prior_cap || "(none filed)"}`,
    "Draft the corrective action plan.",
  ].join("\n\n");
}

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  const b = typeof req.body === "object" && req.body ? req.body : {};
  const acc = await access(req);
  if (!acc.ok) return res.status(acc.bad ? 401 : 402).json({ error: acc.bad ? "That password didn't match." : "The full plan needs a paid password." });
  const r = raw(b.n, b.ref);
  if (!r) return res.status(404).json({ error: "No such finding." });
  if (r.draft) return res.status(200).json({ draft: strip(r.draft), cached: true });
  const key = `${r.audit.report_id}|${r.finding.ref}`;
  if (made.has(key)) return res.status(200).json({ draft: made.get(key), cached: true });
  const ip = String(req.headers["x-forwarded-for"] || "").split(",")[0] || "?";
  if (limited(ip, 40)) return res.status(429).json({ error: "That's a lot of drafts in an hour. Try again in a bit." });
  try {
    const m = await client.beta.messages.create({
      model: "claude-opus-5-5",
      max_tokens: 8000,
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: PROMPT.system,
      output_config: { effort: "medium", format: { type: "json_schema", schema: PROMPT.schema } },
      messages: [{ role: "user", content: content(r.audit, r.finding) }],
    });
    if (m.stop_reason === "refusal") return res.status(422).json({ error: "It couldn't draft that finding." });
    if (m.stop_reason === "max_tokens") return res.status(413).json({ error: "That finding was too long for one draft." });
    const removed = [];
    const d = scrub(JSON.parse(m.content.filter((x) => x.type === "text").map((x) => x.text).join("")), allowedNumbers(content(r.audit, r.finding), PROMPT.system), removed);
    if (removed.length) console.log(`[draft] guard replaced ${removed.length} figure(s) in ${key}`);
    made.set(key, d);
    console.log(`[draft] ${acc.kind} ${key} in=${m.usage.input_tokens} out=${m.usage.output_tokens}`);
    res.setHeader("Cache-Control", "no-store");
    res.status(200).json({ draft: d, cached: false });
  } catch (e) {
    console.error("[draft]", e.status || "", e.message);
    res.status(502).json({ error: "The draft hit a snag. Try again in a minute." });
  }
};
const strip = (d) => Object.fromEntries(Object.entries(d).filter(([k]) => !k.startsWith("_")));
module.exports.content = content;

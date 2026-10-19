// The lookup behind the free preview (/api/preview) and the paid document (/api/data).
// Loads private/data (uploaded as api/_full/ by scripts/deploy.py, never in public site/)
// once per warm instance and returns a view the page renders with no data of its own.
const fs = require("fs");
const path = require("path");

const DIR = process.env.FULL_DIR || path.join(__dirname, "_full");
let AUD = null, DRAFTS = null, BY_SLUG = null, BY_EIN = null;

function load() {
  if (AUD) return;
  AUD = JSON.parse(fs.readFileSync(path.join(DIR, "audits.json"), "utf8"));
  try { DRAFTS = JSON.parse(fs.readFileSync(path.join(DIR, "drafts.json"), "utf8")); } catch { DRAFTS = {}; }
  BY_SLUG = new Map(); BY_EIN = new Map();
  for (const a of AUD) {
    if (a.latest) BY_SLUG.set(a.slug, a);
    if (!BY_EIN.has(a.ein)) BY_EIN.set(a.ein, []);
    BY_EIN.get(a.ein).push(a);
  }
}

// Severity order the page lists findings in: a repeat material weakness first.
const rank = (f) => (f.repeat ? 8 : 0) + (f.material_weakness ? 4 : 0) + (f.questioned_costs ? 2 : 0) + (f.significant_deficiency ? 1 : 0);
const sorted = (fs_) => fs_.slice().sort((a, b) => rank(b) - rank(a) || a.ref.localeCompare(b.ref));

// 2 CFR 200.521(d): the pass-through issues its management decision within six months of the
// FAC accepting the audit. Computed, never typed.
function decisionClock(accepted) {
  if (!accepted) return null;
  const d = new Date(accepted + "T12:00:00Z"), day = d.getUTCDate();
  d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + 6);
  const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
  d.setUTCDate(Math.min(day, last)); // Aug 31 + 6 months is Feb 28, not Mar 3
  return d.toISOString().slice(0, 10);
}

function draftFor(a, f) { return (DRAFTS || {})[`${a.report_id}|${f.ref}`] || null; }

// full = paid. Free: every finding listed with its requirement, severity, repeat flag, programs,
// the auditor's own text and the filed CAP (all public record), plus the drafted CAP paragraph for
// the first finding. Paid: the whole draft for every finding and the agency page.
function view(slug, full) {
  load();
  const a = BY_SLUG.get(String(slug || ""));
  if (!a) return null;
  const fs_ = sorted(a.findings);
  const findings = fs_.map((f, i) => {
    const d = draftFor(a, f);
    const base = {
      ref: f.ref, requirement: f.requirement, requirement_names: f.requirement_names,
      material_weakness: f.material_weakness, significant_deficiency: f.significant_deficiency, questioned_costs: f.questioned_costs,
      modified_opinion: f.modified_opinion, other_matters: f.other_matters, repeat: f.repeat, prior_refs: f.prior_refs,
      programs: f.programs, text: f.text, text_is_stub: f.text_is_stub, prior_cap: f.prior_cap,
      drafted: !!d,
    };
    if (full) return { ...base, draft: d ? strip(d) : null };
    // Free: the first finding's paragraph, and only a title for the rest.
    if (!d) return { ...base, draft: null };
    return { ...base, draft: i === 0 ? { title: d.title, what_failed: d.what_failed, cap_paragraph: d.cap_paragraph } : { title: d.title } };
  });
  const history = (BY_EIN.get(a.ein) || []).filter((h) => h.report_id !== a.report_id).sort((x, y) => y.year - x.year)
    .map((h) => ({ year: h.year, report_id: h.report_id, findings: sorted(h.findings).map((f) => ({ ref: f.ref, requirement_names: f.requirement_names, repeat: f.repeat, material_weakness: f.material_weakness, significant_deficiency: f.significant_deficiency, title: (draftFor(h, f) || {}).title || "" })) }));
  const passthroughs = [...new Set(fs_.flatMap((f) => f.programs.flatMap((p) => p.passthrough)))];
  return {
    full: !!full,
    org: { name: a.name, city: a.city, ein: a.ein, slug: a.slug, year: a.year, fy_end: a.fy_end, accepted: a.accepted, expended: a.expended,
           low_risk: a.low_risk, flags: a.flags, flagged_years: a.flagged_years, auditor: a.auditor.firm,
           contact: { name: a.contact.name, title: a.contact.title } },
    findings,
    n_findings: fs_.length, n_drafted: fs_.filter((f) => draftFor(a, f)).length, n_repeat: fs_.filter((f) => f.repeat).length,
    passthroughs, decision_by: decisionClock(a.accepted),
    history,
  };
}

const strip = (d) => Object.fromEntries(Object.entries(d).filter(([k]) => !k.startsWith("_")));

// For the live route: the raw audit + finding, so a missing draft can be made on demand.
function raw(slug, ref) {
  load();
  const a = BY_SLUG.get(String(slug || ""));
  if (!a) return null;
  const f = a.findings.find((x) => x.ref === ref);
  return f ? { audit: a, finding: f, draft: draftFor(a, f) } : null;
}

module.exports = { view, raw, decisionClock, rank };

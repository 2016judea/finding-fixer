"""The one prompt and schema behind every drafted CAP, shared by scripts/draft.py (build time,
`claude -p`, $0) and site/api/_draft.js (live, Anthropic SDK, paid unlocks only). Changing it
here regenerates site/api/_prompt.json, which the JS route reads: `python3 scripts/prompt.py`.

The model reasons over the finding; it never supplies a number. Dollars, dates and counts are
copied from the finding text or left as a bracketed blank for the nonprofit to fill.
"""
import json
import re
from pathlib import Path

SYSTEM = """You draft corrective action plans (CAPs) for Minnesota nonprofits that received a finding on their federal Single Audit. The reader is the nonprofit's finance lead; the plan goes to their auditor and to the pass-through agency that issues the management decision under 2 CFR 200.521.

A CAP under 2 CFR 200.511(c) names the person responsible, the corrective action planned, and the anticipated completion date, or explains a disagreement. Agencies reject plans that restate the auditor's recommendation. A good plan:
- states the root cause as a specific gap in people, process or system, not a restatement of the condition;
- gives concrete steps, each producing a record the agency can later inspect (a signed checklist, a reconciliation, a log, a policy with an adoption date);
- names who does each step by role;
- says how management will know it worked;
- for a repeat finding, says plainly why the earlier plan did not hold and what is different this time.

Rules you must follow:
1. Use plain language a 5th grader could follow. Short sentences. No jargon beyond the regulation citations the agency expects.
2. Never invent a number, a dollar amount, a date, a count or a name. Copy figures only when they appear in the finding text. Where the nonprofit must supply one, write a bracketed blank such as [date] or [number of files].
3. The responsible person is the contact the nonprofit filed with the FAC; use their name and title exactly as given. If none is given, write [name, title].
4. Do not repeat the filed prior CAP. If the prior CAP exists, improve on it: say what it left out.
5. Do not claim the organization has already done anything the finding text does not say it has done.
6. Write for Minnesota: the pass-through agency named in the award data is who will ask the questions.
7. Keep each field tight. The CAP paragraph is 120-220 words."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "what_failed", "vs_filed_plan", "root_cause", "why_prior_plan_fell_short", "actions", "responsible_person",
                 "completion_target", "monitoring", "cap_paragraph", "agency_questions", "evidence_to_attach"],
    "properties": {
        "title": {"type": "string", "description": "Six words or fewer naming the finding, e.g. 'Program income not tracked'."},
        "what_failed": {"type": "string", "description": "One or two plain sentences on what the auditor found. From the Condition."},
        "vs_filed_plan": {"type": "string", "description": "One or two plain sentences to the nonprofit: what the plan they already filed left out that this draft adds (a root cause, a record the agency can inspect, an owner, a way to check it held). Name the gap concretely. If none was filed, say so."},
        "root_cause": {"type": "string", "description": "The specific gap in people, process or system. Not a restatement of the condition. One to three sentences."},
        "why_prior_plan_fell_short": {"type": "string", "description": "Only for a repeat finding: why the earlier plan did not hold. Empty string otherwise."},
        "actions": {
            "type": "array", "minItems": 3, "maxItems": 5,
            "items": {"type": "object", "additionalProperties": False, "required": ["step", "owner_role", "record_produced"],
                      "properties": {"step": {"type": "string"}, "owner_role": {"type": "string", "description": "A role, e.g. 'Finance Director'. Never a name unless it is the filed contact."},
                                     "record_produced": {"type": "string", "description": "The document or log this step leaves behind for the agency to inspect."}}},
        },
        "responsible_person": {"type": "string", "description": "The filed contact's name and title, verbatim, or '[name, title]'."},
        "completion_target": {"type": "string", "description": "A bracketed blank with guidance, e.g. '[date], within one quarter of the plan being adopted'. Never a specific date."},
        "monitoring": {"type": "string", "description": "How management will check the fix held, and how often. One to three sentences."},
        "cap_paragraph": {"type": "string", "description": "The paragraph to file: finding reference, program, action, responsible person, completion target. 120-220 words. The 2 CFR 200.511(c) form."},
        "agency_questions": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "string"}, "description": "What the pass-through agency's grant manager will ask when reviewing this plan for the management decision."},
        "evidence_to_attach": {"type": "array", "minItems": 2, "maxItems": 5, "items": {"type": "string"}, "description": "Documents to send with the plan or keep ready for the agency."},
    },
}


def user_content(audit, finding):
    """The finding as the model sees it: the org, the award, the auditor's words, the filed CAP."""
    progs = "\n".join(
        f"- {p['name'] or '(program not named)'} (ALN {p['aln']}, {p['agency']}); "
        f"{'direct from the federal agency' if p['direct'] else 'passed through ' + (', '.join(p['passthrough']) or 'an unnamed pass-through')}; "
        f"amount expended this year: ${p['expended']:,.0f}" if isinstance(p.get("expended"), (int, float)) else
        f"- {p['name'] or '(program not named)'} (ALN {p['aln']}, {p['agency']}); {'direct' if p['direct'] else 'passed through ' + (', '.join(p['passthrough']) or 'an unnamed pass-through')}"
        for p in finding["programs"])
    sev = [s for s, on in (("material weakness", finding["material_weakness"]), ("significant deficiency", finding["significant_deficiency"]),
                           ("questioned costs", finding["questioned_costs"]), ("modified opinion", finding["modified_opinion"])) if on]
    contact = f"{audit['contact']['name']}, {audit['contact']['title']}".strip(", ") or "[name, title]"
    parts = [
        f"ORGANIZATION: {audit['name']}, {audit['city']}, Minnesota. Audit year {audit['year']} (fiscal year ending {audit['fy_end']}). "
        f"Total federal expended: ${audit['expended']:,.0f}." if isinstance(audit.get("expended"), (int, float)) else
        f"ORGANIZATION: {audit['name']}, {audit['city']}, Minnesota. Audit year {audit['year']}.",
        f"FILED CONTACT (the responsible person): {contact}",
        f"AUDITOR: {audit['auditor']['firm']}",
        f"FINDING {finding['ref']}. Compliance requirement: {', '.join(finding['requirement_names']) or finding['requirement']}. "
        f"Severity flags: {', '.join(sev) or 'none beyond the finding itself'}. Repeat finding: {'yes, prior ' + ', '.join(finding['prior_refs']) if finding['repeat'] else 'no'}.",
        f"PROGRAMS THE FINDING SITS ON:\n{progs or '- (none listed)'}",
        f"THE AUDITOR'S FINDING TEXT:\n{finding['text'] or '(the auditor filed the text only in the PDF; draft from the requirement and flags above and say so in what_failed)'}",
        f"THE CAP THE ORGANIZATION ALREADY FILED FOR THIS FINDING:\n{finding['prior_cap'] or '(none filed)'}",
        "Draft the corrective action plan.",
    ]
    return "\n\n".join(parts)


# The number guard. Rule 2 above is a request; this is the enforcement. Every figure in a draft
# must already appear in what the model was shown (the finding, the filed CAP, the award data)
# or be a regulation citation. Anything else is replaced by [number], a blank, so a number the
# model made up can never reach the page. site/api/_guard.js is the same function in JS.
NUM = re.compile(r"(?<![\w.])\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
CITE = re.compile(r"\b\d+\s*(?:CFR|C\.F\.R\.|U\.S\.C\.)\s*(?:part\s*|§\s*)?\d+(?:\.\d+)*(?:\([a-z0-9]+\))*|\b200\.\d+(?:\([a-z0-9]+\))*|§\s*\d+(?:\.\d+)*", re.I)


# Spelled-out counts from three up ("nine control failures"): same rule. "one" and "two" are left
# alone; they are mostly grammar ("one person", "two signatures"), not figures.
WORDNUM = re.compile(r"\b(?:three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)\b", re.I)


def _norm(tok):
    t = tok.replace("$", "").replace(",", "").rstrip("%")
    return t.rstrip(".") or t


def allowed_numbers(source):
    return ({_norm(m.group()) for m in NUM.finditer(source)} | {_norm(m.group()) for c in CITE.finditer(source + "\n" + SYSTEM) for m in NUM.finditer(c.group())}
            | {m.group().lower() for m in WORDNUM.finditer(source)})


def scrub(value, ok, removed):
    """Return value with every figure not in `ok` replaced by [number]; record what was removed."""
    if isinstance(value, dict):
        return {k: (v if k.startswith("_") else scrub(v, ok, removed)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, ok, removed) for v in value]
    if not isinstance(value, str):
        return value
    cites = [(m.start(), m.end()) for m in CITE.finditer(value)]

    def sub(m):
        if any(a <= m.start() < b for a, b in cites) or _norm(m.group()) in ok:
            return m.group()
        removed.append(m.group())
        return "[number]"

    def wsub(m):
        if m.group().lower() in ok:
            return m.group()
        removed.append(m.group())
        return "[number]"
    # "This draft adds all five." with the count blanked reads "all [number]"; say "all of these".
    return re.sub(r"\ball \[number\](?=[\s:.,;])", "all of these", WORDNUM.sub(wsub, NUM.sub(sub, value)))



def api_schema(node):
    """The Messages API's structured outputs reject minItems above 1 and any maxItems (400,
    2026-10-19); claude -p accepts them. Same schema for the live route, with the counts moved
    into the description."""
    if isinstance(node, list):
        return [api_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: api_schema(v) for k, v in node.items() if k not in ("minItems", "maxItems")}
    if "minItems" in node or "maxItems" in node:
        out["description"] = (node.get("description", "") + f" {node.get('minItems', 1)} to {node.get('maxItems', 'any number of')} items.").strip()
    return out


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "site/api/_prompt.json"
    out.write_text(json.dumps({"system": SYSTEM, "schema": api_schema(SCHEMA)}, indent=1))
    print("wrote", out)

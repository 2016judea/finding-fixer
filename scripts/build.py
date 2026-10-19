#!/usr/bin/env python3
"""Join the FAC pull into what the site serves.

    python3 scripts/build.py

Writes
  private/data/audits.json   every Minnesota NONPROFIT Single Audit 2022–2025 that carries a finding:
                             org, audit, each finding with the auditor's text, the filed CAP, the
                             program and who passed it through. Gitignored; deployed as api/_full/.
  private/data/drafts.json   the drafted CAPs (scripts/draft.py), keyed report_id|finding_ref.
  site/data/index.json       the public search index: name, city, EIN, latest flagged year,
                             finding count, repeat flag. No texts, no contacts.
  site/data/meta.json        counts for the page and the offer. Every number on the page is read
                             from here, never typed.

Only `entity_type == "non-profit"` rows ship; schools, counties and tribes are a different buyer.
"""
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAC = ROOT / "data/fac"
PRIV = ROOT / "private/data"
PUB = ROOT / "site/data"
OFFER = json.loads((ROOT / "site/offer.json").read_text())

# 2 CFR 200 Appendix XI compliance requirement letters (the FAC's type_requirement).
REQ = {"A": "Activities allowed or unallowed", "B": "Allowable costs / cost principles", "C": "Cash management",
       "E": "Eligibility", "F": "Equipment and real property management", "G": "Matching, level of effort, earmarking",
       "H": "Period of performance", "I": "Procurement, suspension and debarment", "J": "Program income",
       "L": "Reporting", "M": "Subrecipient monitoring", "N": "Special tests and provisions", "P": "Other"}
AGENCY = {"10": "USDA", "11": "Commerce", "12": "Defense", "14": "HUD", "15": "Interior", "16": "Justice", "17": "Labor",
          "19": "State", "20": "Transportation", "21": "Treasury", "45": "NEA/NEH/IMLS", "59": "SBA", "64": "Veterans Affairs",
          "66": "EPA", "81": "Energy", "84": "Education", "93": "Health and Human Services", "94": "AmeriCorps", "97": "Homeland Security"}


def req_names(code):
    code = (code or "").strip().upper()
    return [REQ[c] for c in code if c in REQ] or ([code] if code else [])


def slug(name, city):
    s = (name + " " + (city or "")).lower().replace("&", " and ")
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", s))


def load(n):
    return json.loads((FAC / f"{n}.json").read_text())


def main():
    G, F, T, C, A, P = (load(n) for n in ("general", "findings", "findings_text", "caps", "federal_awards", "passthrough"))
    by_rep = collections.defaultdict(list)
    for f in F:
        by_rep[f["report_id"]].append(f)
    text = {(t["report_id"], t["finding_ref_number"]): t for t in T}
    cap = {(c["report_id"], c["finding_ref_number"]): c for c in C}
    award = collections.defaultdict(dict)
    for a in A:
        award[a["report_id"]][a["award_reference"]] = a
    # The same agency is typed many ways ("MINNESOTA DEPARTMENT OF EDUCATION", "Minnesota Department of Education"):
    # one display spelling per casefolded name, the one filed most often.
    spell = collections.defaultdict(collections.Counter)
    for p in P:
        if p["passthrough_name"]:
            spell[" ".join(p["passthrough_name"].split()).casefold()][" ".join(p["passthrough_name"].split())] += 1
    KEEP = {"MN", "DEED", "DHS", "MDE", "MDH", "USDA", "HUD", "DPS", "MHFA", "LLC", "ISD", "YMCA", "YWCA", "II", "III", "IV", "USA"}
    titled = lambda s: " ".join(w if w in KEEP else w.title() for w in s.split())
    canon = {k: (next((s for s in c if not s.isupper()), None) or titled(c.most_common(1)[0][0])) for k, c in spell.items()}
    pt = collections.defaultdict(list)
    for p in P:
        if p["passthrough_name"]:
            pt[(p["report_id"], p["award_reference"])].append(canon[" ".join(p["passthrough_name"].split()).casefold()])

    audits = []
    for g in G:
        if g["entity_type"] != "non-profit" or g["report_id"] not in by_rep:
            continue
        rid = g["report_id"]
        refs = sorted({f["reference_number"] for f in by_rep[rid]})
        findings = []
        for ref in refs:
            rows = [f for f in by_rep[rid] if f["reference_number"] == ref]
            progs = []
            for f in rows:
                a = award[rid].get(f["award_reference"]) or {}
                progs.append({"award_ref": f["award_reference"], "name": a.get("federal_program_name") or "",
                              "aln": f"{a.get('federal_agency_prefix', '')}.{a.get('federal_award_extension', '')}".strip("."),
                              "agency": AGENCY.get(str(a.get("federal_agency_prefix")), str(a.get("federal_agency_prefix") or "")),
                              "expended": a.get("amount_expended"), "direct": a.get("is_direct") == "Y", "major": a.get("is_major") == "Y",
                              "opinion": a.get("audit_report_type") or "", "passthrough": sorted(set(pt.get((rid, f["award_reference"]), [])))})
            f0 = rows[0]
            t, c = text.get((rid, ref)) or {}, cap.get((rid, ref)) or {}
            ftxt = (t.get("finding_text") or "").strip()
            findings.append({
                "ref": ref, "requirement": f0["type_requirement"], "requirement_names": req_names(f0["type_requirement"]),
                "material_weakness": f0["is_material_weakness"] == "Y", "significant_deficiency": f0["is_significant_deficiency"] == "Y",
                "other_matters": f0["is_other_matters"] == "Y", "questioned_costs": f0["is_questioned_costs"] == "Y",
                "modified_opinion": f0["is_modified_opinion"] == "Y", "repeat": f0["is_repeat_finding"] == "Y",
                "prior_refs": sorted({r for f in rows for r in (f.get("prior_finding_ref_numbers") or "").replace(";", ",").split(",") if r.strip()}),
                "programs": progs, "text": ftxt, "text_is_stub": len(ftxt) < 300 or bool(re.search(r"see (the )?(attached|accompanying|schedule)", ftxt, re.I)),
                "prior_cap": (c.get("planned_action") or "").strip(),
            })
        audits.append({
            "report_id": rid, "year": int(g["audit_year"]), "fy_end": g["fy_end_date"], "accepted": g["fac_accepted_date"],
            "ein": g["auditee_ein"], "uei": g["auditee_uei"], "name": g["auditee_name"].strip(), "city": (g["auditee_city"] or "").strip().title(),
            "slug": slug(g["auditee_name"], g["auditee_city"]),
            "expended": g["total_amount_expended"], "low_risk": g["is_low_risk_auditee"] == "Yes",
            "flags": {"going_concern": g["is_going_concern_included"] == "Yes", "ic_deficiency": g["is_internal_control_deficiency_disclosed"] == "Yes",
                      "material_weakness": g["is_internal_control_material_weakness_disclosed"] == "Yes", "material_noncompliance": g["is_material_noncompliance_disclosed"] == "Yes"},
            "contact": {"name": (g["auditee_contact_name"] or "").strip(), "title": (g["auditee_contact_title"] or "").strip(), "email": (g["auditee_email"] or "").strip().lower()},
            "certify": {"name": (g["auditee_certify_name"] or "").strip(), "title": (g["auditee_certify_title"] or "").strip()},
            "auditor": {"firm": (g["auditor_firm_name"] or "").strip(), "contact": (g["auditor_contact_name"] or "").strip(), "email": (g["auditor_email"] or "").strip().lower(), "city": (g["auditor_city"] or "").strip()},
            "findings": findings,
        })
    # Two groups with one name and town (a parent and its housing arm) must not share a slug: the second gets its EIN tail.
    eins_by_slug = collections.defaultdict(set)
    for a in audits:
        eins_by_slug[a["slug"]].add(a["ein"])
    for a in audits:
        if len(eins_by_slug[a["slug"]]) > 1:
            a["slug"] = f"{a['slug']}-{a['ein'][-4:]}"
    audits.sort(key=lambda a: (a["slug"], -a["year"]))

    # Latest flagged audit per EIN is the one the page opens on; earlier years hang off it as history.
    by_ein = collections.defaultdict(list)
    for a in audits:
        by_ein[a["ein"]].append(a)
    latest = {ein: max(rows, key=lambda a: a["year"]) for ein, rows in by_ein.items()}
    for ein, rows in by_ein.items():
        yrs = sorted({a["year"] for a in rows})
        for a in rows:
            a["flagged_years"] = yrs
            a["latest"] = a["report_id"] == latest[ein]["report_id"]

    PRIV.mkdir(parents=True, exist_ok=True)
    (PRIV / "audits.json").write_text(json.dumps(audits))

    index = [{"s": a["slug"], "n": a["name"], "c": a["city"], "e": a["ein"], "y": a["year"], "k": len(a["findings"]),
              "r": int(any(f["repeat"] for f in a["findings"])), "yrs": a["flagged_years"]} for a in audits if a["latest"]]
    index.sort(key=lambda r: r["n"].lower())
    PUB.mkdir(parents=True, exist_ok=True)
    (PUB / "index.json").write_text(json.dumps(index, separators=(",", ":")))

    # The worked example the page opens on: the newest audit with a repeat finding and two or more drafted plans.
    drafts = json.loads((PRIV / "drafts.json").read_text()) if (PRIV / "drafts.json").exists() else {}
    drafted = lambda a: sum(1 for f in a["findings"] if f"{a['report_id']}|{f['ref']}" in drafts)
    ex = sorted([a for a in audits if a["latest"] and any(f["repeat"] for f in a["findings"]) and len(a["findings"]) >= 2],
                key=lambda a: (-a["year"], -drafted(a), a["slug"]))
    example = next((a["slug"] for a in ex if drafted(a) >= 2), ex[0]["slug"] if ex else (audits[0]["slug"] if audits else ""))

    years = sorted({a["year"] for a in audits})
    np_all = collections.Counter(int(g["audit_year"]) for g in G if g["entity_type"] == "non-profit")
    lat = [a for a in audits if a["latest"]]
    finds = [f for a in lat for f in a["findings"]]
    meta = {
        "built": __import__("datetime").date.today().isoformat(),
        "years": years, "price_usd": OFFER["price_usd"], "example": example, "n_drafted": len(drafts),
        "n_orgs": len(lat), "n_audits": len(audits), "n_findings_latest": len(finds), "n_findings_all": sum(len(a["findings"]) for a in audits),
        "n_repeat_findings_latest": sum(f["repeat"] for f in finds),
        "n_repeat_orgs": sum(1 for a in lat if len(a["flagged_years"]) > 1),
        "n_nonprofit_audits_by_year": {str(y): np_all[y] for y in years},
        "n_flagged_by_year": {str(y): sum(1 for a in audits if a["year"] == y) for y in years},
        "n_auditor_firms": len({a["auditor"]["firm"].lower() for a in lat if a["auditor"]["firm"]}),
        "top_requirements": collections.Counter(n for f in finds for n in f["requirement_names"]).most_common(6),
        "top_passthroughs": collections.Counter(p for f in finds for pr in f["programs"] for p in pr["passthrough"]).most_common(6),
        "text_coverage": {"with_text": sum(1 for f in finds if f["text"] and not f["text_is_stub"]), "stub": sum(1 for f in finds if f["text_is_stub"]), "of": len(finds)},
        "prior_cap_coverage": {"with_cap": sum(1 for f in finds if f["prior_cap"]), "of": len(finds)},
    }
    (PUB / "meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k not in ("top_requirements", "top_passthroughs")}, indent=1))
    print("top requirements:", meta["top_requirements"])
    print("top pass-throughs:", meta["top_passthroughs"])


if __name__ == "__main__":
    main()

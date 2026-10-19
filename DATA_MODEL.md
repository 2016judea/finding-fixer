# Finding Fixer — the data model, written from the need first

*Written 2026-10-18 before any FAC pull, per `~/.claude/BUSINESS.md` rule 5. The
"reality" column was filled in afterwards, field by field.*

## The need

A Minnesota nonprofit fails part of its federal Single Audit. The auditor writes
the finding; the nonprofit must answer it with a corrective action plan (CAP) in
the form 2 CFR 200.511(c) requires (the person responsible, the action planned,
the completion date, or a reasoned disagreement) and then answer the pass-through
agency's management decision (2 CFR 200.521) on the same finding. Writing the CAP
is the step this tool takes over. The step after it, defending the plan to the
pass-through, is the paid page.

## Entities and fields

| entity | field | the question it answers for the nonprofit | reality (FAC public API, 2026-10-18) |
|---|---|---|---|
| **Org** | ein, uei | is this me | `general.auditee_ein`, `auditee_uei` ✓ |
| | name, city | is this me | `general.auditee_name`, `auditee_city` ✓ (state filter `auditee_state=MN`) |
| | entity_type | am I in the nonprofit set | `general.entity_type` ✓ (`non-profit`) |
| | contact_name, contact_title, contact_email | who signs the CAP (the default "person responsible") | `general.auditee_contact_name/_title`, `auditee_email` ✓ public |
| | auditor_firm, auditor_contact, auditor_email | who will read the CAP first; the channel | `general.auditor_firm_name`, `auditor_contact_name`, `auditor_email` ✓ |
| **Audit** | report_id, audit_year, fy_end, accepted | which audit, how recent | `general.report_id`, `audit_year`, `fy_end_date`, `fac_accepted_date` ✓ |
| | total_expended | how big my federal footprint is (and how close to the $750K threshold) | `general.total_amount_expended` ✓ |
| | flags: going concern, IC deficiency, material weakness, material noncompliance | what kind of trouble this is | `general.is_*_disclosed`, `is_going_concern_included` ✓ |
| | low_risk_auditee | whether I lost low-risk status (more programs tested next year) | `general.is_low_risk_auditee` ✓ |
| | opinion | was anything qualified | `general.gaap_results` / `is_sp_framework_required` — partial; the opinion on compliance is per award in `federal_awards.audit_report_type` |
| **Finding** | reference_number (e.g. 2024-001) | the number the CAP must answer by | `findings.reference_number` ✓ |
| | award_reference → program | which federal program it is on | `findings.award_reference` → `federal_awards` ✓ |
| | type_requirement | which compliance requirement failed (A–N letters) | `findings.type_requirement` ✓ |
| | severity: material weakness / significant deficiency / other | how hard the agency will push | `findings.is_material_weakness`, `is_significant_deficiency`, `is_other_matters`, `is_other_findings` ✓ |
| | questioned_costs | is money being asked back | `findings.is_questioned_costs` ✓ (flag only; the dollar figure is in the finding text) |
| | modified_opinion | did it qualify the program opinion | `findings.is_modified_opinion` ✓ |
| | repeat, prior_ref | was this already a finding, and which one | `findings.is_repeat_finding`, `prior_finding_ref_numbers` ✓ |
| | text | the auditor's own words: condition, criteria, cause, effect, recommendation | `findings_text.finding_text` ✓ (full text; some are "see attached" stubs) |
| **Prior CAP** | planned_action | what I already told them, so the new draft does not repeat it | `corrective_action_plans.planned_action` ✓ (the auditee's own filed text, by `finding_ref_number`) |
| **Program** | federal_program_name, agency prefix, ALN | the program named in the CAP | `federal_awards.federal_program_name`, `federal_agency_prefix`, `federal_award_extension` ✓ |
| | amount_expended | the size of the program the finding sits on | `federal_awards.amount_expended` ✓ |
| | is_direct, passthrough_name | **who issues the management decision**: the federal agency, or the MN state agency / intermediary that passed the money through | `federal_awards.is_direct` + `passthrough.passthrough_name` ✓ |
| | is_major, audit_report_type | was this a major program; what opinion it got | `federal_awards.is_major`, `audit_report_type` ✓ |
| **CAP draft** (output) | finding_ref, root_cause, action, owner, date, monitoring, disagreement | the document itself, 200.511(c) shape | drafted by a model over the rows above; **no number may come from the model** (dollars, dates and counts are copied from the finding or left as a blank to fill) |
| **Agency page** (output, paid) | per finding: the pass-through's likely questions, what evidence to attach, the 200.521 six-month clock from the FAC acceptance date | the step after the CAP | derived: pass-through from `passthrough`, clock from `fac_accepted_date`, questions drafted from the finding text and requirement type |

## Joins

```
general ──report_id──► findings ──(report_id, reference_number)──► findings_text
                   │                                            └► corrective_action_plans (prior CAP, same key)
                   │                 └──(report_id, award_reference)──► federal_awards ──► passthrough
                   └─(auditee_ein / auditee_uei)─► the same org's other years (repeat chain)
```

## What reality could not fill

- **The dollar amount of questioned costs** is a flag plus free text; the draft
  quotes the figure only when the finding text prints one.
- **The management decision itself** (what the pass-through actually decided) is
  not in the FAC. The agency page is what to expect, not what happened.
- **Nonprofits under the $750K expenditure threshold** have no Single Audit and so
  no row. Those with internal-control letters from a plain financial audit are
  invisible here.
- **~1 in 5 finding texts is a stub** ("see attached schedule") where the auditor
  filed the finding as part of the PDF. Those findings get listed with type and
  repeat flag but no drafted paragraph; the page says so.

## The smallest slice

One org's latest flagged audit: its findings listed (type, severity, repeat), one
drafted CAP paragraph free; the whole CAP document plus the agency page paid.

# Finding Fixer

**Live:** https://finding-fixer.vercel.app

A Minnesota nonprofit that failed part of its federal Single Audit types its name and gets the
corrective action plan drafted from the finding text, in the form the auditor and the
pass-through agency expect. The step taken over: writing the CAP.

Every group that spends $750,000 or more in federal money files a Single Audit with the Federal
Audit Clearinghouse. When the auditor writes a finding, the group must answer it with a
corrective action plan under 2 CFR 200.511(c): who is responsible, what will be done, by when.
Then the pass-through agency (for most Minnesota nonprofits, a state department or a county) has
six months to issue a management decision on it (2 CFR 200.521). Most filed plans copy the
auditor's recommendation back; many findings repeat the next year. This puts a better plan on one
phone screen:

1. **Your findings**: every finding on your latest flagged audit, with the compliance requirement,
   severity (material weakness, significant deficiency, questioned costs), repeat flag and the
   program and pass-through it sits on. The auditor's own text and the plan you already filed,
   as filed.
2. **The drafted plan**: for each finding, the root cause (not a restatement of the condition),
   steps that each leave a record the agency can inspect, the responsible person (your filed
   contact), a completion target, how to monitor it, and the paragraph to file. For a repeat
   finding, why the last plan did not hold.
3. **What the agency will ask**: the pass-through named in your award data, its 200.521 clock
   counted from the FAC acceptance date, and per finding the questions a grant manager asks
   when reviewing a CAP, with the evidence to have ready.
4. **Earlier years**: the same group's findings in prior audits, so the repeat chain is visible.

No login. The search runs in the browser over a public name index; the audit and the drafts come
from two functions over data that never ships as a static file.

## The paywall

Free, to anyone: every finding listed with type, severity and repeat flag, the auditor's text,
the filed plan, and the drafted paragraph for the first finding. Paid, once: the whole plan for
every finding, the agency page, print-to-PDF and a Markdown download.

`site/` ships only `data/index.json` (name, town, EIN, year, counts) and `data/meta.json`.
`scripts/build.py` writes the full data to `private/data/` (gitignored); `scripts/deploy.py`
uploads it as `api/_full/`, which only the functions read. Same mechanism as msp-house-index
(`product-paywall` skill).

| route | does |
|---|---|
| `GET /api/preview?n=<slug>` | the free view of one group's latest flagged audit (`site/api/_view.js`) |
| `GET /api/data?n=<slug>` | the full view; password in `x-password`, HMAC-checked, then a paid Stripe session for it |
| `POST /api/draft {n, ref}` | drafts one finding live (paid only) when it was not pre-drafted at build; Claude Opus 5.5 over the same prompt, `site/api/_prompt.json` |
| `POST /api/checkout` | Stripe embedded Checkout at `offer.json` `price_usd`; mints the password into the session and invoice |
| `POST /api/stripe-webhook` | `checkout.session.completed` via the shared stripe-router: emails the password once, and a sale notice to Aidan |
| `GET /api/session-status` | the return page; sends the password email if the webhook has not |

Vercel env: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` (the router's secret for this product),
`ACCESS_SECRET`, `ANTHROPIC_API_KEY`, `MAILGUN_*`, `SITE_URL`. Lost password:
`python3 scripts/fulfil.py <session_id>`; every sale: `--recent`; a free copy:
`python3 scripts/issue_password.py "comp:<label>"`. Funnel events, to Vercel and PostHog both:
`preview_open`, `checkout_open`, `paid`, `unlock`, `download`, `print`.

Round-1 pages: `/for/<token>/` opens on the reader's own audit (`scripts/build_for.py` from
`outreach/round1/ledger.csv`, both gitignored) and carries the A/B variant in `window.FOR`, never
in the URL.

This repo is private: the git history holds nothing paid, but the drafts are the product.

## Price

**$100, once, for the full plan. A hypothesis under test, set 2026-10-19.**

Arithmetic: a CAP for a Single Audit is otherwise a consultant's day. GSA CALC lists 40 awarded
"Senior Accountant" rates with a median of **$128.79/hour**, fully burdened (read 2026-10-18 via
the CALC API). Eight hours is **$1,030**. A tenth of one use is $103; rounded, $100. Context, not the
basis: msp-house-index at $100 drew 10 checkouts and 0 payments (10/11–10/12), so if round 1 shows
`checkout_open` without `paid`, the price is the first thing to change (distribution-channel rule 15).

## Data

Public record only: the Federal Audit Clearinghouse API (`api.fac.gov`, free key from
api.data.gov; `FAC_API_KEY` in `.env`). `scripts/fetch_fac.py` pulls every Minnesota Single Audit
2022–2025 (`general`), then for each one `findings`, `findings_text`, `corrective_action_plans`,
`federal_awards` and `passthrough`, cached under `data/cache/fac/`. Only `entity_type ==
"non-profit"` ships. Counts on the page are read from `site/data/meta.json`, written by the build.

What the pull found (2026-10-19, `scripts/build.py`): 664 flagged nonprofit audits from 359 groups
over four years; 545 findings on the latest audit per group, 540 with the auditor's full text
(5 are "see the PDF" stubs), all 545 with a filed plan; 177 of the 359 groups were flagged in more
than one year. `DATA_MODEL.md` has the field-by-field check of the ideal model against the FAC.

The drafted plans are made by `scripts/draft.py` (`claude -p`, the prompt in `scripts/prompt.py`)
and cached in `data/cache/drafts/`; audits drafted after the build are drafted live on unlock. The
model reasons over the finding text and never supplies a number: dollars, dates and counts are
copied from the finding or left as a bracketed blank.

## Build

```
python3 scripts/fetch_fac.py      # FAC pull, cached
python3 scripts/build.py          # private/data/audits.json, site/data/index.json, site/data/meta.json
python3 scripts/draft.py          # private/data/drafts.json ($0, claude -p; re-run build.py after)
node --test test/site.test.js     # 11 tests
node scripts/serve_local.js 4710  # the deployed shape, locally
python3 scripts/deploy.py         # Vercel production over the REST API (--setup once)
```

## Distribution

Round 1 is drafted, not sent (`outreach/round1/`, gitignored; `scripts/round1.py`). 50 recipients drafted on 2026-10-19: 20 repeat-finding nonprofits, 12 first-time findings whose 200.521 clock is still open, 8 finance contacts filed for several flagged entities, 10 audit firms; 3 fiscal sponsors held (no flagged audit of their own to open on). Segments: the flagged
nonprofits themselves (repeaters first), their auditors (one email per firm, with the firm's own
offer), and Minnesota fiscal sponsors and nonprofit intermediaries with a public address. Each
recipient's `/for/<token>/` page opens on their own audit; a recipient with no row of their own is
held.

The A/B test, shared across every product in this round so results pool: **variant A states the
price in the email; variant B leaves the price to the page.** Assigned alternately within each
segment; recorded in the ledger beside the token; fired as `preview_open {variant}` from the page.
Hypothesis: stating the price in the email lowers clicks but raises paid-per-click. Readout at day 3:
visits, `checkout_open`, `paid`, replies, by variant and pooled.

MIT for the code. The data is the federal government's and the groups' own filings.

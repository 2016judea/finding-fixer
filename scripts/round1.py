#!/usr/bin/env python3
"""Round 1, drafted not sent: 50 named recipients from the FAC's own contact fields, each opening on
its own audit. Writes outreach/round1/ledger.csv and outreach/round1/drafts/<token>.txt (both
gitignored), then run scripts/build_for.py for the /for/<token>/ pages.

    python3 scripts/round1.py

Segments (BUSINESS.md rule 4: 50 recipients, 3+ kinds of buyer):
  repeat      a nonprofit whose latest audit carries a repeat finding (the plan they filed did not hold)
  clock       a first-time finding whose pass-through decision clock (2 CFR 200.521) is still running
  manager     one finance contact filed for several flagged entities (housing managers, mostly)
  auditor     the audit firm that signed the most flagged MN nonprofit audits since 2024; a channel
  sponsor     Minnesota fiscal sponsors: held, none has a flagged audit of its own in the FAC

Every address is the one the group (or firm) filed with the Federal Audit Clearinghouse, dated by
the FAC acceptance date, checked for a mail server on its domain, and deduped against the
outreach ledger's `contacted` table (outreach-ledger skill: mandatory). A/B is alternated within
each segment: A names the price in the email, B leaves it to the page.
"""
import calendar
import csv
import datetime
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outreach/round1"
SITE = "https://finding-fixer.vercel.app"
TODAY = datetime.date.today().isoformat()
PRICE = json.loads((ROOT / "site/public/offer.json").read_text())["price_usd"]
A = json.loads((ROOT / "private/data/audits.json").read_text())
D = json.loads((ROOT / "private/data/drafts.json").read_text())
L = [a for a in A if a["latest"]]
TARGET = {"repeat": 20, "clock": 12, "manager": 8, "auditor": 10}

contacted = {r[0] for r in duckdb.connect(str(Path.home() / "Desktop/outreach-ledger/outreach.duckdb"), read_only=True)
             .sql("select lower(recipient_key) from contacted where recipient_key is not null").fetchall()}


def rank(f):
    return f["repeat"] * 8 + f["material_weakness"] * 4 + f["questioned_costs"] * 2 + f["significant_deficiency"]


def first(a):
    return sorted(a["findings"], key=lambda f: (-rank(f), f["ref"]))[0]


def clock(acc):
    d = datetime.date.fromisoformat(acc)
    m = d.month + 6
    y, m = d.year + (m - 1) // 12, (m - 1) % 12 + 1
    return datetime.date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def nice(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


_mx = {}


def has_mx(email):
    dom = email.split("@")[-1].lower()
    if dom not in _mx:
        r = subprocess.run(["dig", "+short", "MX", dom], capture_output=True, text=True, timeout=20)
        _mx[dom] = bool(r.stdout.strip())
    return _mx[dom]


def title_case(s):
    return " ".join(w if any(c.islower() for c in w) else w.capitalize() for w in s.split()) if s else s


def person(name):
    return title_case((name or "").strip())


def passthrough(f):
    p = [x for pr in f["programs"] for x in pr["passthrough"]]
    return p[0] if p else ""


def drafted(a, f):
    return f"{a['report_id']}|{f['ref']}" in D


def own_line(a, f):
    what = ", ".join(f["requirement_names"]) or "a compliance requirement"
    prog = (f["programs"][0]["name"] if f["programs"] else "") or "a federal program"
    rep = f", a repeat of {', '.join(f['prior_refs'])}" if f["repeat"] and f["prior_refs"] else (", a repeat finding" if f["repeat"] else "")
    return (f"{a['name']}'s {a['year']} Single Audit, accepted by the Federal Audit Clearinghouse on {nice(a['accepted'])}, "
            f"carries finding {f['ref']} on {prog} ({what.lower()}){rep}.")


def fact_line(a, f):
    pt = passthrough(f)
    due = clock(a["accepted"])
    if due >= TODAY and pt:
        return f"{pt} has until {nice(due)} to issue its management decision on it, and the plan is what it reads first."
    if len(a["flagged_years"]) > 1:
        return f"The FAC shows findings on {a['name']}'s audits in {len(a['flagged_years'])} of the last four years ({', '.join(map(str, a['flagged_years']))})."
    return f"The plan filed with it names who and when, but not why it happened or what record will show it was fixed."


rows = []
taken_email, taken_org = set(), set()


def add(seg, company, name, email, src_date, a, f, own, fact, page_line):
    e = email.strip().lower()
    if not e or e in taken_email or e in contacted or a["slug"] in taken_org:
        return False
    if not has_mx(e):
        return False
    tok = hashlib.sha1(f"finding-fixer|{e}".encode()).hexdigest()[:10]
    rows.append({"token": tok, "segment": seg, "company": company, "name": name, "email": e,
                 "email_source": f"Federal Audit Clearinghouse general record {a['report_id']}", "email_source_date": src_date,
                 "own_record": own, "fact": fact, "org_slug": a["slug"], "finding_ref": f["ref"], "page_line": page_line,
                 "status": "drafted", "hold_reason": "", "drafted_on": TODAY, "sent_on": "", "reply_kind": "", "reply_on": "",
                 "page_url": f"{SITE}/for/{tok}/"})
    taken_email.add(e)
    taken_org.add(a["slug"])
    return True


by_email = defaultdict(list)
for a in L:
    by_email[a["contact"]["email"].strip().lower()].append(a)
newest = sorted(L, key=lambda a: (a["accepted"] or ""), reverse=True)

# manager: one contact filed for several flagged entities. Opens on the newest of them.
n = 0
for e, group in sorted(by_email.items(), key=lambda kv: -len(kv[1])):
    if n >= TARGET["manager"] or len(group) < 2 or not e:
        continue
    a = max(group, key=lambda x: x["accepted"] or "")
    f = first(a)
    if not drafted(a, f):
        continue
    if add("manager", a["name"], person(a["contact"]["name"]), e, a["accepted"], a, f,
           f"You are the filed contact on {len(group)} entities with a flagged Single Audit. The newest: {own_line(a, f)}",
           fact_line(a, f), f"{len(group)} entities name you as their contact. This one is the newest."):
        n += 1
        for x in group:
            taken_org.add(x["slug"])

# repeat, then clock: newest first, drafted only (the free paragraph is never drafted live).
for seg, test in (("repeat", lambda a: any(f["repeat"] for f in a["findings"]) and a["year"] >= 2024),
                  ("clock", lambda a: not any(f["repeat"] for f in a["findings"]) and clock(a["accepted"]) >= TODAY)):
    n = 0
    for a in newest:
        if n >= TARGET[seg] or not test(a) or len(by_email[a["contact"]["email"].strip().lower()]) > 1:
            continue
        f = first(a)
        if not drafted(a, f):
            continue
        if add(seg, a["name"], person(a["contact"]["name"]), a["contact"]["email"], a["accepted"], a, f,
               own_line(a, f), fact_line(a, f), ""):
            n += 1

# auditor: the firms that signed the most flagged audits since 2024, keyed on the filed auditor email.
firm = defaultdict(list)
for a in L:
    if a["year"] >= 2024:
        firm[a["auditor"]["firm"].split(",")[0].replace(" LLP", "").strip().lower()].append(a)
n = 0
for k, group in sorted(firm.items(), key=lambda kv: -len(kv[1])):
    if n >= TARGET["auditor"]:
        break
    for a in sorted(group, key=lambda x: x["accepted"] or "", reverse=True):
        f = first(a)
        e = a["auditor"]["email"].strip().lower()
        if not drafted(a, f) or not e or e in taken_email:
            continue
        own = (f"{a['auditor']['firm']} signed {len(group)} Minnesota nonprofit Single Audits with findings filed since 2024. "
               f"The newest: {own_line(a, f)}")
        taken_org.discard(a["slug"])  # a firm may open on a client another segment also names
        if add("auditor", a["auditor"]["firm"], person(a["auditor"]["contact"]), e, a["accepted"], a, f, own,
               "Each of those clients now owes its pass-through a corrective action plan, and most filed plans copy the recommendation back.",
               f"A client of {a['auditor']['firm']}. The plan below is the kind you could hand them."):
            n += 1
            break

for org in ("Propel Nonprofits", "Springboard for the Arts", "Pillsbury United Communities"):
    rows.append({"token": hashlib.sha1(f"finding-fixer|{org}".encode()).hexdigest()[:10], "segment": "sponsor", "company": org,
                 "name": "", "email": "", "email_source": "", "email_source_date": "", "own_record": "", "fact": "", "org_slug": "",
                 "finding_ref": "", "page_line": "", "status": "hold",
                 "hold_reason": "no flagged Single Audit of its own in the FAC 2022-2025, so no row to open on; no address researched",
                 "drafted_on": TODAY, "sent_on": "", "reply_kind": "", "reply_on": "", "page_url": ""})

# A/B alternated within each segment, so segments stay balanced.
seen = defaultdict(int)
for r in rows:
    r["variant"] = "AB"[seen[r["segment"]] % 2]
    seen[r["segment"]] += 1

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "drafts").mkdir(exist_ok=True)
for p in (OUT / "drafts").glob("*.txt"):
    p.unlink()
cols = ["token", "variant", "segment", "company", "name", "email", "email_source", "email_source_date", "own_record", "fact",
        "org_slug", "finding_ref", "page_line", "status", "hold_reason", "drafted_on", "sent_on", "reply_kind", "reply_on", "page_url"]
with (OUT / "ledger.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

for r in rows:
    if r["status"] == "hold":
        continue
    if r["segment"] == "auditor":
        poke = f"The drafted plan for that finding is open to read, no login: {r['page_url']}"
        price = f" The full plan for a client, every finding with the page of what the agency will ask, is ${PRICE}, once."
    else:
        poke = f"The drafted plan for {r['finding_ref']}, and what your filed plan left out, is open to read, no login: {r['page_url']}"
        price = f" The full plan, every finding answered in the 200.511(c) form with the page of what the agency will ask, is ${PRICE}, once."
    body = "\n".join([
        f"To: {r['email']}",
        f"Subject: bricks / {title_case(r['company'])}",
        "",
        f"{r['own_record']} {r['fact']}",
        "",
        poke + (price if r["variant"] == "A" else ""),
        "",
        "How this gets built: https://randomaidan.substack.com/p/business-prototypes",
        "",
        "Aidan",
        "Brick & Mortar",
        "",
    ])
    (OUT / "drafts" / f"{r['token']}.txt").write_text(body)

cnt = defaultdict(lambda: defaultdict(int))
for r in rows:
    cnt[r["segment"]][r["status"] + "/" + r["variant"]] += 1
print(json.dumps(cnt, indent=1))
print(sum(r["status"] == "drafted" for r in rows), "drafted,", sum(r["status"] == "hold" for r in rows), "held")

#!/usr/bin/env python3
"""Round-1 pages: one /for/<token>/ per recipient, opening on the audit the email names.

    python3 scripts/build_for.py      # outreach/round1/ledger*.csv -> private/for/<token>/index.html

Each page is site/public/index.html with window.FOR = {t, n, line, v} set before the app runs, so it
opens on the reader's own audit and tags every funnel event with the token and the A/B variant
(v: "A" price in the email, "B" price only on the page). The token is in the PATH because Vercel
analytics drops ?query and #hash; the variant never appears in the URL. Pages and ledger are
gitignored; deploy.py ships them. A row with status=hold gets no page.

Every ledger*.csv gets pages, not only ledger.csv: a URL that went out in an email must keep
resolving after the list is regenerated. 2026-10-19 a rerun of round1.py replaced the 50 rows whose
links were already scheduled in Zoho, and every one of those links 404'd. ledger.csv is the round
that went out; ledger_rerun_unsent.csv (status=held) is the regenerated list, whose pages stay up.
On a token in two ledgers, ledger.csv wins.
"""
import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "outreach/round1/ledger.csv"
OUT = ROOT / "private/for"
index = {r["s"] for r in json.loads((ROOT / "site/public/data/index.json").read_text())}
page = (ROOT / "site/public/index.html").read_text()
anchor = "<script>\nconst $ = s =>"
assert anchor in page
shutil.rmtree(OUT, ignore_errors=True)
n, done = 0, set()
for r in (r for led in [LEDGER] + sorted(LEDGER.parent.glob("ledger_*.csv")) for r in csv.DictReader(led.open())):
    t, s = r["token"].strip(), r.get("org_slug", "").strip()
    if not t or not s or t in done or r.get("status", "").strip() == "hold":
        continue
    done.add(t)
    assert s in index, f"{t}: no audit with slug {s}"
    cfg = {"t": t, "n": s, "line": r.get("page_line", "").strip(), "v": r.get("variant", "").strip()}
    html = page.replace(anchor, f"<script>window.FOR={json.dumps(cfg)};</script>\n" + anchor, 1)
    html = html.replace("<title>Finding Fixer</title>", "<title>Finding Fixer</title>\n<meta name=\"robots\" content=\"noindex\">", 1)
    d = OUT / t
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html)
    n += 1
print(f"{n} pages in {OUT}")

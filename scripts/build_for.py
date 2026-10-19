#!/usr/bin/env python3
"""Round-1 pages: one /for/<token>/ per recipient, opening on the audit the email names.

    python3 scripts/build_for.py      # outreach/round1/ledger.csv -> private/for/<token>/index.html

Each page is site/index.html with window.FOR = {t, n, line, v} set before the app runs, so it
opens on the reader's own audit and tags every funnel event with the token and the A/B variant
(v: "A" price in the email, "B" price only on the page). The token is in the PATH because Vercel
analytics drops ?query and #hash; the variant never appears in the URL. Pages and ledger are
gitignored; deploy.py ships them. A row with status=hold gets no page.
"""
import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "outreach/round1/ledger.csv"
OUT = ROOT / "private/for"
index = {r["s"] for r in json.loads((ROOT / "site/data/index.json").read_text())}
page = (ROOT / "site/index.html").read_text()
anchor = "<script>\nconst $ = s =>"
assert anchor in page
shutil.rmtree(OUT, ignore_errors=True)
n = 0
for r in csv.DictReader(LEDGER.open()):
    t, s = r["token"].strip(), r.get("org_slug", "").strip()
    if not t or not s or r.get("status", "").strip() == "hold":
        continue
    assert s in index, f"{t}: no audit with slug {s}"
    cfg = {"t": t, "n": s, "line": r.get("page_line", "").strip(), "v": r.get("variant", "").strip()}
    html = page.replace(anchor, f"<script>window.FOR={json.dumps(cfg)};</script>\n" + anchor, 1)
    html = html.replace("<title>Finding Fixer</title>", "<title>Finding Fixer</title>\n<meta name=\"robots\" content=\"noindex\">", 1)
    d = OUT / t
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html)
    n += 1
print(f"{n} pages in {OUT}")

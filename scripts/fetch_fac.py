#!/usr/bin/env python3
"""Pull every Minnesota Single Audit from the Federal Audit Clearinghouse public API, with
its findings, the auditor's finding text, the auditee's filed corrective action plan, the
federal awards and who passed each award through.

    python3 scripts/fetch_fac.py            # 2022-2025, cached in data/cache/fac/

Source: https://api.fac.gov (PostgREST). Key: FAC_API_KEY in .env (api.data.gov, free; 1,000
calls/hour). Every response is cached by URL hash, so a re-run costs nothing until the cache is
cleared. Reads nothing from the bricks repo; the FAC is the only source.
"""
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data/cache/fac"
OUT = ROOT / "data/fac"
API = "https://api.fac.gov"
YEARS = [2022, 2023, 2024, 2025]
PAGE = 5000
CHUNK = 80  # report_ids per in-list


def key():
    for p in (ROOT / ".env", Path.home() / "Desktop/workspace/bricks/.env"):
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("FAC_API_KEY="):
                    return line.split("=", 1)[1].strip()
    sys.exit("FAC_API_KEY missing from .env")


KEY = key()
CALLS = 0


def get(table, params):
    """One cached GET. params is a list of (k, v) so the same filter can repeat."""
    global CALLS
    qs = urllib.parse.urlencode(params, safe="(),.*")
    url = f"{API}/{table}?{qs}"
    f = CACHE / f"{table}-{hashlib.sha1(url.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text())
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"X-Api-Key": KEY, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
            CALLS += 1
            rows = json.loads(body)
            if not isinstance(rows, list):
                raise RuntimeError(f"{table}: {str(rows)[:200]}")
            CACHE.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(rows))
            return rows
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")[:300]
            if e.code == 429 or e.code >= 500:
                print(f"  {e.code} on {table}; sleeping {60 if e.code == 429 else 10 + attempt * 10}s", file=sys.stderr)
                time.sleep(60 if e.code == 429 else 10 + attempt * 10)
                continue
            raise RuntimeError(f"{table} {e.code}: {txt}") from None
        except (urllib.error.URLError, TimeoutError):
            time.sleep(3 + attempt * 5)
    sys.exit(f"{table}: gave up")


def all_rows(table, params):
    rows, offset = [], 0
    while True:
        page = get(table, params + [("limit", PAGE), ("offset", offset)])
        rows += page
        if len(page) < PAGE:
            return rows
        offset += PAGE


def by_report(table, ids, extra=()):
    rows = []
    ids = sorted(set(ids))
    for i in range(0, len(ids), CHUNK):
        rows += all_rows(table, [("report_id", "in.(" + ",".join(ids[i:i + CHUNK]) + ")")] + list(extra))
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    general = []
    for y in YEARS:
        g = all_rows("general", [("auditee_state", "eq.MN"), ("audit_year", f"eq.{y}")])
        print(f"general {y}: {len(g)}")
        general += g
    (OUT / "general.json").write_text(json.dumps(general))

    ids = [g["report_id"] for g in general]
    findings = by_report("findings", ids)
    print(f"findings: {len(findings)} on {len({f['report_id'] for f in findings})} audits")
    (OUT / "findings.json").write_text(json.dumps(findings))

    fids = sorted({f["report_id"] for f in findings})
    text = by_report("findings_text", fids)
    print(f"findings_text: {len(text)}")
    (OUT / "findings_text.json").write_text(json.dumps(text))

    caps = by_report("corrective_action_plans", fids)
    print(f"corrective_action_plans: {len(caps)}")
    (OUT / "caps.json").write_text(json.dumps(caps))

    awards = by_report("federal_awards", fids)
    print(f"federal_awards (audits with findings): {len(awards)}")
    (OUT / "federal_awards.json").write_text(json.dumps(awards))

    pt = by_report("passthrough", fids)
    print(f"passthrough: {len(pt)}")
    (OUT / "passthrough.json").write_text(json.dumps(pt))
    print(f"API calls this run: {CALLS}")


if __name__ == "__main__":
    main()

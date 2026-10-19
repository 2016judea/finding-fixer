#!/usr/bin/env python3
"""Draft a CAP for every finding on the latest flagged audit of each nonprofit, at $0.

    python3 scripts/draft.py --sample 3        # three findings, printed, nothing saved
    python3 scripts/draft.py [--jobs 6]        # every finding on every latest audit -> private/data/drafts.json
    python3 scripts/draft.py --only <slug>     # one org
    python3 scripts/draft.py --collect         # drafts.json from the cache, guarded; no drafting

Runs `claude -p` with the prompt in scripts/prompt.py and a JSON schema, under Aidan's own
subscription, so a 300-finding build costs nothing (memory: "Test a Claude-API prompt + JSON
schema for $0"). Each finding's draft is cached in data/cache/drafts/<report>|<ref>.json; a
re-run only drafts what is missing. The live route (site/api/_draft.js) uses the same prompt
through the SDK for audits that were not pre-drafted.
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompt import SCHEMA, SYSTEM, allowed_numbers, scrub, user_content  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data/cache/drafts"
AUDITS = ROOT / "private/data/audits.json"
OUT = ROOT / "private/data/drafts.json"
MODEL = os.environ.get("DRAFT_MODEL", "opus")


def guarded(audit, finding, d):
    """The number guard (scripts/prompt.py): a figure the model was not shown becomes [number]."""
    removed = []
    out = scrub(d, allowed_numbers(user_content(audit, finding)), removed)
    out["_scrubbed"] = removed
    return out


def draft_one(audit, finding):
    key, d = _draft_one(audit, finding)
    return key, (guarded(audit, finding, d) if d else None)


def _draft_one(audit, finding):
    key = f"{audit['report_id']}|{finding['ref']}"
    f = CACHE / (key.replace("|", "__") + ".json")
    if f.exists():
        return key, json.loads(f.read_text())
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # the subscription, not the key
    env["ENABLE_TOOL_SEARCH"] = "false"
    cmd = ["claude", "-p", "--model", MODEL, "--tools", "", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA),
           "--output-format", "json", user_content(audit, finding)]
    for attempt in range(3):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL)
        try:
            j = json.loads(r.stdout)
            out = j.get("structured_output") or json.loads(j.get("result", ""))
            if "session limit" in json.dumps(j).lower():
                raise RuntimeError("session limit")
            out["_model"] = MODEL
            out["_drafted"] = __import__("datetime").date.today().isoformat()
            CACHE.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(out))
            return key, out
        except Exception as e:  # noqa: BLE001
            err = f"{e}: {r.stdout[:300]} {r.stderr[:300]}"
    print(f"  FAILED {key}: {err}", file=sys.stderr)
    return key, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--only")
    ap.add_argument("--collect", action="store_true", help="rebuild drafts.json from the cache only; draft nothing")
    a = ap.parse_args()
    audits = [x for x in json.loads(AUDITS.read_text()) if x["latest"] and (not a.only or x["slug"] == a.only)]
    # The free slice shows each group's FIRST finding drafted (site/api/_view.js order: repeat, material
    # weakness, questioned costs, significant deficiency), and that paragraph is never drafted live. So
    # every group's first finding goes first, newest audits first; the rest after (paid unlocks can
    # also draft those live).
    rank = lambda f: (f["repeat"] * 8 + f["material_weakness"] * 4 + f["questioned_costs"] * 2 + f["significant_deficiency"])
    jobs = []
    for x in audits:
        for i, f in enumerate(sorted(x["findings"], key=lambda f: (-rank(f), f["ref"]))):
            jobs.append((i > 0, -x["year"], x["slug"], i, x, f))
    jobs = [(x, f) for *_, x, f in sorted(jobs, key=lambda j: j[:4])]
    if a.sample:
        import random
        random.seed(11)
        jobs = random.sample([j for j in jobs if j[1]["text"] and not j[1]["text_is_stub"]], a.sample)
        for x, f in jobs:
            key, d = draft_one(x, f)
            print(f"\n===== {x['name']} {f['ref']} ({', '.join(f['requirement_names'])}; repeat={f['repeat']})")
            print("FINDING:", f["text"][:700].replace("\n", " "))
            print("FILED CAP:", f["prior_cap"][:500].replace("\n", " "))
            print("DRAFT:", json.dumps(d, indent=1) if d else "FAILED")
        return
    cached = sum(1 for x, f in jobs if (CACHE / (x["report_id"] + "__" + f["ref"] + ".json")).exists())
    print(f"{len(jobs)} findings on {len(audits)} audits; {cached} cached", flush=True)
    drafts = {}  # rebuilt from the cache every run, so the guard covers old drafts too
    if a.collect:
        for x, f in jobs:
            c = CACHE / (x["report_id"] + "__" + f["ref"] + ".json")
            if c.exists():
                drafts[f"{x['report_id']}|{f['ref']}"] = guarded(x, f, json.loads(c.read_text()))
        OUT.write_text(json.dumps(drafts))
        print(f"{len(drafts)} drafts collected into {OUT}")
        return
    with ThreadPoolExecutor(a.jobs) as ex:
        for i, (key, d) in enumerate(ex.map(lambda j: draft_one(*j), jobs), 1):
            if d:
                drafts[key] = d
            if i % 20 == 0:
                OUT.write_text(json.dumps(drafts))
                print(f"  {i}/{len(jobs)}", flush=True)
    OUT.write_text(json.dumps(drafts))
    missing = sum(1 for x, f in jobs if (x["report_id"] + "|" + f["ref"]) not in drafts)
    print(f"{len(drafts)} drafts in {OUT}; {missing} missing")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Draft a CAP for every finding on the latest flagged audit of each nonprofit, at $0.

    python3 scripts/draft.py --sample 3        # three findings, printed, nothing saved
    python3 scripts/draft.py [--jobs 6]        # every finding on every latest audit -> private/data/drafts.json
    python3 scripts/draft.py --only <slug>     # one org

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
from prompt import SCHEMA, SYSTEM, user_content  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data/cache/drafts"
AUDITS = ROOT / "private/data/audits.json"
OUT = ROOT / "private/data/drafts.json"
MODEL = os.environ.get("DRAFT_MODEL", "opus")


def draft_one(audit, finding):
    key = f"{audit['report_id']}|{finding['ref']}"
    f = CACHE / (key.replace("|", "__") + ".json")
    if f.exists():
        return key, json.loads(f.read_text())
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # the subscription, not the key
    env["ENABLE_TOOL_SEARCH"] = "false"
    cmd = ["claude", "-p", "--model", MODEL, "--tools", "", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA),
           "--output-format", "json", user_content(audit, finding)]
    for attempt in range(3):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env, cwd=str(ROOT))
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
    a = ap.parse_args()
    audits = [x for x in json.loads(AUDITS.read_text()) if x["latest"] and (not a.only or x["slug"] == a.only)]
    # Newest audits first: the groups most likely to be writing a CAP right now, and the ones the round-1 list names.
    audits.sort(key=lambda x: (-x["year"], x["slug"]))
    jobs = [(x, f) for x in audits for f in x["findings"]]
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
    print(f"{len(jobs)} findings on {len(audits)} audits; {cached} cached")
    drafts = json.loads(OUT.read_text()) if OUT.exists() else {}
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

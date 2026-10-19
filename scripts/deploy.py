#!/usr/bin/env python3
"""Create (once), configure and deploy site/ to Vercel production over the REST API.

    python3 scripts/deploy.py --setup   # create the project, env vars, analytics, public (idempotent)
    python3 scripts/deploy.py           # deploy site/ + private/data (as api/_full/) + private/for (as for/)

Not the CLI: `vercel deploy --prod` has returned BLOCKED on this account with no error while
/v13/deployments goes READY (unit-turns-mpls, 2026-10-17). Polls readyState, exits non-zero on
anything but READY. Keys come from ~/Desktop/bricks/.env (the keyring) unless set in the
environment. ACCESS_SECRET is generated once into .access_secret (gitignored) and mirrored
into ./.env for fulfil.py and issue_password.py.

The paywall (README "The paywall"): site/ is public and holds only the free index. private/data/
(every finding, the texts, the drafts; scripts/build.py, gitignored) goes up as api/_full/, bundled
only with the functions and redirected away from any public URL (site/vercel.json).
"""
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
PRIVATE = REPO / "private"
EXTRA = [(PRIVATE / "data", "api/_full"), (PRIVATE / "for", "public/for")]
OFFER = json.loads((SITE / "public/offer.json").read_text())
PROJECT = OFFER["product"]
TEAM = "team_XnhPzBEcaSfEmZFo9M2isLFY"
SKIP = {".git", "node_modules", ".vercel", "__pycache__", ".DS_Store", ".env"}
KEYRING = Path.home() / "Desktop/bricks/.env"


def env(name):
    if os.environ.get(name):
        return os.environ[name]
    for line in KEYRING.read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit(f"{name} is not in the environment or {KEYRING}")


def req(method, url, token, body=None, headers=None, raw=None):
    h = {"Authorization": f"Bearer {token}"}
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if body is not None:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
        except urllib.error.URLError:
            time.sleep(2 + attempt * 3)  # Errno 51 is transient here; retry
    sys.exit(f"network failed: {url}")


def access_secret():
    f = REPO / ".access_secret"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    s = f.read_text().strip()
    dotenv = REPO / ".env"
    lines = dotenv.read_text().splitlines() if dotenv.exists() else []
    if not any(l.startswith("ACCESS_SECRET=") for l in lines):
        lines.append(f"ACCESS_SECRET={s}")
        dotenv.write_text("\n".join(lines) + "\n")
    return s


def setup(token):
    api = "https://api.vercel.com"
    code, p = req("GET", f"{api}/v9/projects/{PROJECT}?teamId={TEAM}", token)
    if code == 404:
        code, p = req("POST", f"{api}/v10/projects?teamId={TEAM}", token, {"name": PROJECT, "framework": None})
        print("created project", code, p.get("id"))
    pid = p["id"]
    vals = {"STRIPE_SECRET_KEY": env("STRIPE_SECRET_KEY"), "ANTHROPIC_API_KEY": env("ANTHROPIC_API_KEY"),
            "ACCESS_SECRET": access_secret(), "SITE_URL": OFFER["site"],
            **{k: env(k) for k in ("MAILGUN_API_KEY", "MAILGUN_DOMAIN", "MAILGUN_FROM")}}
    for k, v in vals.items():
        c, out = req("POST", f"{api}/v10/projects/{pid}/env?teamId={TEAM}&upsert=true", token,
                     {"key": k, "value": v, "type": "encrypted", "target": ["production", "preview"]})
        print("env", k, c)
    c, out = req("POST", f"{api}/web/insights/toggle?projectId={pid}&teamId={TEAM}", token, {"value": True})
    print("analytics", c, out)
    c, out = req("PATCH", f"{api}/v9/projects/{pid}?teamId={TEAM}", token, {"ssoProtection": None})
    print("public", c)
    print("alias", (p.get("targets", {}).get("production") or {}).get("alias"))


def collect():
    for path in sorted(SITE.rglob("*")):
        rel = path.relative_to(SITE)
        if path.is_file() and not any(part in SKIP for part in rel.parts):
            yield rel, path
    for src, dest in EXTRA:
        for path in sorted(src.rglob("*")) if src.exists() else []:
            if path.is_file() and path.name not in SKIP:
                yield Path(dest) / path.relative_to(src), path


def deploy(token):
    assert (PRIVATE / "data" / "audits.json").exists(), "run scripts/build.py: private/data/ is what the API serves"
    files, total = [], 0
    for rel, path in collect():
        body = path.read_bytes()
        sha = hashlib.sha1(body).hexdigest()
        c, out = req("POST", "https://api.vercel.com/v2/files", token, raw=body,
                     headers={"Content-Type": "application/octet-stream", "x-vercel-digest": sha, "x-vercel-team-id": TEAM})
        if c >= 400:
            sys.exit(f"upload {rel} failed: {c} {out}")
        files.append({"file": str(rel), "sha": sha, "size": len(body)})
        total += len(body)
    print(f"  {len(files)} files, {total:,} bytes")
    c, out = req("POST", f"https://api.vercel.com/v13/deployments?teamId={TEAM}&skipAutoDetectionConfirmation=1", token,
                 {"name": PROJECT, "project": PROJECT, "target": "production", "files": files,
                  "projectSettings": {"framework": None, "buildCommand": "echo build", "outputDirectory": "public", "installCommand": "echo skip"}})
    if c >= 400 or out.get("error"):
        sys.exit(f"create failed: {c} {json.dumps(out.get('error'))}")
    url = out["url"]
    print(f"  deploying https://{url}")
    for _ in range(100):
        time.sleep(3)
        _, d = req("GET", f"https://api.vercel.com/v13/deployments/{url}?teamId={TEAM}", token)
        s = d.get("readyState")
        if s in ("READY", "ERROR", "BLOCKED", "CANCELED"):
            print(f"  {s} {d.get('errorMessage') or ''}")
            sys.exit(0 if s == "READY" else 1)
    sys.exit("timed out")


if __name__ == "__main__":
    tok = env("VERCEL_TOKEN")
    setup(tok) if "--setup" in sys.argv else deploy(tok)

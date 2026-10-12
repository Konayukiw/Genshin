# -*- coding: utf-8 -*-
"""Fetch LUNABASE (lunnoa1013/LUNABASE-Simulator, data/ only) into _tmp/LUNABASE
and list characters / weapons / artifacts it has that data/v1 does not.

LUNABASE is the id source for entities: a new character / weapon / artifact
added to data/v1 should carry the id LUNABASE assigns it. Requires `gh auth
login` with access to the (private) repo.
"""
import io
import json
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if sys.stdout else sys.stdout

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "v1"
REPO = "lunnoa1013/LUNABASE-Simulator"
DEST = ROOT / "_tmp" / "LUNABASE"
LUNA = DEST / "data"

LOCALES = ("en", "ja", "zh")
# Removed from data/v1 on purpose (unreleased Traveler entries, nameless test swords)
IGNORE_IDS = {"10000134", "10000135", "390002", "390003"}


def run(*cmd):
    subprocess.run(cmd, check=True)


def fetch():
    if (DEST / ".git").is_dir():
        run("git", "-C", str(DEST), "fetch", "--depth", "1", "origin", "HEAD")
        run("git", "-C", str(DEST), "reset", "--hard", "FETCH_HEAD")
    else:
        DEST.parent.mkdir(parents=True, exist_ok=True)
        run("gh", "repo", "clone", REPO, str(DEST), "--",
            "--filter=blob:none", "--sparse", "--depth", "1", "-c", "core.longpaths=true")
        run("git", "-C", str(DEST), "sparse-checkout", "set", "data")
    log = subprocess.run(["git", "-C", str(DEST), "log", "-1", "--format=%cs %h %s"],
                         capture_output=True, text=True, encoding="utf-8").stdout.strip()
    print(f"LUNABASE @ {log}\n")


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def api_ids(cat, lang="en"):
    return {i["id"] for i in load_json(DATA / lang / cat / "index.json")["items"] if i["id"]}


def report(label, luna, ours):
    new = {k: v for k, v in luna.items() if k not in ours and k not in IGNORE_IDS}
    gone = sorted(ours - set(luna))
    print(f"{label:16} LUNABASE={len(luna):4}  API={len(ours):4}  new={len(new)}")
    for eid, name in sorted(new.items()):
        print(f"    + {eid:12} {name}")
    if gone:
        print(f"    (API only: {gone})")
    return len(new)


def main():
    fetch()
    n_new = 0
    for cat in ("characters", "weapons"):
        luna = {str(e["id"]): e.get("en_name") or e.get("name")
                for e in load_json(LUNA / f"{cat}.json")}
        n_new += report(cat, luna, api_ids(cat))
    for lang in LOCALES:
        luna = {str(e["id"]): e.get("name")
                for e in load_json(LUNA / "artifacts" / lang / "artifacts.json")}
        n_new += report(f"artifacts/{lang}", luna, api_ids("artifacts", lang))
    print(f"\n{n_new} entr{'y' if n_new == 1 else 'ies'} in LUNABASE missing from data/v1"
          if n_new else "\ndata/v1 is up to date with LUNABASE")


if __name__ == "__main__":
    main()

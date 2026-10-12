# -*- coding: utf-8 -*-
"""Validate data/v1/: JSON parseability, index/file consistency, id coverage."""
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "v1"
LOCALES = ("en", "ja", "zh")
CATS = ("characters", "weapons", "artifacts")
QTYPES = ("archon", "story", "world", "event", "hangout")

errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


def main():
    # 1. every JSON parses
    n_files = 0
    for p in DATA.rglob("*.json"):
        n_files += 1
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"unparseable: {p.relative_to(DATA)}: {e}")
    print(f"parsed {n_files} JSON files")

    # 2. manifest + locale/category index consistency
    manifest = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    check(bool(manifest.get("data_version")), "manifest missing data_version")
    check(manifest.get("locales") == list(LOCALES), "manifest locales mismatch")

    for lang in LOCALES:
        for cat in CATS:
            idx = json.loads((DATA / lang / cat / "index.json").read_text(encoding="utf-8"))
            slugs = [Path(i["url"]).name for i in idx["items"]]
            files = {p.name for p in (DATA / lang / cat).glob("*.json")
                     if p.name != "index.json"}
            check(idx["count"] == len(idx["items"]), f"{lang}/{cat}: count mismatch")
            check(set(slugs) == files, f"{lang}/{cat}: index slugs != files")
            no_id = [i["slug"] for i in idx["items"] if not i["id"]]
            if no_id:
                print(f"  note: {lang}/{cat}: {len(no_id)} item(s) without id: {no_id[:5]}")
        for qt in QTYPES:
            idxp = DATA / lang / "quests" / qt / "index.json"
            if not idxp.is_file():
                continue
            idx = json.loads(idxp.read_text(encoding="utf-8"))
            slugs = {Path(i["url"]).name for i in idx["items"]}
            files = {p.name for p in (DATA / lang / "quests" / qt).glob("*.json")
                     if p.name != "index.json"}
            check(set(slugs) == files, f"{lang}/quests/{qt}: index slugs != files")

    # icons: every listed file exists and belongs to a known character
    icons = json.loads((DATA / "icons" / "index.json").read_text(encoding="utf-8"))
    char_ids = {i["id"] for i in json.loads(
        (DATA / "en" / "characters" / "index.json").read_text(encoding="utf-8"))["items"]}
    check(icons["count"] == len(icons["items"]), "icons: count mismatch")
    for i in icons["items"]:
        check((DATA / "icons" / i["file"]).is_file(), f"icons: missing file {i['file']}")
        check(i["id"] in char_ids, f"icons: unknown character id {i['id']}")
    print(f"icons: {icons['count']}/{len(char_ids)} characters")

    # 3. cross-locale id parity for entities (report only; untranslated items
    #    in a given locale may legitimately lack an id)
    idsets = {}
    for cat in CATS:
        s = {}
        for lang in LOCALES:
            idx = json.loads((DATA / lang / cat / "index.json").read_text(encoding="utf-8"))
            s[lang] = {i["id"] for i in idx["items"] if i["id"]}
        idsets[cat] = s
        mask = s["en"] & s["ja"] & s["zh"]
        print(f"{cat}: en={len(s['en'])} ja={len(s['ja'])} zh={len(s['zh'])} "
              f"common={len(mask)}")

    # 4. quest id coverage summary
    for qt in QTYPES:
        row = []
        for lang in LOCALES:
            idxp = DATA / lang / "quests" / qt / "index.json"
            if not idxp.is_file():
                row.append(f"{lang}: -")
                continue
            idx = json.loads(idxp.read_text(encoding="utf-8"))
            wid = sum(1 for i in idx["items"] if i["id"])
            row.append(f"{lang}: {wid}/{idx['count']}")
        print(f"quests/{qt:8} {'  '.join(row)}")

    print()
    if errors:
        print(f"FAILED with {len(errors)} problem(s):")
        for e in errors[:30]:
            print(f"  - {e}")
        sys.exit(1)
    print("OK: data/v1 is consistent")


if __name__ == "__main__":
    main()

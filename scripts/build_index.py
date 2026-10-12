# -*- coding: utf-8 -*-

import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if sys.stdout else sys.stdout

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "v1"

LOCALES = ("en", "ja", "zh")
CATEGORIES = ("characters", "weapons", "artifacts")
QUEST_TYPES = ("archon", "story", "world", "event", "hangout")
ICON_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg")
VARIANT_SUFFIX_RE = re.compile(r"\s*\([^()]*\)$")
TRAVELER_IDS = {"10000005", "10000007"}


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def dump_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def ordered_files(dirpath, key="slug"):
    files = {p.stem: p for p in dirpath.glob("*.json") if p.name != "index.json"}
    idx = dirpath / "index.json"
    prev = [i[key] for i in load_json(idx)["items"]] if idx.is_file() else []
    order = [s for s in dict.fromkeys(prev) if s in files]
    order += sorted(set(files) - set(order))
    return [(s, files[s]) for s in order]


def build_entities():
    canonical = {cat: {} for cat in CATEGORIES}
    for lang in LOCALES:
        for cat in CATEGORIES:
            items = []
            for slug, p in ordered_files(DATA / lang / cat):
                obj = load_json(p)
                eid = obj.get("id")
                name = obj.get("name") or obj.get("set_name")
                en = canonical[cat].get(eid) if eid else None
                if lang == "en":
                    en_name = name
                elif en:
                    en_name = en["name"]
                    if cat == "characters" and "-" in eid:
                        en_name = ("Traveler" if eid.split("-")[0] in TRAVELER_IDS
                                   else VARIANT_SUFFIX_RE.sub("", en_name))
                else:
                    en_name = name
                item = {"id": eid, "slug": slug, "name": name, "en_name": en_name,
                        "url": f"/v1/{lang}/{cat}/{slug}.json"}
                if cat == "characters":
                    item["rarity"] = obj.get("rarity")
                    item["element"] = obj.get("element")
                    item["weapon"] = obj.get("weapon")
                    if lang != "en" and en:
                        item["element_en"] = en["element"]
                        item["weapon_en"] = en["weapon"]
                elif cat == "weapons":
                    item["rarity"] = obj.get("rarity")
                    item["type"] = obj.get("type")
                    item["base_atk"] = obj.get("base_atk")
                    if lang != "en" and en:
                        item["type_en"] = en["type"]
                elif cat == "artifacts":
                    item["affixes"] = len(obj.get("affixes") or [])
                items.append(item)
                if lang == "en" and eid:
                    canonical[cat][eid] = item
            dump_json(DATA / lang / cat / "index.json", {
                "locale": lang, "category": cat, "count": len(items), "items": items})
    return canonical


def build_quests():
    for lang in LOCALES:
        qtypes = {}
        for qtype in QUEST_TYPES:
            qdir = DATA / lang / "quests" / qtype
            if not qdir.is_dir():
                continue
            items = []
            for slug, p in ordered_files(qdir):
                obj = load_json(p)
                title = ((obj.get("quests") or [{}])[0].get("title")
                         or obj.get("act_title") or slug)
                items.append({
                    "id": obj.get("id"), "slug": slug, "title": title,
                    "chapter": obj.get("chapter"), "act": obj.get("act"),
                    "region": obj.get("region"),
                    "url": f"/v1/{lang}/quests/{qtype}/{slug}.json",
                })
            dump_json(qdir / "index.json", {
                "locale": lang, "category": "quests", "quest_type": qtype,
                "count": len(items), "items": items})
            qtypes[qtype] = {"count": len(items), "url": f"/v1/{lang}/quests/{qtype}"}
        dump_json(DATA / lang / "quests" / "index.json", {
            "locale": lang, "category": "quests",
            "count": sum(v["count"] for v in qtypes.values()), "quest_types": qtypes})


def build_icons(canonical):
    icon_dir = DATA / "icons"
    names = {lang: {i["id"]: i["name"]
                    for i in load_json(DATA / lang / "characters" / "index.json")["items"]}
             for lang in LOCALES}
    by_slug = {c["slug"]: eid for eid, c in canonical["characters"].items()}
    files = {p.stem: p.name for p in icon_dir.iterdir() if p.suffix.lower() in ICON_EXTS}
    idx = icon_dir / "index.json"
    prev = [i["id"] for i in load_json(idx)["items"]] if idx.is_file() else []
    found = {by_slug[s]: f for s, f in files.items() if s in by_slug}
    order = [i for i in dict.fromkeys(prev) if i in found]
    order += sorted(set(found) - set(order))
    items = [{"id": eid, "en_name": names["en"].get(eid), "zh_name": names["zh"].get(eid),
              "ja_name": names["ja"].get(eid), "file": found[eid]} for eid in order]
    dump_json(idx, {"count": len(items), "items": items})
    orphans = sorted(f for s, f in files.items() if s not in by_slug)
    missing = sorted(c["slug"] for eid, c in canonical["characters"].items() if eid not in found)
    return orphans, missing


def build_manifest(now):
    counts = {}
    for lang in LOCALES:
        cats = {}
        for cat in CATEGORIES:
            d = load_json(DATA / lang / cat / "index.json")
            cats[cat] = {"count": d["count"], "url": f"/v1/{lang}/{cat}"}
            counts[f"{cat}/{lang}"] = d["count"]
        q = load_json(DATA / lang / "quests" / "index.json")
        cats["quests"] = {"count": q["count"], "url": f"/v1/{lang}/quests"}
        counts[f"quests/{lang}"] = q["count"]
        dump_json(DATA / lang / "index.json", {"locale": lang, "categories": cats})

    manifest = {
        "schema_version": 1,
        "data_version": now.strftime("%Y%m%dT%H%MZ"),
        "generated_at": now.isoformat(),
        "locales": list(LOCALES),
        "quest_types": list(QUEST_TYPES),
        "counts": counts,
        "endpoints": {lang: f"/v1/{lang}" for lang in LOCALES},
        "license": ("Game content and data © HoYoverse / Cognosphere. "
                    "Unofficial fan project; not affiliated with or endorsed by HoYoverse."),
    }
    dump_json(DATA / "index.json", manifest)
    return manifest


def main():
    now = datetime.now(timezone.utc)
    canonical = build_entities()
    build_quests()
    orphans, missing = build_icons(canonical)
    manifest = build_manifest(now)

    print(f"data_version: {manifest['data_version']}")
    for key, n in manifest["counts"].items():
        print(f"  {key:16} {n:5}")
    if orphans:
        print(f"warning: icons without a matching en character slug: {orphans}")
    if missing:
        print(f"note: characters without an icon: {missing}")


if __name__ == "__main__":
    main()

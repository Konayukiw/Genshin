# -*- coding: utf-8 -*-
"""Build data/v1/ (publishable dataset + 3-layer indexes) from source/ data.

- Injects LUNABASE entity ids ("id" key) into characters / weapons / artifacts.
- Injects recovered Honey Hunter wiki ids into quest files (may be null).
- Emits per-locale index.json + per-category index.json + root manifest.
"""
import io
import json
import os
import re
import sys
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if sys.stdout else sys.stdout

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source"
DATA = ROOT / "data" / "v1"
LUNA = Path(r"E:\Projects\LUNABASE") / "data"
MAPS = ROOT / "scripts" / "maps"

LOCALES = ("en", "ja", "zh")
LANG_DIR = {"en": "En", "ja": "Ja", "zh": "Zh"}
CAT_DIR = {
    "characters": {"en": "Characters", "ja": "キャラクター", "zh": "角色"},
    "weapons": {"en": "Weapons", "ja": "武器", "zh": "武器"},
    "artifacts": {"en": "Artifacts", "ja": "聖遺物", "zh": "圣遗物"},
}
QUEST_TYPES = ("archon", "story", "world", "event", "hangout")
QUEST_DIR = {
    "archon": {"en": "Archon Quests", "ja": "魔神任務", "zh": "魔神任务"},
    "story": {"en": "Story Quests", "ja": "伝説任務", "zh": "传说任务"},
    "world": {"en": "World Quests", "ja": "世界任務", "zh": "世界任务"},
    "event": {"en": "Event Quests", "ja": "イベント任務", "zh": "活动任务"},
    "hangout": {"en": None, "ja": "デート任務", "zh": "邀约任务"},
}
ELEMENT_L10N = {
    "en": {"Anemo": "Anemo", "Geo": "Geo", "Electro": "Electro", "Dendro": "Dendro",
           "Hydro": "Hydro", "Pyro": "Pyro", "Cryo": "Cryo", "None": "None"},
    "ja": {"Anemo": "風", "Geo": "岩", "Electro": "雷", "Dendro": "草",
           "Hydro": "水", "Pyro": "炎", "Cryo": "氷", "None": "無"},
    "zh": {"Anemo": "风", "Geo": "岩", "Electro": "雷", "Dendro": "草",
           "Hydro": "水", "Pyro": "火", "Cryo": "冰", "None": "无"},
}
ELEM2CANON = {}
for _loc_map in ELEMENT_L10N.values():       # each locale's {canon_element: localized_token}
    for _canon, _loc in _loc_map.items():
        ELEM2CANON[_loc] = _canon            # localized token -> canonical element
        ELEM2CANON[_canon] = _canon          # canonical name -> itself

REPORT = {"generated_at": None, "entities": {}, "quests": {}, "unmatched": {}}


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def dump_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def slugify_en(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unnamed"


def slugify_locale(name):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", (name or "")).strip()
    s = re.sub(r"\s+", "-", s).strip("-.")
    return s or "unnamed"


def unique(slug, used):
    base, n = slug, 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "-", (name or "")).strip().rstrip(".")

def load_lunabase():
    chars = load_json(LUNA / "characters.json")
    weapons = load_json(LUNA / "weapons.json")
    artifacts = {lang: load_json(LUNA / "artifacts" / lang / "artifacts.json")
                 for lang in LOCALES}
    return chars, weapons, artifacts


TWIN_NAME = {
    "10000005": {"en": "Aether", "ja": "空", "zh": "空"},
    "10000007": {"en": "Lumine", "ja": "蛍", "zh": "荧"},
}


def build_entity_maps(chars, weapons, artifacts):
    """-> {category: {lang: {source filename stem: {"id","display","en_name"}}}}"""
    maps = {"characters": {}, "weapons": {}, "artifacts": {}}
    for cat, idx in (("characters", chars), ("weapons", weapons)):
        for lang in LOCALES:
            key = {"en": "en_name", "ja": "name", "zh": "zh_name"}[lang]
            counts = defaultdict(int)
            for e in idx:
                counts[e.get(key) or ""] += 1
            by_name = {}
            for e in idx:
                eid = str(e["id"])
                is_variant = "-" in eid  # element variants (traveler / mannequin)
                name = e.get(key) or ""
                canon = ELEM2CANON.get(e.get("element") or "") if cat == "characters" else None
                local_elem = ELEMENT_L10N[lang].get(canon, canon) if canon else None
                if cat == "characters" and canon and eid.split("-")[0] in TWIN_NAME:
                    name = f"{TWIN_NAME[eid.split('-')[0]][lang]} ({local_elem})"
                elif is_variant and canon:
                    name = f"{name} ({local_elem})"
                elif name and counts.get(name, 0) > 1 and canon:
                    name = f"{name} ({local_elem})"
                if name in by_name:  # same name+element, keep both addressable
                    name = f"{name} [{eid}]"
                by_name[name] = {"id": eid, "display": name, "en_name": e.get("en_name")}
            maps[cat][lang] = {safe_filename(k): v for k, v in by_name.items()}
    for lang in LOCALES:
        by_name = {}
        for e in artifacts[lang]:
            name = e.get("name") or ""
            by_name[name] = {"id": str(e["id"]), "display": name,
                             "en_name": e.get("en_name")}
        maps["artifacts"][lang] = {safe_filename(k): v for k, v in by_name.items()}
    return maps

def build_entities(maps):
    """Process characters / weapons / artifacts for all locales."""
    canonical = {"characters": {}, "weapons": {}}  # id -> en summary fields
    for lang in LOCALES:
        for cat in ("characters", "weapons", "artifacts"):
            srcdir = SRC / LANG_DIR[lang] / CAT_DIR[cat][lang]
            files = sorted(p for p in srcdir.glob("*.json")) if srcdir.is_dir() else []
            used = set()
            items = []
            n_id = 0
            unmatched = []
            for p in files:
                stem = p.stem
                meta = maps[cat].get(lang, {}).get(stem)
                obj = load_json(p)
                eid = meta["id"] if meta else None
                en_name = (meta or {}).get("en_name") or obj.get("name") or obj.get("set_name")
                if lang == "en":
                    en_name = obj.get("name") or obj.get("set_name")
                obj["id"] = eid
                if eid:
                    n_id += 1
                else:
                    unmatched.append(stem)
                slug = unique(slugify_en(en_name) if eid else slugify_locale(obj.get("name")),
                              used)
                dump_json(DATA / lang / cat / f"{slug}.json", obj)
                item = {"id": eid, "slug": slug,
                        "name": obj.get("name") or obj.get("set_name"),
                        "en_name": en_name,
                        "url": f"/v1/{lang}/{cat}/{slug}.json"}
                if cat == "characters":
                    item["rarity"] = obj.get("rarity")
                    item["element"] = obj.get("element")
                    item["weapon"] = obj.get("weapon")
                elif cat == "weapons":
                    item["rarity"] = obj.get("rarity")
                    item["type"] = obj.get("type")
                    item["base_atk"] = obj.get("base_atk")
                elif cat == "artifacts":
                    item["affixes"] = len(obj.get("affixes") or [])
                items.append(item)
                if lang == "en":
                    if cat == "characters":
                        canonical[cat][eid] = {"element_en": obj.get("element"),
                                               "weapon_en": obj.get("weapon")}
                    elif cat == "weapons":
                        canonical[cat][eid] = {"type_en": obj.get("type")}
            # enrich localized items with canonical en fields + slug sharing
            if lang != "en":
                for item in items:
                    c = canonical["characters"].get(item["id"]) if item["id"] else None
                    if cat == "characters" and c:
                        item["element_en"] = c["element_en"]
                        item["weapon_en"] = c["weapon_en"]
                    if cat == "weapons":
                        c = canonical["weapons"].get(item["id"]) if item["id"] else None
                        if c:
                            item["type_en"] = c["type_en"]
            REPORT["entities"][f"{cat}/{lang}"] = {
                "total": len(files), "with_id": n_id,
            }
            if unmatched:
                REPORT["unmatched"][f"{cat}/{lang}"] = unmatched
            dump_json(DATA / lang / cat / "index.json", {
                "locale": lang, "category": cat, "count": len(items), "items": items})
    return canonical

def build_quests():
    """Process quest files with recovered wiki ids."""
    qmap = load_json(MAPS / "quest_ids.json") if (MAPS / "quest_ids.json").is_file() else {}
    for lang in LOCALES:
        for qtype in QUEST_TYPES:
            srcdir = SRC / LANG_DIR[lang] / QUEST_DIR[qtype][lang] \
                if QUEST_DIR[qtype].get(lang) else None
            if not srcdir or not srcdir.is_dir():
                REPORT["quests"][f"{qtype}/{lang}"] = {"total": 0, "with_id": 0}
                continue
            qrel = qmap.get(f"{qtype}/{lang}", {})
            used = set()
            items = []
            n_id = 0
            for dp, _dns, fns in os.walk(srcdir):
                for fn in sorted(fns):
                    if not fn.endswith(".json"):
                        continue
                    p = Path(dp) / fn
                    rel = p.relative_to(srcdir).as_posix()
                    obj = load_json(p)
                    hit = qrel.get(rel) or {}
                    eid = hit.get("id")
                    obj["id"] = eid
                    qids = hit.get("qids") or []
                    for i, q in enumerate(obj.get("quests") or []):
                        if i < len(qids) and isinstance(q, dict):
                            obj["quests"][i] = {"id": qids[i], **q}
                    if eid:
                        n_id += 1
                    parts = rel.split("/")
                    folder = parts[0] if len(parts) > 1 else ""
                    stem = "/".join(parts[1:])[:-5] if len(parts) > 1 else fn[:-5]
                    stem = re.sub(r"（q_\d+）\s*$", "", stem).strip()
                    title = (obj.get("quests") or [{}])[0].get("title") or obj.get("act_title") or stem
                    slug = unique(slugify_locale(stem) if eid or lang != "ja"
                                  else slugify_locale(stem), used)
                    dump_json(DATA / lang / "quests" / qtype / f"{slug}.json", obj)
                    items.append({
                        "id": eid, "slug": slug, "title": title,
                        "chapter": obj.get("chapter"), "act": obj.get("act"),
                        "region": obj.get("region"),
                        "url": f"/v1/{lang}/quests/{qtype}/{slug}.json",
                    })
            REPORT["quests"][f"{qtype}/{lang}"] = {"total": len(items), "with_id": n_id}
            dump_json(DATA / lang / "quests" / qtype / "index.json", {
                "locale": lang, "category": "quests", "quest_type": qtype,
                "count": len(items), "items": items})
        # quests root index per locale
        qtypes = {}
        for qtype in QUEST_TYPES:
            idx = DATA / lang / "quests" / qtype / "index.json"
            if idx.is_file():
                d = load_json(idx)
                qtypes[qtype] = {"count": d["count"],
                                 "url": f"/v1/{lang}/quests/{qtype}"}
        qtotal = sum(v["count"] for v in qtypes.values())
        dump_json(DATA / lang / "quests" / "index.json", {
            "locale": lang, "category": "quests", "count": qtotal,
            "quest_types": qtypes})

def build_indexes(now):
    counts = {}
    for lang in LOCALES:
        cats = {}
        for cat in ("characters", "weapons", "artifacts"):
            d = load_json(DATA / lang / cat / "index.json")
            cats[cat] = {"count": d["count"], "url": f"/v1/{lang}/{cat}"}
            counts[f"{cat}/{lang}"] = d["count"]
        q = load_json(DATA / lang / "quests" / "index.json")
        cats["quests"] = {"count": q["count"], "url": f"/v1/{lang}/quests"}
        counts[f"quests/{lang}"] = q["count"]
        dump_json(DATA / lang / "index.json", {"locale": lang, "categories": cats})

    data_version = now.strftime("%Y%m%dT%H%MZ")
    manifest = {
        "schema_version": 1,
        "data_version": data_version,
        "generated_at": now.isoformat(),
        "locales": list(LOCALES),
        "quest_types": list(QUEST_TYPES),
        "counts": counts,
        "endpoints": {lang: f"/v1/{lang}" for lang in LOCALES},
        "license": ("Game content and data © HoYoverse / Cognosphere. "
                    "Unofficial fan project; not affiliated with or endorsed by HoYoverse."),
    }
    dump_json(DATA / "index.json", manifest)


def main():
    now = datetime.now(timezone.utc)
    if (ROOT / "data").exists():
        shutil.rmtree(ROOT / "data")
    chars, weapons, artifacts = load_lunabase()
    maps = build_entity_maps(chars, weapons, artifacts)
    build_entities(maps)
    build_quests()
    build_indexes(now)
    REPORT["generated_at"] = now.isoformat()
    (MAPS / "build_report.json").write_text(
        json.dumps(REPORT, ensure_ascii=False, indent=1), encoding="utf-8")

    try:
        print(f"{'category':12} {'lang':4} {'total':>6} {'with_id':>8} {'rate':>5}")
        for key, v in {**REPORT["entities"], **REPORT["quests"]}.items():
            total, wid = v["total"], v["with_id"]
            rate = f"{wid * 100 // total}%" if total else "-"
            print(f"{key:12} {'':4} {total:6} {wid:8} {rate:>5}")
        print("\nwritten: data/v1")
    except Exception:
        pass  # stdout unavailable (pythonw); report is in build_report.json


if __name__ == "__main__":
    main()





# -*- coding: utf-8 -*-

import argparse
import json
import urllib.request
import zipfile
from pathlib import Path

import fetch_yatta as fy

ROOT = fy.ROOT
DATA = fy.DATA
AGD = ROOT / "_tmp" / "agd"
RAW = "https://gitlab.com/Dimbreath/AnimeGameData/-/raw/master"
ARCHIVE = "https://gitlab.com/api/v4/projects/Dimbreath%2FAnimeGameData/repository/archive.zip"
TEXTMAP = {"ja": "JP", "en": "EN", "zh": "CHS"}
FILES = [f"TextMap/TextMap{s}.json" for s in TEXTMAP.values()]
FILES += [f"TextMap/TextMap_Medium{s}.json" for s in TEXTMAP.values()]
FILES += [f"ExcelBinOutput/{name}.json" for name in (
    "DialogExcelConfigData", "NpcExcelConfigData", "CoopChapterExcelConfigData",
    "MainQuestExcelConfigData", "QuestExcelConfigData")]
FOLDERS = {"BinOutput/Coop": "BinOutput_Coop", "BinOutput/Talk/Coop": "BinOutput_Talk_Coop",
           "BinOutput/Talk/Quest": "BinOutput_Talk_Quest"}
HANGOUT_DIALOG_MIN = 190000000
HANGOUT_DIALOG_MAX = 200000000
HASH_SHIFT = 512
STEP_TITLE = "failParent"
ROMAN_ACTS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
KANJI_ACTS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}

K = {
    "talks": "NGKBJGGOPEG",
    "talk_start": "KNDKMMOMHOG",
    "nodes": "CEKCHKLHGFL",
    "node_type": "HMLLJAMHHHG",
    "node_next": "MPEMBNCPNJO",
    "options": "ICBFHNOKIDE",
    "option_dialog": "LNKEDDLBLEP",
    "dialogs": "IOEDPLCPFFB",
    "dialog_id": "GMOMCKNPBGE",
    "dialog_next": "JDAPCNPEAEH",
    "dialog_role": "DGGDDIMMIDO",
    "dialog_text": "HJJLLECCCPI",
    "excel_dialog_id": "GFLDJMJKIKE",
}


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": fy.USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=900) as res, open(tmp, "wb") as fh:
        while chunk := res.read(1 << 20):
            fh.write(chunk)
    tmp.replace(dest)
    print(f"downloaded {dest.relative_to(ROOT)} ({dest.stat().st_size:,} bytes)")


def ensure_agd():
    for rel in FILES:
        if not (AGD / rel).is_file():
            download(f"{RAW}/{rel}", AGD / rel)
    for path, name in FOLDERS.items():
        dest = AGD / name
        if dest.is_dir() and any(dest.iterdir()):
            continue
        archive = AGD / f"{name}.zip"
        if not archive.is_file():
            download(f"{ARCHIVE}?path={path}&sha=master", archive)
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if info.is_dir() or not info.filename.endswith(".json"):
                    continue
                target = (dest / Path(info.filename).name).resolve()
                if target.parent == dest.resolve():
                    target.write_bytes(z.read(info))


def check_keys(obj, keys, where):
    missing = [K[k] for k in keys if K[k] not in obj]
    if missing:
        raise SystemExit(f"{where}: field(s) {missing} not found, the obfuscated names changed, update K")


class Source:
    def __init__(self):
        self.coops = {int(p.stem[4:]): fy.load_json(p) for p in (AGD / "BinOutput_Coop").glob("Coop*.json")}
        self.talk_files = {}
        for cop in self.coops.values():
            check_keys(cop, ("talks",), "Coop file")
        hashes, dialog_ids = set(), set()
        for p in (AGD / "BinOutput_Talk_Coop").glob("*.json"):
            sub, node = p.stem.split("_")
            items = fy.load_json(p).get(K["dialogs"]) or []
            for it in items:
                check_keys(it, ("dialog_id", "dialog_next", "dialog_role", "dialog_text"), p.name)
                hashes.add(str(it[K["dialog_text"]]))
                dialog_ids.add(it[K["dialog_id"]])
            self.talk_files[(sub, node)] = items
        for cop in self.coops.values():
            for talk in cop[K["talks"]].values():
                for node in talk[K["nodes"]].values():
                    for opt in node.get(K["options"]) or []:
                        dialog_ids.add(opt[K["option_dialog"]])
        self.covered_talks = {did // 100 for did in dialog_ids}
        self.quest_talks = {}
        for p in (AGD / "BinOutput_Talk_Quest").glob("*.json"):
            if not p.stem.isdigit() or not HANGOUT_DIALOG_MIN // 100 <= int(p.stem) < HANGOUT_DIALOG_MAX // 100:
                continue
            if int(p.stem) in self.covered_talks:
                continue
            items = fy.load_json(p).get(K["dialogs"]) or []
            for it in items:
                hashes.add(str(it[K["dialog_text"]]))
                dialog_ids.add(it[K["dialog_id"]])
            self.quest_talks[int(p.stem)] = items
        self.dialogs = {}
        self.extra = {}
        for row in fy.load_json(AGD / "ExcelBinOutput" / "DialogExcelConfigData.json"):
            did = row.get(K["excel_dialog_id"])
            if not isinstance(did, int):
                continue
            if did in dialog_ids:
                self.dialogs[did] = (str(row.get("talkContentTextMapHash")), str(row.get("talkRoleNameTextMapHash")))
                hashes.update(self.dialogs[did])
            elif HANGOUT_DIALOG_MIN <= did < HANGOUT_DIALOG_MAX and did // 100 not in self.covered_talks and did // 100 not in self.quest_talks:
                self.extra.setdefault(did // 100, {})[did] = row
                hashes.update((str(row.get("talkContentTextMapHash")), str(row.get("talkRoleNameTextMapHash"))))
        self.npcs = {}
        for row in fy.load_json(AGD / "ExcelBinOutput" / "NpcExcelConfigData.json"):
            self.npcs[str(row["id"])] = str(row.get("nameTextMapHash"))
        hashes.update(self.npcs.values())
        self.chapters = {r["id"]: r for r in fy.load_json(AGD / "ExcelBinOutput" / "CoopChapterExcelConfigData.json") if r["id"] in self.coops}
        self.mains = {r["id"]: r for r in fy.load_json(AGD / "ExcelBinOutput" / "MainQuestExcelConfigData.json") if r.get("chapterId") in self.coops}
        self.steps = {}
        for r in fy.load_json(AGD / "ExcelBinOutput" / "QuestExcelConfigData.json"):
            if r.get("mainId") in self.mains:
                self.steps.setdefault(r["mainId"], []).append(r)
        for r in self.chapters.values():
            hashes.update((str(r.get("chapterNameTextMapHash")), str(r.get("coopPageTitleTextMapHash"))))
        for r in self.mains.values():
            hashes.update((str(r.get("titleTextMapHash")), str(r.get("descTextMapHash"))))
        for rows in self.steps.values():
            for r in rows:
                h = r.get(STEP_TITLE)
                if isinstance(h, int):
                    hashes.update((str(h), str(h ^ HASH_SHIFT)))
        self.text = {}
        for lang, suffix in TEXTMAP.items():
            tm = {}
            for name in (f"TextMap{suffix}.json", f"TextMap_Medium{suffix}.json"):
                for h, t in fy.load_json(AGD / "TextMap" / name).items():
                    if h in hashes:
                        tm[h] = t
            self.text[lang] = tm

    def t(self, lang, h):
        return fy.clean(self.text[lang].get(str(h))) or None

    def t_shifted(self, lang, h):
        if not isinstance(h, int):
            return None
        return self.t(lang, h) or self.t(lang, h ^ HASH_SHIFT)

    def talk(self, lang, conv, sub, node_id):
        return self.items_lines(lang, conv, self.talk_files.get((str(sub), str(node_id)), []))

    def items_lines(self, lang, conv, items):
        items = {str(it[K["dialog_id"]]): it for it in items}
        if not items:
            return []
        referenced = {str(n) for it in items.values() for n in it.get(K["dialog_next"]) or []}
        start = next((k for k in items if k not in referenced), next(iter(items)))

        def succ(k):
            return [str(n) for n in items[k].get(K["dialog_next"]) or [] if str(n) in items]

        out = []
        for k in fy.linear_order(start, items, succ):
            it = items[k]
            text = self.t(lang, it[K["dialog_text"]])
            excel = self.dialogs.get(it[K["dialog_id"]])
            if not text and excel:
                text = self.t(lang, excel[0])
            if not text:
                continue
            role = it[K["dialog_role"]]
            if role.get("_type") == "TALK_ROLE_NPC":
                name = (excel and self.t(lang, excel[1])) or self.t(lang, self.npcs.get(str(role.get("_id")))) or "？？？"
                out.append(conv.line(name, text))
            else:
                out.append({"sit": text})
        return out

    def subquest(self, lang, conv, sub, talk):
        check_keys(talk, ("talk_start", "nodes"), f"talk {sub}")
        nodes = {str(k): v for k, v in talk[K["nodes"]].items()}

        def succ(k):
            return [str(n) for n in nodes[k].get(K["node_next"]) or [] if str(n) in nodes]

        out = []
        for k in fy.linear_order(str(talk[K["talk_start"]]), nodes, succ):
            node = nodes[k]
            kind = node.get(K["node_type"])
            if kind == "COOP_NODE_SELECT":
                for opt in node.get(K["options"]) or []:
                    excel = self.dialogs.get(opt[K["option_dialog"]])
                    text = excel and self.t(lang, excel[0])
                    if text:
                        out.append({"sit": text})
            elif kind == "COOP_NODE_TALK":
                out += self.talk(lang, conv, sub, k)
        return out

    def agd_detail(self, lang, cid):
        ch = self.chapters.get(cid)
        if not ch:
            return None
        page = self.t(lang, ch.get("coopPageTitleTextMapHash"))
        n = ch.get("chapterSortId") or 1
        if lang == "en":
            num = f"{page}: Act {ROMAN_ACTS.get(n, n)}"
        elif lang == "zh":
            num = f"{page} 第{KANJI_ACTS.get(n, n)}幕"
        else:
            num = f"{page} 第{n}幕"
        story = {}
        for mid in sorted(m for m, r in self.mains.items() if r["chapterId"] == cid):
            r = self.mains[mid]
            if not all(self.t(lg, r.get("titleTextMapHash")) for lg in TEXTMAP):
                continue
            steps = sorted(self.steps.get(mid, []), key=lambda s: (s.get("order") or 0, s["subId"]))
            story[str(len(story))] = {
                "id": mid,
                "info": {"title": self.t(lang, r.get("titleTextMapHash")), "description": self.t(lang, r.get("descTextMapHash"))},
                "story": {str(j): {"id": s["subId"], "title": self.t_shifted(lang, s.get(STEP_TITLE))} for j, s in enumerate(steps)},
            }
        info = {"id": cid, "type": "hq", "chapterNum": num, "chapterTitle": self.t(lang, ch.get("chapterNameTextMapHash")),
                "route": self.t("en", ch.get("chapterNameTextMapHash"))}
        return {"info": info, "storyList": story}

    def extra_talk(self, lang, conv, talk_id):
        if talk_id in self.quest_talks:
            return self.items_lines(lang, conv, self.quest_talks[talk_id])
        rows = {str(k): v for k, v in self.extra.get(talk_id, {}).items()}
        referenced = {str(n) for r in rows.values() for n in r.get("nextDialogs") or []}
        start = next((k for k in sorted(rows, key=int) if k not in referenced), min(rows, key=int))

        def succ(k):
            return [str(n) for n in rows[k].get("nextDialogs") or [] if str(n) in rows]

        out = []
        for k in fy.linear_order(start, rows, succ):
            row = rows[k]
            text = self.t(lang, row.get("talkContentTextMapHash"))
            if not text:
                continue
            role = row.get("talkRole") or {}
            if role.get("type") == "TALK_ROLE_NPC":
                name = self.t(lang, row.get("talkRoleNameTextMapHash")) or self.t(lang, self.npcs.get(str(role.get("id")))) or "？？？"
                out.append(conv.line(name, text))
            else:
                out.append({"sit": text})
        return out

    def chapter(self, lang, cid, detail):
        talks = {str(k): v for k, v in self.coops[cid][K["talks"]].items()}
        conv = fy.Dialogue(lang)
        mqs = fy.ordered(detail.get("storyList"))
        main_ids = sorted(mq["id"] for mq in mqs)
        units = {mid: [] for mid in main_ids}

        def owner(n):
            below = [m for m in main_ids if m <= n // 100]
            return below[-1] if below else None

        for k in talks:
            if owner(int(k)) is not None:
                units[owner(int(k))].append((int(k), "coop", k))
        for tid in [*self.quest_talks, *self.extra]:
            if tid // 100 in units:
                units[tid // 100].append((tid, "talk", tid))
        quests = []
        for mq in mqs:
            titles = {s["id"]: fy.clean(s.get("title")) for s in fy.ordered(mq.get("story"))}
            dialogue = []
            for uid, kind, key in sorted(units[mq["id"]]):
                lines = self.subquest(lang, conv, key, talks[key]) if kind == "coop" else self.extra_talk(lang, conv, key)
                if lines and titles.get(uid):
                    dialogue.append({"section": titles[uid]})
                dialogue += lines
            info = mq.get("info") or {}
            q = {"id": f"q-{mq['id']}", "title": fy.clean(info.get("title")), "dialogue": dialogue}
            if info.get("description"):
                q["description"] = fy.clean(info["description"])
            if not dialogue:
                q["note"] = fy.NO_DIALOGUE[lang]
            quests.append(q)
        orphans = sorted((k for k in talks if owner(int(k)) is None), key=int)
        obj = fy.chapter_fields(detail["info"], lang, "hangout")
        obj["quests"] = quests
        obj["speakers"] = conv.speakers
        obj["id"] = f"ch-{cid}"
        return obj, orphans, main_ids


def existing_hangouts():
    out = {lang: [] for lang in fy.LOCALES}
    for lang in fy.LOCALES:
        for p in (DATA / lang / "quests" / "hangout").glob("*.json"):
            if p.name != "index.json":
                obj = fy.load_json(p)
                out[lang].append((p, obj))
    return out


def target_path(lang, obj, existing, taken):
    for p, old in existing[lang]:
        if old.get("id") == obj["id"]:
            return p, old
    for p, old in existing[lang]:
        if not old.get("id") and old.get("act_title") == obj["act_title"]:
            return p, old
    base = fy.slugify(obj["act_title"]) if lang == "en" else fy.FS_UNSAFE_RE.sub("_", obj["act_title"])
    slug, n = base, 1
    while (DATA / lang / "quests" / "hangout" / f"{slug}.json").exists() or (lang, slug) in taken:
        n += 1
        slug = f"{base}-{n}"
    taken.add((lang, slug))
    return DATA / lang / "quests" / "hangout" / f"{slug}.json", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    ensure_agd()
    src = Source()
    existing = existing_hangouts()
    taken = set()
    total = 0
    for cid in sorted(src.coops):
        for lang in fy.LOCALES:
            detail = fy.fetch(lang, f"quest/{cid}") or src.agd_detail(lang, cid)
            if not detail:
                print(f"{cid} {lang}: no chapter info, skipped")
                continue
            obj, orphans, _ = src.chapter(lang, cid, detail)
            path, old = target_path(lang, obj, existing, taken)
            lines = sum(len(q["dialogue"]) for q in obj["quests"])
            old_lines = sum(len(q["dialogue"]) for q in old["quests"]) if old else None
            state = "new" if old is None else ("replace" if old.get("id") else "replace (adds id)")
            print(f"{cid} {lang} {state:18} {path.relative_to(ROOT)}  lines {old_lines if old_lines is not None else '-'} -> {lines}"
                  + (f"  unmatched talks {orphans}" if orphans else ""))
            if args.write:
                fy.dump_json(path, obj)
            total += 1
    print(f"\n{total} file(s) {'written' if args.write else 'to write'}")
    if not args.write:
        print("dry run: pass --write to save files, then run scripts/build_index.py")


if __name__ == "__main__":
    main()

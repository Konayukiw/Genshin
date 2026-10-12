# -*- coding: utf-8 -*-

import argparse
import io
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if sys.stdout else sys.stdout

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "v1"
CACHE = ROOT / "_tmp" / "yatta"
API = "https://gi.yatta.moe/api/v2"
USER_AGENT = "GenshinDatabaseAPI/1.0 (+https://genshin.konayuki.xyz)"
DELAY = 0.6

LOCALES = {"ja": "jp", "en": "en", "zh": "chs"}
TYPES = {"aq": "archon", "lq": "story", "hq": "hangout", "eq": "event", "wq": "world"}
CHAPTER_TYPES = ("aq", "lq", "hq")
TRAVELER = {"ja": "旅人", "en": "Traveler", "zh": "旅行者"}
NO_DIALOGUE = {
    "ja": "対話行なし (戦闘・探索のみの任務の可能性)",
    "en": "No dialogue lines (battle/exploration-only quest)",
    "zh": "该任务没有对话内容。",
}
KANJI_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}
TEST_RE = re.compile(r"\(test\)|^破棄$", re.I)
COLOR_RE = re.compile(r"</?color(?:=[^>]*)?>")
FS_UNSAFE_RE = re.compile(r'[\\/:*?"<>|]')

_last_request = 0.0


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def dump_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def fetch(lang, path, refresh=False):
    ylang = LOCALES[lang]
    cache = CACHE / ylang / (path.replace("/", "_") + ".json")
    if cache.is_file() and not refresh:
        body = load_json(cache)
    else:
        global _last_request
        for attempt in range(4):
            wait = DELAY - (time.monotonic() - _last_request)
            if wait > 0:
                time.sleep(wait)
            _last_request = time.monotonic()
            req = urllib.request.Request(f"{API}/{ylang}/{path}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as res:
                    body = json.loads(res.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    body = {"code": 404}
                    break
                if attempt == 3:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise
            time.sleep(2 ** attempt * 2)
        dump_json(cache, body)
    if body.get("code") == 404 or body.get("response") not in (None, 200):
        return None
    return body.get("data")


def clean(text):
    if not isinstance(text, str):
        return text
    text = COLOR_RE.sub("", text).replace("$HIDDEN", "")
    return text[1:] if text.startswith("#") else text


def kanji_number(s):
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    for ch in s:
        if ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch in KANJI_DIGITS:
            cur = KANJI_DIGITS[ch]
        else:
            return None
    return total + cur


def roman_number(s):
    if not s or any(ch not in ROMAN for ch in s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN[a]
        total += -v if b in ROMAN and ROMAN[b] > v else v
    return total


def split_chapter_num(num, lang, qtype):
    num = (num or "").strip()
    if not num:
        return None, None
    if lang == "en":
        m = re.match(r"^(.*?)\s*[:\-]\s*(Act\s+(\S+))$", num)
        if not m:
            return num, None
        chapter, act, n = m.group(1), m.group(2), m.group(3)
        if qtype != "archon" and roman_number(n):
            act = f"Act {roman_number(n)}"
        return chapter, act
    m = re.match(r"^(.*?)\s*(第([〇零一二三四五六七八九十\d]+)幕)$", num)
    if not m:
        return num, None
    chapter, act, n = m.group(1).strip(), m.group(2), m.group(3)
    if lang == "ja":
        act = f"第{kanji_number(n)}幕" if kanji_number(n) is not None else act
        chapter = re.sub(r"第([〇零一二三四五六七八九十]+)章", lambda c: f"第{kanji_number(c.group(1))}章", chapter)
    return chapter or None, act


def slugify(title):
    s = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def ordered(d):
    if isinstance(d, dict):
        return [d[k] for k in sorted(d, key=lambda k: int(k) if str(k).lstrip("-").isdigit() else 0)]
    return list(d or [])


def linear_order(start, nodes, succ):
    reach, back, state = [], set(), {}
    if start in nodes:
        stack = [(start, iter(succ(start)))]
        state[start] = 1
        reach.append(start)
        while stack:
            nid, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[nid] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                back.add((nid, nxt))
            elif nxt not in state:
                state[nxt] = 1
                reach.append(nxt)
                stack.append((nxt, iter(succ(nxt))))
    indeg = {n: 0 for n in reach}
    for n in reach:
        for m in succ(n):
            if (n, m) not in back:
                indeg[m] += 1
    order, stack, seen = [], [start] if start in nodes else [], set()
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        order.append(n)
        for m in reversed([m for m in succ(n) if (n, m) not in back]):
            indeg[m] -= 1
            if indeg[m] == 0:
                stack.append(m)
    order += [n for n in reach if n not in seen]
    rest = sorted((n for n in nodes if n not in state), key=lambda k: (not str(k).isdigit(), int(k) if str(k).isdigit() else 0, str(k)))
    return order + rest


class Dialogue:
    def __init__(self, lang):
        self.lang = lang
        self.speakers = []

    def speaker(self, role):
        role = clean(role)
        if role not in self.speakers:
            self.speakers.append(role)
        return self.speakers.index(role)

    def is_traveler(self, role):
        return role in (TRAVELER[self.lang], "{NICKNAME}")

    def line(self, role, text):
        text = clean(text)
        if text is None or text == "":
            return None
        if not role or self.is_traveler(role):
            return {"sit": text}
        return {"s": self.speaker(role), "t": text}

    def graph(self, task):
        items = {str(k): v for k, v in (task.get("items") or {}).items()}

        def succ(nid):
            out = []
            for t in items[nid].get("text") or []:
                n = str(t.get("next"))
                if n in items and n not in out:
                    out.append(n)
            return out

        return items, linear_order(str(task.get("initDialog")), items, succ)

    def task(self, task):
        items, order = self.graph(task)
        out, options = [], {}
        for nid in order:
            node = items[nid]
            texts = [t for t in node.get("text") or [] if isinstance(t, dict)]
            if node.get("type") == "MultiDialog":
                for t in texts:
                    line = self.line(None, t.get("text"))
                    if line:
                        out.append(line)
                        options[str(t.get("next"))] = clean(t.get("text"))
                continue
            for t in texts:
                if self.is_traveler(node.get("role")) and options.get(nid) == clean(t.get("text")):
                    continue
                line = self.line(node.get("role"), t.get("text"))
                if line:
                    out.append(line)
        return out

    def step(self, step):
        lines = []
        for task in step.get("taskData") or []:
            lines += self.task(task)
        for narr in step.get("narratorData") or []:
            for it in narr.get("items") or []:
                line = self.line(it.get("role"), it.get("text"))
                if line:
                    lines.append(line)
        if lines and step.get("title"):
            lines.insert(0, {"section": clean(step["title"])})
        return lines

    def quest(self, mq, with_id):
        dialogue = []
        for step in ordered(mq.get("story")):
            dialogue += self.step(step)
        info = mq.get("info") or {}
        q = {}
        if with_id:
            q["id"] = f"q-{mq['id']}"
        q["title"] = clean(info.get("title"))
        q["dialogue"] = dialogue
        if info.get("description"):
            q["description"] = clean(info["description"])
        if not dialogue:
            q["note"] = NO_DIALOGUE[self.lang]
        return q


def chapter_fields(info, lang, qtype, sibling=None):
    chapter, act = split_chapter_num(info.get("chapterNum"), lang, qtype)
    title = clean(info.get("chapterTitle"))
    if qtype == "archon":
        return {"chapter": chapter or title, "chapter_title": (sibling or {}).get("chapter_title"),
                "act": act, "act_title": title, "region": clean(info.get("chapterImageTitle")) or None}
    if qtype in ("story", "hangout"):
        return {"chapter": chapter or title, "chapter_title": title, "act": act, "act_title": title, "region": None}
    return {"chapter": clean(info.get("chapterNum")) or title, "chapter_title": None, "act": None,
            "act_title": title, "region": None}


def build_chapter_file(detail, lang, qtype, sibling=None):
    conv = Dialogue(lang)
    quests = [conv.quest(mq, True) for mq in ordered(detail.get("storyList"))]
    obj = chapter_fields(detail["info"], lang, qtype, sibling)
    obj["quests"] = quests
    obj["speakers"] = conv.speakers
    obj["id"] = f"ch-{detail['info']['id']}"
    return obj


def build_main_quest_file(detail, mq, lang, qtype):
    conv = Dialogue(lang)
    quest = conv.quest(mq, False)
    info = detail["info"]
    if qtype == "world":
        chapter = clean(info.get("chapterTitle")) or quest["title"]
    else:
        chapter = clean(info.get("chapterNum")) or clean(info.get("chapterTitle")) or quest["title"]
    obj = {"chapter": chapter, "chapter_title": None, "act": None, "act_title": quest["title"], "region": None}
    obj["quests"] = [quest]
    obj["speakers"] = conv.speakers
    obj["id"] = f"q-{mq['id']}"
    return obj


class Local:
    def __init__(self):
        self.files = {}
        self.ids = {lang: set() for lang in LOCALES}
        self.untitled = {lang: set() for lang in LOCALES}
        self.slugs = {}
        self.by_id = {}
        for lang in LOCALES:
            for p in (DATA / lang / "quests").glob("*/*.json"):
                if p.name == "index.json":
                    continue
                qtype = p.parent.name
                obj = load_json(p)
                eid = obj.get("id")
                self.slugs.setdefault((lang, qtype), {})[p.stem] = eid
                if eid:
                    self.ids[lang].add(eid)
                    self.by_id[(lang, eid)] = (qtype, p.stem, obj)
                else:
                    self.untitled[lang].add(((obj.get("quests") or [{}])[0].get("title") or obj.get("act_title")))
                for q in obj.get("quests") or []:
                    if q.get("id"):
                        self.ids[lang].add(q["id"])

    def has(self, lang, eid, title=None):
        return eid in self.ids[lang] or (title is not None and title in self.untitled[lang])

    def sibling(self, lang, qtype, chapter_prefix):
        for (l, eid), (qt, slug, obj) in self.by_id.items():
            if l == lang and qt == qtype and obj.get("chapter") == chapter_prefix:
                return obj
        return None

    def pick_slug(self, base, qtype, eid, langs):
        n = 1
        while True:
            slug = base if n == 1 else f"{base}-{n}"
            if all(self.slugs.get((lang, qtype), {}).get(slug) in (None, eid) for lang in langs):
                for lang in langs:
                    self.slugs.setdefault((lang, qtype), {})[slug] = eid
                return slug
            n += 1


def hangout_ids(local):
    ids = set()
    for lang in LOCALES:
        for (l, eid), (qt, _, _) in local.by_id.items():
            if l == lang and qt == "hangout" and eid.startswith("ch-"):
                ids.add(int(eid[3:]))
    found = set(ids)
    for base in sorted({i // 100 for i in ids}):
        act = 1
        while act < 10:
            cid = base * 100 + act
            if cid not in found and fetch("ja", f"quest/{cid}") is None:
                break
            found.add(cid)
            act += 1
    return sorted(found)


def plan(local, ytypes):
    lists = {lang: (fetch(lang, "quest") or {}).get("items", {}) for lang in LOCALES}
    jobs = []
    entries = [(k, v["type"]) for k, v in lists["ja"].items() if v["type"] in ytypes]
    if "hq" in ytypes:
        entries += [(str(i), "hq") for i in hangout_ids(local)]
    for key, ytype in entries:
        qtype = TYPES[ytype]
        if ytype in CHAPTER_TYPES:
            eid = f"ch-{key}"
            missing = [lang for lang in LOCALES if not local.has(lang, eid)]
            if missing:
                jobs.append({"kind": "chapter", "key": key, "ytype": ytype, "qtype": qtype, "eid": eid, "langs": missing})
            continue
        info = lists["ja"][key]
        if (info.get("chapterCount") or 1) == 1 and all(local.has(lang, f"q-{key}") for lang in LOCALES):
            continue
        detail = fetch("ja", f"quest/{key}")
        if not detail:
            print(f"warning: no detail for {ytype} {key}")
            continue
        for mq in ordered(detail.get("storyList")):
            eid = f"q-{mq['id']}"
            ja_title = clean((mq.get("info") or {}).get("title"))
            missing = [lang for lang in LOCALES if not local.has(lang, eid, ja_title if lang == "ja" else None)]
            if missing:
                jobs.append({"kind": "quest", "key": key, "mq": mq["id"], "ytype": ytype, "qtype": qtype, "eid": eid, "langs": missing})
    return lists, jobs


def build(job, d, lang, local):
    qtype = job["qtype"]
    if job["kind"] == "chapter":
        chapter, _ = split_chapter_num(d["info"].get("chapterNum"), lang, qtype)
        return build_chapter_file(d, lang, qtype, local.sibling(lang, qtype, chapter) if qtype == "archon" else None)
    mq = next((m for m in ordered(d.get("storyList")) if m["id"] == job["mq"]), None)
    return build_main_quest_file(d, mq, lang, qtype) if mq else None


def skip_reason(objs):
    titles = [q["title"] for obj in objs.values() for q in obj["quests"]]
    titles += [obj["act_title"] for obj in objs.values()]
    if not objs or any(not t for t in titles):
        return "empty title"
    if any(TEST_RE.search(t) for t in titles):
        return "test/discarded quest"
    if not any(q["dialogue"] for obj in objs.values() for q in obj["quests"]):
        return "no dialogue in any locale"
    return None


def run_job(job, lists, local, write):
    qtype, eid = job["qtype"], job["eid"]
    details = {lang: fetch(lang, f"quest/{job['key']}") for lang in LOCALES}
    objs = {lang: obj for lang, d in details.items() if d and (obj := build(job, d, lang, local))}
    reason = skip_reason(objs)
    if reason:
        return [("-", None, f"skipped: {reason}")]
    en = details.get("en")
    if job["kind"] == "chapter":
        en_title = (en or {}).get("info", {}).get("route") or (en or {}).get("info", {}).get("chapterTitle")
    else:
        en_title = objs["en"]["quests"][0]["title"] if "en" in objs else None
    results = []
    slug_shared = None
    existing = [local.by_id[(lang, eid)][:2] for lang in LOCALES if (lang, eid) in local.by_id]
    if existing:
        qtype = existing[0][0]
    if qtype != "hangout":
        if existing and all(local.slugs.get((lang, qtype), {}).get(existing[0][1]) in (None, eid) for lang in job["langs"]):
            slug_shared = local.pick_slug(existing[0][1], qtype, eid, job["langs"])
        else:
            base = slugify(en_title) or str(job.get("mq") or job["key"])
            slug_shared = local.pick_slug(base, qtype, eid, job["langs"])
    for lang in job["langs"]:
        obj = objs.get(lang)
        if not obj:
            results.append((lang, None, "no detail"))
            continue
        if qtype == "hangout":
            if lang == "en":
                slug = local.pick_slug(slugify(en_title) or job["key"], qtype, eid, [lang])
            else:
                slug = local.pick_slug(FS_UNSAFE_RE.sub("_", obj["act_title"] or job["key"]), qtype, eid, [lang])
        else:
            slug = slug_shared
        path = DATA / lang / "quests" / qtype / f"{slug}.json"
        if write:
            dump_json(path, obj)
        lines = sum(len(q["dialogue"]) for q in obj["quests"])
        results.append((lang, path, f"{len(obj['quests'])} quest(s), {lines} lines"))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--refresh-lists", action="store_true")
    ap.add_argument("--types", default="aq,lq,eq,wq")
    args = ap.parse_args()
    if args.refresh_lists:
        for lang in LOCALES:
            fetch(lang, "quest", refresh=True)
    local = Local()
    lists, jobs = plan(local, set(args.types.split(",")))
    print(f"{len(jobs)} missing unit(s)")
    written, skipped = 0, 0
    for job in jobs:
        info = lists["ja"].get(job["key"]) or {}
        label = f"{job['ytype']} {job['key']}" + (f"/{job['mq']}" if job.get("mq") else "")
        print(f"- {label:16} {job['eid']:12} langs={','.join(job['langs'])}  {info.get('chapterNum') or ''} {info.get('chapterTitle') or ''}")
        for lang, path, msg in run_job(job, lists, local, args.write):
            rel = path.relative_to(ROOT) if path else "-"
            print(f"    {lang}: {rel}  ({msg})")
            written += path is not None
            skipped += msg.startswith("skipped")
    print(f"\n{written} file(s) {'written' if args.write else 'to write'}, {skipped} unit(s) skipped")
    if not args.write:
        print("\ndry run: pass --write to save files, then run scripts/build_index.py")


if __name__ == "__main__":
    main()

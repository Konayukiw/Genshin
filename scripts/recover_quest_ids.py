# -*- coding: utf-8 -*-
"""Recover Honey Hunter wiki numeric IDs for quest files.

Reads the raw scrape data under _tmp/ (not committed) and the normalized
quest JSONs under source/<Lang>/, then emits scripts/maps/quest_ids.json.

Quest files without a recoverable id get {"id": null}. The map is committed
to git so that data/ can be rebuilt even after _tmp/ is deleted.

ID scheme:
  q-<n>      quest-level page id (world / event / hangout zh)
  ch-<n>     chapter-level id (story chapters, hangout ja, archon chapters)
  ch-<n>-<k> k-th act file inside a chapter (story / archon multi-act)

Entries may carry "qids" (list of q-<n>) mapping the quests[] entries of a
chapter/act file to their quest-level page ids (zh story, ja archon).
"""
import html as htmllib
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if sys.stdout else sys.stdout

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source"
TMP = ROOT / "_tmp"
MAPS_OUT = ROOT / "scripts" / "maps" / "quest_ids.json"

SUFFIX_RE = re.compile(r"\s*\|?\s*Genshin\s*Impact\s*Database\s*Wiki.*$", re.I)
Q_SUFFIX_RE = re.compile(r"（q_(\d+)）\s*$")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}
KAN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

QUEST_DIRS = {
    "en": {"archon": "Archon Quests", "story": "Story Quests",
           "world": "World Quests", "event": "Event Quests"},
    "ja": {"archon": "魔神任務", "story": "伝説任務",
           "world": "世界任務", "event": "イベント任務", "hangout": "デート任務"},
    "zh": {"archon": "魔神任务", "story": "传说任务",
           "world": "世界任务", "event": "活动任务", "hangout": "邀约任务"},
}


def clean_marker(t):
    return (t or "").replace("$HIDDEN", "").replace("$UNRELEASED", "").replace("$#", "").strip()


def norm(t):
    """Normalize a title/series for comparison."""
    t = clean_marker(SUFFIX_RE.sub("", t or ""))
    t = t.replace("：", ":").replace("_", " ")
    return re.sub(r"\s+", " ", t).strip().casefold()


def meta_from_tds(tds):
    m = {}
    for i, cell in enumerate(tds or []):
        c = (cell or "").strip()
        if c in ("Name", "Type", "Series", "Description", "Next", "Previous",
                 "Required AR", "Involved NPC"):
            if i + 1 < len(tds):
                v = (tds[i + 1] or "").strip()
                if c not in m and v and not v.startswith("."):
                    m[c] = v
    for k in list(m):
        if m[k] in ("Rarity", "Family", "Amount", "Icon", "Name"):
            del m[k]
    return m


def series_from_tds(meta):
    sv = meta.get("Series", "")
    if sv and sv.lower() != "n/a":
        s = clean_marker(sv).split(":")[0].strip()
        if s:
            return s
    return None


def load_tds_qpages(qdir):
    """tds+scripts format quest pages -> {slug: (title, meta)}"""
    out = {}
    if not qdir.is_dir():
        return out
    for fn in sorted(os.listdir(qdir)):
        if not fn.endswith(".json"):
            continue
        try:
            q = json.loads((qdir / fn).read_text(encoding="utf-8"))
        except Exception:
            continue
        title = clean_marker(SUFFIX_RE.sub("", q.get("title") or ""))
        meta = meta_from_tds(q.get("tds"))
        name = clean_marker(meta.get("Name", "") or "")
        if not title:
            title = name
        out[fn[:-5]] = (title, meta)
    return out

def act_ordinal(act_field, stem):
    """Best-effort ordinal for act files inside one chapter."""
    a = act_field or ""
    m = re.search(r"Act\s+([IVX]+)", a, re.I)
    if m and m.group(1).upper() in ROMAN:
        return ROMAN[m.group(1).upper()]
    m = re.search(r"第([一二三四五六七八九十百0-9]+)幕", a)
    if m:
        tok = m.group(1)
        if tok.isdigit():
            return int(tok)
        total = cur = 0
        ok = True
        for ch in tok:
            if ch in KAN:
                cur = KAN[ch]
            elif ch == "十":
                total += (cur or 1) * 10
                cur = 0
            elif ch == "百":
                total += (cur or 1) * 100
                cur = 0
            else:
                ok = False
                break
        if ok:
            return total + cur
    return None


def walk_quest_files(catdir):
    """-> {(folder, stem): {"rel": str, "json": dict}}"""
    files = {}
    if not catdir.is_dir():
        return files
    for dp, _dns, fns in os.walk(catdir):
        for fn in fns:
            if not fn.endswith(".json"):
                continue
            p = Path(dp) / fn
            rel = p.relative_to(catdir).as_posix()
            parts = rel.split("/")
            folder = parts[0] if len(parts) > 1 else ""
            stem = "/".join(parts[1:])[:-5] if len(parts) > 1 else fn[:-5]
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            files[(folder, stem)] = {"rel": rel, "json": data}
    return files


def chapter_page_title(path):
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    m = re.search(r"<title>(.*?)</title>", txt, re.S)
    if not m:
        return None
    return clean_marker(SUFFIX_RE.sub("", htmllib.unescape(m.group(1)).strip()))


def ch_json_title(path):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    t = d.get("title") or d.get("name")
    return clean_marker(SUFFIX_RE.sub("", t or "")) if t else None

def wiki_map_eq(lang):
    """html_eq_<lang>: q -> chapter via ch_index.json seriesRaw."""
    base = TMP / f"html_eq_{lang}"
    idx = base / "ch_index.json"
    if not idx.is_file():
        return {}
    ch_idx = json.loads(idx.read_text(encoding="utf-8"))
    q2ch = {}
    for v in ch_idx.values():
        for q in v.get("qs") or []:
            q2ch[q] = v
    out = {}
    for slug, (title, _meta) in load_tds_qpages(base / "q").items():
        chv = q2ch.get(slug) or {}
        series = clean_marker(chv.get("seriesRaw", "")).strip()
        if not series or series.lower() == "n/a":
            series = clean_marker(chv.get("name", "")).strip()
        out[slug] = (series, title)
    return out


def wiki_map_wq(lang):
    if lang == "en":
        return {slug: (series_from_tds(meta) or title, title)
                for slug, (title, meta) in load_tds_qpages(TMP / "html" / "q").items()}
    if lang == "zh":
        out = {}
        for qdir in (TMP / "html_wq_zh" / "q", TMP / "html_wq2_zh" / "html" / "q"):
            for slug, (title, meta) in load_tds_qpages(qdir).items():
                out[slug] = (series_from_tds(meta) or title, title)
        return out
    if lang == "ja":
        out = {}
        for fn in ("wqja_covered.json", "wqja_new.json", "wqja_p01.json",
                   "wqja_p02.json", "wqja_all.json"):
            p = TMP / "_scrape" / "enum_wq" / fn
            if not p.is_file():
                continue
            try:
                entries = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for e in entries:
                if not isinstance(e, dict):
                    continue
                qid, name = str(e.get("id")), clean_marker(e.get("name") or "")
                if qid and name and qid not in out:
                    out[f"q_{qid}"] = (None, name)
        return out
    return {}


def wiki_chapters_lq(lang):
    """-> {cid: {"titles": set, "qtitles": set, "qids": [str]}}"""
    chapters = {}

    def entry(cid):
        return chapters.setdefault(str(cid), {"titles": set(), "qtitles": set(), "qids": []})

    if lang in ("en", "ja"):
        base = TMP / "_scrape" / ("raw_lq_en" if lang == "en" else "raw_lq_ja")
        p = base / "_ch_index.json"
        if p.is_file():
            for cid, v in json.loads(p.read_text(encoding="utf-8")).items():
                e = entry(cid)
                if v.get("title"):
                    e["titles"].add(v["title"])
                e["qids"].extend(str(q) for q in v.get("qids") or [])
    if lang in ("ja", "zh"):
        for p in (TMP / "_scrape" / "enum_lq").glob("ch_*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if d.get("ch"):
                e = entry(d["ch"])
                if lang == "ja" and d.get("title"):
                    e["titles"].add(d["title"])
                e["qids"].extend(str(q) for q in d.get("qids") or [])
    # localized quest-page titles -> cid (needed for ja where _ch_index
    # titles are English, and for act-level files in multi-act chapters)
    qdir_html = {"en": TMP / "_scrape" / "raw_lq_en_q",
                 "ja": TMP / "_scrape" / "raw_lq_ja_q"}.get(lang)
    qdir_json = TMP / "html_lq_zh" / "q" if lang == "zh" else None
    for cid, e in chapters.items():
        for qid in e["qids"]:
            t = None
            if qdir_html:
                t = chapter_page_title(qdir_html / f"q_{qid}.html")
            elif qdir_json:
                t = ch_json_title(qdir_json / f"q_{qid}.json")
            if t:
                e["qtitles"].add(t)
    return chapters


def _match_by_title(files, title2cid, allow_ordinal=True):
    """title2cid: normalized title -> [cid]. Returns {(folder,stem): {...}}"""
    by_cid = defaultdict(list)
    hit = {}
    for key, info in files.items():
        data = info["json"]
        stem = key[1].split("/")[-1]
        cids = set()
        for t in (stem, data.get("act_title") or "",
                  (data.get("quests") or [{}])[0].get("title") or ""):
            for cid in title2cid.get(norm(t), []):
                cids.add(cid)
        if len(cids) == 1:
            cid = next(iter(cids))
            by_cid[cid].append(key)
            hit[key] = cid
    result = {}
    for cid, keys in by_cid.items():
        if len(keys) == 1:
            result[keys[0]] = {"id": f"ch-{cid}", "via": "chapter-title",
                               "rel": files[keys[0]]["rel"]}
        elif allow_ordinal:
            ordered = sorted(keys, key=lambda k: (act_ordinal(files[k]["json"].get("act"),
                                                               k[1]) or 10 ** 6, k[1]))
            for i, k in enumerate(ordered):
                result[k] = {"id": f"ch-{cid}-{i + 1}", "via": "chapter-title+ordinal",
                             "rel": files[k]["rel"]}
    return result


def _match_story_zh(files):
    """zh story: html_lq_zh/ch_index.json maps each ch_ page (1:1 with an act
    file) to its q_ pages (1:1 with quests[] entries). File id = ch-<cid>;
    per-quest ids = q-<qid> emitted as "qids" in page order."""
    base = TMP / "html_lq_zh"
    idx_p = base / "ch_index.json"
    if not idx_p.is_file():
        return {}
    ch_idx = json.loads(idx_p.read_text(encoding="utf-8"))
    ch_series = {}
    list_p = base / "ch_list.json"
    if list_p.is_file():
        for row in json.loads(list_p.read_text(encoding="utf-8")):
            ch_series[row.get("slug") or ""] = clean_marker(row.get("series") or "")

    qmeta = {}  # qid -> (clean title, has_dialog, meta)
    qdir = base / "q"
    if qdir.is_dir():
        for fn in sorted(os.listdir(qdir)):
            if not fn.endswith(".json"):
                continue
            try:
                d = json.loads((qdir / fn).read_text(encoding="utf-8"))
            except Exception:
                continue
            title = clean_marker(SUFFIX_RE.sub("", d.get("title") or ""))
            meta = meta_from_tds(d.get("tds"))
            if not title:
                title = clean_marker(meta.get("Name", "") or "")
            has_dialog = any("dialog_data.push" in s for s in d.get("scripts") or [])
            qmeta[fn[:-5].split("_")[-1]] = (title, has_dialog, meta)

    def is_stub(t):
        return "(test)" in (t or "").replace("（", "(").replace("）", ")").casefold()

    def kept_qs(ch_key):
        """q ids of one ch page minus (test) stubs and empty pages, in page
        order; an untitled quest with dialogue falls back to the ch title."""
        ch_title = clean_marker((ch_idx.get(ch_key) or {}).get("title") or "")
        out = []
        for q in (ch_idx.get(ch_key) or {}).get("qs") or []:
            title, has_dialog, meta = qmeta.get(str(q), ("", False, {}))
            if is_stub(title):
                continue
            if not title and not has_dialog and \
                    not any(k in meta for k in ("Description", "Next", "Involved NPC")):
                continue
            out.append((str(q), norm(title) or norm(ch_title)))
        return out

    title2ch = defaultdict(list)
    for key, v in ch_idx.items():
        t = norm(v.get("title") or "")
        if t:
            title2ch[t].append(key)

    result = {}
    for key, info in files.items():
        folder, stem = key
        cands = title2ch.get(norm(stem), [])
        if len(cands) > 1:
            by_series = [c for c in cands
                         if norm(ch_series.get(c, "").split(" ")[0]) == norm(folder)]
            if by_series:
                cands = by_series
        if len(cands) != 1:
            continue
        ch_key = cands[0]
        ftitles = [norm((q or {}).get("title") or "")
                   for q in (info["json"].get("quests") or [])]
        cands_q = kept_qs(ch_key)
        qids, used = [], set()
        for ft in ftitles:
            hit = next((i for i, (_q, qt) in enumerate(cands_q)
                        if i not in used and qt == ft), None)
            if hit is None:
                qids, used = [], set()
                break
            used.add(hit)
            qids.append(f"q-{cands_q[hit][0]}")
        if len(qids) != len(ftitles):  # fall back to page order
            qids = [f"q-{q}" for q, _t in cands_q] if len(cands_q) == len(ftitles) else []
        entry = {"id": f"ch-{ch_key.split('_')[-1]}", "via": "ch_index",
                 "rel": info["rel"]}
        if qids:
            entry["qids"] = qids
        result[key] = entry
    return result



def _match_archon_ja(files):
    """ja archon: html_aq_ja/ch_index.json maps each ch_ page (1:1 with an
    act file) to its q_ links (1:1 with quests[] entries), scraped from the
    chapter page itself. File id = ch-<cid>; per-quest ids = q-<qid>.

    Title quirks handled: unrendered wiki template macros in page titles
    ({MATEAVATAR#SEXPRO[...]}) match by suffix; ・/· and full-width paren
    normalization; act files whose title diverges from the page title match
    via their quests[] titles against the q link names."""
    base = TMP / "html_aq_ja"
    idx_p = base / "ch_index.json"
    if not idx_p.is_file():
        return {}
    ch_idx = json.loads(idx_p.read_text(encoding="utf-8"))
    ch_series, ch_name = {}, {}
    list_p = base / "ch_list.json"
    if list_p.is_file():
        for row in json.loads(list_p.read_text(encoding="utf-8")):
            slug = row.get("slug") or ""
            ch_series[slug] = clean_marker(row.get("series") or "")
            ch_name[slug] = clean_marker(row.get("name") or "")

    def norm_ja(t):
        t = norm(t).replace("\u30fb", "\u00b7")
        return t.replace("\uff08", "(").replace("\uff09", ")")

    def is_stub(t):
        return "(test)" in (t or "").replace("\uff08", "(").replace("\uff09", ")").casefold()

    macro_re = re.compile(r"\{[^{}]*\}")
    title2ch = defaultdict(list)
    macro_suffix = []
    for key, v in ch_idx.items():
        for t in (v.get("title") or "", ch_name.get(key, "")):
            t = clean_marker(t)
            tn = norm_ja(t)
            if not tn or tn == "n/a":
                continue
            if "{" in t:
                suf = norm_ja(macro_re.sub("", t))
                if suf:
                    macro_suffix.append((suf, key))
            else:
                title2ch[tn].append(key)

    qname2ch = defaultdict(list)
    qname_global = defaultdict(list)
    for key, v in ch_idx.items():
        for qid, nm in (v.get("qnames") or {}).items():
            qn = norm_ja(nm)
            if not qn or qn == "n/a" or is_stub(nm):
                continue
            qname2ch[qn].append(key)
            qname_global[qn].append((key, str(qid)))

    def kept_qs(ch_key):
        """(qid, normalized name) in page order, minus (test) stubs."""
        v = ch_idx.get(ch_key) or {}
        qnames = v.get("qnames") or {}
        return [(str(q), norm_ja(qnames.get(str(q), "")))
                for q in v.get("qs") or []
                if not is_stub(qnames.get(str(q), ""))]

    def match_quests(info, ch_key):
        ftitles = [norm_ja((q or {}).get("title") or "")
                   for q in (info["json"].get("quests") or [])]
        cands_q = kept_qs(ch_key)
        qids, used, taken = [], set(), set()
        ok = True
        for ft in ftitles:
            hit = next((i for i, (_q, qt) in enumerate(cands_q)
                        if i not in used and qt == ft), None)
            if hit is not None:
                used.add(hit)
                qids.append(f"q-{cands_q[hit][0]}")
                taken.add(cands_q[hit][0])
                continue
            # quest listed on another chapter page (e.g. an epilogue quest
            # the in-game act still carries) -> unique global qname lookup
            gl = [g for g in qname_global.get(ft, []) if g[1] not in taken]
            if len(gl) == 1:
                qids.append(f"q-{gl[0][1]}")
                taken.add(gl[0][1])
                continue
            ok = False
            break
        if not ok:  # fall back to page order
            qids = [f"q-{q}" for q, _t in cands_q] if len(cands_q) == len(ftitles) else []
        return qids

    matched = {}
    for key, info in files.items():
        folder, stem = key
        data = info["json"]
        ftitles = {norm_ja(stem), norm_ja(data.get("act_title") or "")} - {""}
        qtitles = {norm_ja((q or {}).get("title") or "")
                   for q in (data.get("quests") or [])} - {""}
        ch_key, via = None, None

        cands = set()
        for t in ftitles:
            cands.update(title2ch.get(t, []))
        if len(cands) > 1:
            by_series = {c for c in cands
                         if norm(ch_series.get(c, "").split(" ")[0]) == norm(folder)}
            if by_series:
                cands = by_series
        if len(cands) == 1:
            ch_key, via = next(iter(cands)), "ch-title"

        if not ch_key:
            cands = set()
            for t in ftitles:
                cands.update(c for suf, c in macro_suffix if t.endswith(suf))
            if len(cands) == 1:
                ch_key, via = next(iter(cands)), "ch-title-macro"

        if not ch_key:
            cands = set()
            for t in ftitles | qtitles:
                cands.update(qname2ch.get(t, []))
            if len(cands) == 1:
                ch_key, via = next(iter(cands)), "qname"

        if not ch_key:
            scores = defaultdict(int)
            for t in qtitles:
                for c in qname2ch.get(t, []):
                    scores[c] += 1
            if scores:
                best = max(scores.values())
                top = {c for c, s in scores.items() if s == best}
                if best >= 2 and len(top) == 1:
                    ch_key, via = next(iter(top)), "quests-overlap"

        if not ch_key:
            continue
        entry = {"id": f"ch-{ch_key.split('_')[-1]}", "via": via, "rel": info["rel"]}
        qids = match_quests(info, ch_key)
        if qids:
            entry["qids"] = qids
        matched[key] = (ch_key, entry)

    # two files on one ch page -> act ordinals, like _match_by_title
    by_ch = defaultdict(list)
    for key, (ch_key, _e) in matched.items():
        by_ch[ch_key].append(key)
    result = {}
    for ch_key, keys in by_ch.items():
        if len(keys) == 1:
            result[keys[0]] = matched[keys[0]][1]
            continue
        cid = ch_key.split("_")[-1]
        ordered = sorted(keys, key=lambda k: (act_ordinal(files[k]["json"].get("act"),
                                                          k[1]) or 10 ** 6, k[1]))
        for i, k in enumerate(ordered):
            e = dict(matched[k][1])
            e["id"] = f"ch-{cid}-{i + 1}"
            e["via"] += "+ordinal"
            result[k] = e
    return result


def wiki_chapters_aq(lang):
    """archon: ch_XXXX pages are act pages; title == output act file name."""
    cands = defaultdict(list)
    chdir = {"en": TMP / "_scrape" / "raw_aq_en_ch",
             "zh": TMP / "_scrape" / "raw_aq_zh_ch"}.get(lang)
    if chdir and chdir.is_dir():
        for p in chdir.glob("ch_*.html"):
            t = chapter_page_title(p)
            if t:
                cands[p.stem[3:]].append(t)
    return {cid: list(set(ts)) for cid, ts in cands.items()}


def _match_hangout_zh(files):
    """zh hangout: qid->ch via enum_hq, Series part0 == output file stem."""
    qid2cid = {}
    for p in (TMP / "_scrape" / "enum_hq").glob("ch_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("ch"):
            for q in d.get("qids") or []:
                qid2cid.setdefault(str(q), str(d["ch"]))
    if not qid2cid:
        return {}
    stem2cids = defaultdict(set)
    for slug, (_t, meta) in load_tds_qpages(TMP / "html_hq_zh" / "q").items():
        cid = qid2cid.get(slug.split("_")[-1])
        sv = meta.get("Series", "")
        if cid and sv and sv.lower() != "n/a":
            parts = [norm(x) for x in sv.split(":") if norm(x)]
            if parts:
                stem2cids[parts[0]].add(cid)
    by_cid = defaultdict(list)
    for key in files:
        cids = stem2cids.get(norm(key[1].split("/")[-1]), set())
        if len(cids) == 1:
            by_cid[next(iter(cids))].append(key)
    result = {}
    for cid, keys in by_cid.items():
        for k in keys:
            result[k] = {"id": f"ch-{cid}", "via": "series+enum",
                         "rel": files[k]["rel"]}
    return result


def wiki_map_hq(lang):
    if lang == "zh":
        return {slug: (series_from_tds(meta) or title, title)
                for slug, (title, meta) in load_tds_qpages(TMP / "html_hq_zh" / "q").items()}
    if lang == "ja":
        out = {}
        for p in (TMP / "_scrape" / "enum_hq").glob("ch_*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            cid, title = d.get("ch"), clean_marker(d.get("title") or "")
            if cid and title:
                out[f"ch_{cid}"] = (None, title)
        return out
    return {}


def match_type(qtype, lang):
    catdir = SRC / {"en": "En", "ja": "Ja", "zh": "Zh"}[lang] / QUEST_DIRS[lang][qtype]
    files = walk_quest_files(catdir)
    if not files:
        return {}, (0, 0)

    result = {}
    for key, info in files.items():
        m = Q_SUFFIX_RE.search(key[1].split("/")[-1])
        if m:
            result[key] = {"id": f"q-{m.group(1)}", "via": "filename",
                           "rel": info["rel"]}

    if qtype in ("world", "event", "hangout"):
        wiki = {"world": wiki_map_wq, "event": wiki_map_eq,
                "hangout": wiki_map_hq}[qtype](lang)
        by_pair = defaultdict(list)
        for slug, (series, title) in wiki.items():
            by_pair[(norm(series), norm(title))].append(slug)
        wiki_by_title = defaultdict(list)
        for slug, (_s, title) in wiki.items():
            wiki_by_title[norm(title)].append(slug)
        out_titles = defaultdict(list)
        for key in files:
            out_titles[norm(key[1].split("/")[-1])].append(key)

        allow_title_unique = (qtype == "hangout") or (qtype == "world" and lang == "ja")
        for key, info in files.items():
            if key in result:
                continue
            data = info["json"]
            folder, stem = key
            titles = {norm(stem), norm(data.get("act_title") or ""),
                      norm((data.get("quests") or [{}])[0].get("title") or "")} - {""}
            hit = None
            for t in titles:
                for s in {norm(folder), norm(data.get("chapter") or "")} - {""}:
                    slugs = by_pair.get((s, t), [])
                    if len(slugs) == 1:
                        hit = ("series+title", slugs[0])
                        break
                if hit:
                    break
            if not hit and allow_title_unique:
                for t in titles:
                    if t and len(wiki_by_title.get(t, [])) == 1 and len(out_titles.get(t, [])) == 1:
                        hit = ("title-unique", wiki_by_title[t][0])
                        break
            if hit:
                result[key] = {"id": hit[1].replace("_", "-"), "via": hit[0],
                               "rel": info["rel"]}
        if qtype == "hangout" and lang == "zh":
            for k, v in _match_hangout_zh(files).items():
                result.setdefault(k, v)

    elif qtype in ("story", "archon"):
        if qtype == "archon" and lang == "ja":
            result.update(_match_archon_ja(files))
        elif qtype == "archon":
            chapters = wiki_chapters_aq(lang)
            title2cid = defaultdict(list)
            for cid, ts in chapters.items():
                for t in ts:
                    title2cid[norm(t)].append(cid)
            result.update(_match_by_title(files, title2cid))
        elif lang == "zh":
            result.update(_match_story_zh(files))
        else:
            chapters = wiki_chapters_lq(lang)
            title2cid = defaultdict(list)
            for cid, e in chapters.items():
                for t in e["titles"] | e["qtitles"]:
                    title2cid[norm(t)].append(cid)
            result.update(_match_by_title(files, title2cid))

    return result, (sum(1 for v in result.values() if v.get("id")), len(files))


def main():
    maps = {"_meta": {
        "note": "Honey Hunter wiki id recovery map (generated by scripts/recover_quest_ids.py)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }}
    report = []
    for qtype in ("archon", "story", "world", "event", "hangout"):
        for lang in ("en", "ja", "zh"):
            if qtype not in QUEST_DIRS[lang]:
                continue
            res, cov = match_type(qtype, lang)
            maps[f"{qtype}/{lang}"] = {
                info["rel"]: {"id": info["id"], "via": info["via"],
                              **({"qids": info["qids"]} if info.get("qids") else {})}
                for info in res.values()}
            pct = f"{cov[0] * 100 // cov[1]}%" if cov[1] else "-"
            report.append((qtype, lang, cov[0], cov[1], pct))
    MAPS_OUT.parent.mkdir(parents=True, exist_ok=True)
    MAPS_OUT.write_text(json.dumps(maps, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'type':8} {'lang':4} {'mapped':>7} {'total':>7} {'rate':>5}")
    for qtype, lang, n, total, pct in report:
        print(f"{qtype:8} {lang:4} {n:7} {total:7} {pct:>5}")
    print(f"\nwritten: {MAPS_OUT}")
    log = MAPS_OUT.parent / "_recover_log.txt"
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(f"{'type':8} {'lang':4} {'mapped':>7} {'total':>7} {'rate':>5}\n")
        for qtype, lang, n, total, pct in report:
            fh.write(f"{qtype:8} {lang:4} {n:7} {total:7} {pct:>5}\n")
        fh.write(f"\nwritten: {MAPS_OUT}\n")


if __name__ == "__main__":
    main()




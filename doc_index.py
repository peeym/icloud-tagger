#!/usr/bin/env python3
"""doc_index.py: deep tagging for personal, family and company admin documents in iCloud Drive.

CP-2 of icloud-tagger. Identifies what each document IS (ID card, vehicle licence, invoice, policy),
writes Finder tags plus a one-line Hebrew description (Finder comment), keeps a searchable local
index, and maintains Finder aliases to the important documents in one central folder.

Originals are never moved, renamed or modified. Only tags, comments and alias files are written.
Nothing is sent to any external service. Cloud-only (dataless) files are classified from their name
and folder only; their content is never downloaded by `scan`.

Subcommands
  scan                 rules pass over the scope roots (incremental: text extraction only for changed local files)
  apply                write Finder tags (additive) and the description as Finder comment
  aliases              build / refresh the central folder of Finder aliases
  queue                list files the rules could not identify
  find "<query>"       search the index (Hebrew normalised: bidi marks, niqqud and quote variants ignored)
  report               counts per root, status, category, aliases
  override             add a manual identification (kept in data/overrides.json, survives re-runs)
  preview              make local previews of queued files for a human / Claude to identify
  weekly               scan + apply (no Finder automation) + aliases, one summary line to the log

Interactive: any python3. Unattended (launchd): /opt/homebrew/bin/python3, the interpreter that holds the
macOS iCloud Drive (File Provider) permission; alias files are then written by a /usr/bin/python3 child (pyobjc).
Rules: rules.json. Index: data/doc-index.json. Overrides: data/overrides.json (both gitignored).
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "rules.json")
DATA_DIR = os.path.join(HERE, "data")
INDEX_PATH = os.path.join(DATA_DIR, "doc-index.json")
OVERRIDES_PATH = os.path.join(DATA_DIR, "overrides.json")
LOG_DIR = os.path.join(HERE, "logs")
WEEKLY_LOG = os.path.join(LOG_DIR, "doc-index-weekly.log")

TAG_BIN = next((p for p in ("/opt/homebrew/bin/tag", "/usr/local/bin/tag") if os.path.exists(p)), "tag")
PDFTOTEXT = next((p for p in ("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext") if os.path.exists(p)), None)
SF_DATALESS = 0x40000000
TEXT_MAX_BYTES = 15 * 1024 * 1024

# --------------------------------------------------------------------------- normalisation

_QUOTES_DBL = "״“”„″\""
_QUOTES_SGL = "׳‘’‚`´′'"
_SEP = re.compile(r"[_\-‐-―.·,;:()\[\]{}#+=~|!?]+")
_WS = re.compile(r"\s+")
HEB_OR_WORD = "0-9a-zא-ת"


def strip_invisible(s: str) -> str:
    """Remove bidi controls, zero-width and other format/control characters."""
    s = unicodedata.normalize("NFC", s)
    return "".join(ch for ch in s if unicodedata.category(ch) not in ("Cf", "Cc") or ch in "\t\n")


def key(s: str) -> str:
    """Matching key: invisible chars, niqqud and quotes removed, separators to spaces, lowercase."""
    s = strip_invisible(s)
    s = "".join(ch for ch in s if not ("֑" <= ch <= "ׇ") or ch == "־")
    s = s.replace("־", " ")
    for q in _QUOTES_DBL + _QUOTES_SGL:
        s = s.replace(q, "")
    s = s.lower().replace("רישיון", "רשיון")  # spelling variants of the same word
    s = _SEP.sub(" ", s)
    return _WS.sub(" ", s).strip()


def path_key(rel_dir: str) -> str:
    """Key for a relative folder path; keeps the / separators so prefixes like '/רכב' work."""
    return "/" + "/".join(key(p) for p in rel_dir.split("/") if p) + "/"


class Pattern:
    __slots__ = ("raw", "rx", "sub")

    def __init__(self, raw: str):
        self.raw = raw
        if raw[:1] in ("=", "~"):
            word = key(raw[1:])
            prefix = "[\u05d5\u05d4\u05d1\u05dc\u05de\u05e9\u05db]?" if raw[0] == "~" else ""  # ~ allows a Hebrew prefix letter (ו ה ב ל מ ש כ)
            self.rx = re.compile(r"(?<![%s])%s%s(?![%s])" % (HEB_OR_WORD, prefix, re.escape(word), HEB_OR_WORD))
            self.sub = None
        else:
            self.rx = None
            if "/" in raw:
                self.sub = path_key(raw).rstrip("/") if not raw.endswith("/") else path_key(raw)
                if not raw.startswith("/"):
                    self.sub = self.sub.lstrip("/")
            else:
                self.sub = key(raw)

    def hit(self, text: str) -> bool:
        if self.rx is not None:
            return bool(self.rx.search(text))
        return bool(self.sub) and self.sub in text


def pats(lst):
    return [Pattern(p) for p in (lst or [])]


# --------------------------------------------------------------------------- xattr helpers

_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.getxattr.restype = ctypes.c_ssize_t
_libc.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
_libc.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
XATTR_NOFOLLOW = 0x0001


def get_xattr_plist(path: str, name: str):
    p, n = path.encode(), name.encode()
    size = _libc.getxattr(p, n, None, 0, 0, XATTR_NOFOLLOW)
    if size <= 0:
        return None
    buf = ctypes.create_string_buffer(size)
    got = _libc.getxattr(p, n, buf, size, 0, XATTR_NOFOLLOW)
    if got <= 0:
        return None
    try:
        return plistlib.loads(buf.raw[:got])
    except Exception:
        return None


def set_xattr_plist(path: str, name: str, value) -> bool:
    data = plistlib.dumps(value, fmt=plistlib.FMT_BINARY)
    return _libc.setxattr(path.encode(), name.encode(), data, len(data), 0, XATTR_NOFOLLOW) == 0


def current_tags(path: str):
    v = get_xattr_plist(path, "com.apple.metadata:_kMDItemUserTags") or []
    return [t.split("\n")[0] for t in v if isinstance(t, str)]


def current_comment(path: str) -> str:
    v = get_xattr_plist(path, "com.apple.metadata:kMDItemFinderComment")
    return v if isinstance(v, str) else ""


# --------------------------------------------------------------------------- io

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


class Rules:
    def __init__(self, path=RULES_PATH):
        raw = open(path, encoding="utf-8").read()
        self.hash = hashlib.sha1(raw.encode()).hexdigest()[:12]
        r = json.loads(raw)
        self.r = r
        self.root = os.path.expanduser(r["icloud_root"])
        self.central = r["central_folder"]
        self.roots = r["roots"]
        self.exts = {e.lower() for e in r["extensions"]}
        self.important_tag = r.get("important_tag", "מסמך חשוב")
        self.categories = r["categories"]
        self.persons = [(p["tag"], pats(p["any"])) for p in r["persons"]]
        self.person_desc = r.get("person_names_for_description", {})
        self.entities = [dict(e, _any=pats(e.get("any")), _path=pats(e.get("path_any"))) for e in r["entities"]]
        na = r["not_admin"]
        self.na_path, self.na_name = pats(na.get("path_any")), pats(na.get("name_any"))
        self.modifiers = [dict(m, _path=pats(m["path_any"])) for m in r.get("path_modifiers", [])]
        self.types = []
        self.type_by_id = {}
        for t in r["doc_types"]:
            t = dict(t, _any=pats(t.get("any")), _all=pats(t.get("all")), _none=pats(t.get("none")),
                     _path=pats(t.get("path_any")), _pnone=pats(t.get("path_none")))
            self.types.append(t)
            self.type_by_id[t["id"]] = t
        self.folder_defaults = [dict(f, _path=pats(f["path_any"])) for f in r["folder_defaults"]]
        self.folder_force = [dict(f, _path=pats(f["path_any"])) for f in r.get("folder_force", [])]
        self.no_entity_cats = set(r.get("no_entity_categories", []))


# --------------------------------------------------------------------------- classification

def type_matches(t, text, pk, ext):
    if t.get("ext") and ext not in t["ext"]:
        return False
    if t["_path"] and not any(p.hit(pk) for p in t["_path"]):
        return False
    if t["_pnone"] and any(p.hit(pk) for p in t["_pnone"]):
        return False
    if t["_none"] and any(p.hit(text) for p in t["_none"]):
        return False
    if t["_all"] and not all(p.hit(text) for p in t["_all"]):
        return False
    if t["_any"] and not any(p.hit(text) for p in t["_any"]):
        return False
    return bool(t["_any"] or t["_all"])


def match_type(rules, text, pk, ext, for_text=False):
    for t in rules.types:
        if for_text and (t.get("cat") == "ids" or t.get("no_text")):
            continue
        if type_matches(t, text, pk, ext):
            return t
    return None


RX_MONTH_YEAR = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])[-./ ](20\d{2})(?!\d)")
RX_MONTH_YY = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])-(\d{2})(?!\d)")
RX_YEAR = re.compile(r"(?<!\d)((?:19[89]|20[0-3])\d)(?!\d)")


def find_period(name: str, rel_dir: str) -> str:
    for is_dir, src in ((False, strip_invisible(name)), (True, strip_invisible(rel_dir.split("/")[-1] if rel_dir else ""))):
        m = RX_MONTH_YEAR.search(src)
        if m:
            return "%s-%s" % (int(m.group(1)), m.group(2))
        m = RX_MONTH_YY.search(src)
        if m and is_dir:
            return "%s-20%s" % (int(m.group(1)), m.group(2))
        m = RX_YEAR.search(src)
        if m:
            return m.group(1)
    for part in reversed(rel_dir.split("/")[:-1]):
        m = RX_YEAR.search(strip_invisible(part))
        if m:
            return m.group(1)
    return ""


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ו" + items[-1]


RX_LONG_DIGITS = re.compile(r"\d{4,}")
RX_GENERIC = re.compile(r"^(img|scn|scan|file|image|photo|whatsapp|dsc|untitled|attachedfile|document|export|report|pdf)\b")


def clean_title(name: str) -> str:
    """Readable file title for the description. Drops digit runs of 4+ (ID, account, policy numbers), keeps years."""
    stem = strip_invisible(os.path.splitext(name)[0])
    stem = re.sub(r"\.(pdf|jpe?g|png|xlsx?|docx?|tiff?)$", "", stem, flags=re.I)
    if re.fullmatch(r"[0-9a-fA-F-]{16,}|ACFr[\w=-]{20,}", stem.strip()):  # UUIDs and Gmail attachment ids say nothing
        return ""
    stem = RX_LONG_DIGITS.sub(lambda m: m.group(0) if re.fullmatch(r"(19[89]|20[0-3])\d", m.group(0)) else " ", stem)
    stem = re.sub(r"[_\[\]{}#=]+", " ", stem)
    stem = re.sub(r"\s*[-.,:]+\s*(?=[-.,:]|$)", " ", stem)
    stem = _WS.sub(" ", stem).strip(" -.,:()")
    if not re.search(r"[a-zA-Z\u05d0-\u05ea]{3,}", stem) or RX_GENERIC.match(stem.lower()):
        return ""
    return stem[:70]


def build_description(rules, t, persons, entity, period, extra_suffix, name):
    desc = t.get("desc", "מסמך")
    if persons and " של " not in desc:
        desc += " של " + join_he(rules.person_desc.get(p, p) for p in persons)
    if entity and entity["desc"] not in desc:
        desc += ", " + entity["desc"]
    if period and period not in desc:
        desc += ", " + period
    title = clean_title(name)
    noise = {"copy", "עותק", "large", "small", "scan", "חתום", "pdf"}
    extra = [w for w in key(title).split() if w not in noise and not re.fullmatch(r"\d{1,2}", w)]
    if title and any(w not in key(desc) for w in extra) and not t.get("is_send_copy"):
        desc += " (" + title + ")"
    notes = []
    if t.get("note"):
        notes.append(t["note"])
    if t.get("id_original"):
        if "אלעד" in persons and "לשליחה" not in key(name):
            notes.append("עותק מקורי לא מוסתר, לא לשלוח. לשליחה יש קובץ נפרד: תעודת זהות אלעד לשליחה")
        elif t["id"] != "sefach":
            notes.append("עותק מקורי, לא לשלוח כמו שהוא")
    if extra_suffix:
        notes.append(extra_suffix)
    if notes:
        desc += ". " + ". ".join(notes)
    return desc.replace("\u2014", ",").replace("\u2013", ",")  # house rule: no em or en dash as separator


def classify(rules, rec, overrides):
    rel = rec["rel"]
    rel_dir, name = rel.rsplit("/", 1)
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    nk, pk = key(stem), path_key(rel_dir)
    full = pk + " " + nk
    out = {"status": None, "source": None, "type": None, "category": None, "tags": [], "persons": [],
           "entity": None, "description": "", "alias": False}

    ov = overrides.get(rel)
    t = None
    if ov and ov.get("not_admin"):
        out.update(status="not_admin", source="override")
        return out
    if ov and ov.get("type"):
        t = rules.type_by_id.get(ov["type"])
        out["source"] = "override"
    if t is None and not ov:
        if any(p.hit(pk) for p in rules.na_path) or any(p.hit(nk) for p in rules.na_name):
            out.update(status="not_admin", source="rule")
            return out
        for ff in rules.folder_force:
            if any(p.hit(pk) for p in ff["_path"]):
                t = rules.type_by_id[ff["type"]]
                out["source"] = "name"
                break
        t = t or match_type(rules, nk, pk, ext)
        if t and not out["source"]:
            out["source"] = "name"
        elif rec.get("text_type"):
            t = rules.type_by_id.get(rec["text_type"])
            out["source"] = "text" if t else None
        if t is None:
            for fd in rules.folder_defaults:
                if any(p.hit(pk) for p in fd["_path"]):
                    if fd.get("type"):
                        t = rules.type_by_id[fd["type"]]
                        out["source"] = "folder"
                    elif fd.get("status") == "not_admin" and ext not in fd.get("except_ext", []):
                        out.update(status="not_admin", source="folder")
                        return out
                    break
    if t is None and not (ov and ov.get("description")):
        out["status"] = "queued"
        return out

    persons = [tag for tag, plist in rules.persons if any(p.hit(nk) for p in plist)]
    path_persons = [tag for tag, plist in rules.persons if any(p.hit(pk) for p in plist)]
    if t is not None:
        for p in t.get("persons", []):
            if p not in persons:
                persons.append(p)
    if ov and "persons" in ov:
        persons = list(ov["persons"])

    entity = None
    for e in rules.entities:
        if any(p.hit(nk) for p in e["_any"]) or any(p.hit(pk) for p in e["_path"]):
            entity = e
            break
    if ov and "entity" in ov:
        entity = next((e for e in rules.entities if e["id"] == ov["entity"]), None)
    if not persons and not entity:
        persons = path_persons  # folder names like "ביטוחים הראל אלעד צור" say whose it is

    t = t or {"id": "override", "tags": [], "cat": "misc", "alias": False, "desc": "מסמך"}
    cat = t.get("cat", "misc")
    if cat == "@entity":
        cat = entity["id"] if entity else t.get("cat_default", "misc")
    if ov and ov.get("category"):
        cat = ov["category"]

    if cat in rules.no_entity_cats:
        entity = None
    alias = bool(t.get("alias")) and out["source"] in ("name", "override")  # text and folder matches never get an alias
    if t.get("alias_ext") and ext not in t["alias_ext"]:
        alias = False
    suffix = ""
    add_tags = []
    for m in rules.modifiers:
        if m.get("cats") and cat not in m["cats"]:
            continue
        if any(p.hit(pk) for p in m["_path"]):
            add_tags += m.get("add_tags", [])
            if "alias" in m:
                alias = alias and m["alias"]
            suffix = m.get("desc_suffix", suffix)
    if ov and "alias" in ov:
        alias = bool(ov["alias"])

    period = find_period(stem, rel_dir)
    desc = build_description(rules, t, persons, entity, period, suffix, name)
    if ov and ov.get("description"):
        desc = ov["description"]

    tags = list(t.get("tags", [])) + (ov.get("tags", []) if ov else [])
    catinfo = rules.categories.get(cat)
    if catinfo:
        tags.append(catinfo["tag"])
    tags += persons + add_tags
    if entity:
        tags.append(entity["tag"])
    if alias:
        tags.append(rules.important_tag)
    seen, tags_u = set(), []
    for x in tags:
        if x and x not in seen:
            seen.add(x)
            tags_u.append(x)

    out.update(status="identified" if out["source"] in ("name", "text", "override") else "folder",
               type=t["id"], category=cat, tags=tags_u, persons=persons,
               entity=entity["id"] if entity else None, description=desc, alias=alias)
    return out


# --------------------------------------------------------------------------- scan

def extract_text_type(rules, path, ext):
    """Local files only. Returns a doc type id found in the first pages of text, never stores the text."""
    text = ""
    try:
        if ext == ".pdf" and PDFTOTEXT:
            r = subprocess.run([PDFTOTEXT, "-l", "2", "-q", path, "-"], capture_output=True, timeout=30)
            text = r.stdout.decode("utf-8", "ignore")
        elif ext in (".doc", ".docx"):
            r = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", path], capture_output=True, timeout=30)
            text = r.stdout.decode("utf-8", "ignore")
    except Exception:
        return None
    if not text.strip():
        return None
    # Hebrew PDFs often come out in visual (reversed) order; try both directions.
    head = text.strip()[:600]  # title area only: matching the whole body was measured to misfire
    for variant in (head, "\n".join(line[::-1] for line in head.splitlines())):
        t = match_type(rules, key(variant), "/", ext, for_text=True)
        if t:
            return t["id"]
    return None


def cmd_scan(args, rules=None, quiet=False):
    rules = rules or Rules()
    index = load_json(INDEX_PATH, {"files": {}})
    files = index.setdefault("files", {})
    overrides = load_json(OVERRIDES_PATH, {})
    now = datetime.now().isoformat(timespec="seconds")
    seen = set()
    stats = Counter()
    central_abs = os.path.join(rules.root, rules.central)
    for root_rel in rules.roots:
        base = os.path.join(rules.root, root_rel)
        if not os.path.isdir(base):
            stats["missing_root"] += 1
            continue
        for dirpath, dirs, fnames in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and os.path.join(dirpath, d) != central_abs]
            for fn in fnames:
                if fn.startswith(".") and fn.endswith(".icloud"):
                    real = fn[1:-7]
                    if os.path.splitext(real)[1].lower() in rules.exts:
                        stats["placeholder_" + root_rel] += 1
                    continue
                if fn.startswith("."):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext not in rules.exts:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                rel = os.path.relpath(full, rules.root)
                seen.add(rel)
                rec = files.get(rel) or {"rel": rel, "first_seen": now}
                changed = rec.get("size") != st.st_size or rec.get("mtime") != int(st.st_mtime)
                dataless = bool(st.st_flags & SF_DATALESS)
                rec.update(rel=rel, root=root_rel, size=st.st_size, mtime=int(st.st_mtime), dataless=dataless, last_seen=now)
                if changed:
                    stats["new_or_changed"] += 1
                    rec["changed_at"] = now
                # text pass: only local (downloaded) files, only when changed or rules changed
                sig = "%s:%s:%s" % (st.st_size, int(st.st_mtime), rules.hash)
                if not dataless and ext in (".pdf", ".doc", ".docx") and st.st_size < TEXT_MAX_BYTES:
                    if rec.get("text_sig") != sig:
                        nk, pk = key(os.path.splitext(fn)[0]), path_key(os.path.dirname(rel))
                        if match_type(rules, nk, pk, ext) is None and not overrides.get(rel):
                            rec["text_type"] = extract_text_type(rules, full, ext)
                            stats["text_extracted"] += 1
                        rec["text_sig"] = sig
                rec.update(classify(rules, rec, overrides))
                files[rel] = rec
                stats["files"] += 1
                stats["dataless"] += dataless
                stats["status_" + rec["status"]] += 1
    gone = [r for r in files if r not in seen]
    for r in gone:
        files[r]["status"] = "gone"
    stats["gone"] = len(gone)
    index.update(rules_hash=rules.hash, updated=now)
    save_json(INDEX_PATH, index)
    if not quiet:
        print("scan: %d files, %d new/changed, %d cloud-only (classified by name and folder only), %d text-extracted"
              % (stats["files"], stats["new_or_changed"], stats["dataless"], stats["text_extracted"]))
        print("  identified=%d folder=%d queued=%d not_admin=%d gone=%d"
              % (stats["status_identified"], stats["status_folder"], stats["status_queued"],
                 stats["status_not_admin"], stats["gone"]))
        ph = {k[12:]: v for k, v in stats.items() if k.startswith("placeholder_")}
        if ph:
            print("  .icloud placeholders skipped:", ph)
    return stats


# --------------------------------------------------------------------------- apply

FINDER_COMMENT_SCRIPT = r'''
on run argv
  set f to item 1 of argv
  set txt to read (POSIX file f) as «class utf8»
  set AppleScript's text item delimiters to linefeed
  set ls to text items of txt
  set ok to 0
  set errs to 0
  repeat with l in ls
    if (length of l) > 0 then
      set AppleScript's text item delimiters to tab
      set parts to text items of l
      try
        tell application "Finder" to set comment of (POSIX file (item 1 of parts) as alias) to (item 2 of parts)
        set ok to ok + 1
      on error
        set errs to errs + 1
      end try
    end if
  end repeat
  return (ok as text) & " " & (errs as text)
end run
'''


def finder_set_comments(pairs):
    """pairs: list of (abs_path, comment). Uses Finder via AppleScript, never activates it."""
    ok = errs = 0
    with tempfile.TemporaryDirectory() as td:
        scpt = os.path.join(td, "c.applescript")
        open(scpt, "w").write(FINDER_COMMENT_SCRIPT)
        for i in range(0, len(pairs), 150):
            tsv = os.path.join(td, "c%d.tsv" % i)
            with open(tsv, "w", encoding="utf-8") as f:
                for p, c in pairs[i:i + 150]:
                    f.write("%s\t%s\n" % (p, c.replace("\t", " ").replace("\n", " ")))
            r = subprocess.run(["/usr/bin/osascript", scpt, tsv], capture_output=True, text=True, timeout=600)
            try:
                a, b = r.stdout.split()
                ok += int(a)
                errs += int(b)
            except ValueError:
                errs += len(pairs[i:i + 150])
    return ok, errs


def cmd_apply(args, rules=None, quiet=False):
    rules = rules or Rules()
    index = load_json(INDEX_PATH, {"files": {}})
    files = index["files"]
    use_finder = not getattr(args, "no_finder", False)
    add_groups = defaultdict(list)
    remove_ops = []
    comment_pairs, comment_recs = [], []
    stats = Counter()
    for rel, rec in files.items():
        if rec.get("status") not in ("identified", "folder"):
            continue
        path = os.path.join(rules.root, rel)
        if not os.path.exists(path):
            continue
        if not os.access(path, os.W_OK):  # read-only file: tags and comments cannot be written, do not retry weekly
            stats["read_only"] += 1
            rec["read_only"] = True
            continue
        rec.pop("read_only", None)
        applied = rec.setdefault("applied", {})
        desired = rec.get("tags", [])
        cur = current_tags(path)
        if "orig_tags" not in rec:
            rec["orig_tags"] = cur
        prev = applied.get("tags", [])
        cur_l = {t.lower() for t in cur}  # Finder tags are case-insensitive
        des_l = {t.lower() for t in desired}
        orig_l = {t.lower() for t in rec["orig_tags"]}
        to_add = [t for t in desired if t.lower() not in cur_l]
        to_remove = [t for t in prev if t.lower() not in des_l and t.lower() not in orig_l and t.lower() in cur_l]
        if to_add:
            add_groups[",".join(to_add)].append((rel, path))
        if to_remove:
            remove_ops.append((rel, path, ",".join(to_remove)))
        if not to_add and not to_remove:
            applied["tags"] = desired
        desc = rec.get("description", "")
        existing = current_comment(path)
        want = desc
        if existing and existing != applied.get("comment") and desc not in existing:
            want = existing + " | " + desc  # keep a comment someone else wrote
        if existing != want or (use_finder and not applied.get("finder")):
            comment_pairs.append((path, want))
            comment_recs.append((rec, want))
    for tagstr, items in add_groups.items():
        for i in range(0, len(items), 50):
            batch = items[i:i + 50]
            r = subprocess.run([TAG_BIN, "-a", tagstr] + [p for _, p in batch], capture_output=True, timeout=120)
            ok = r.returncode == 0
            for rel, p in batch:
                if not ok:
                    ok1 = subprocess.run([TAG_BIN, "-a", tagstr, p], capture_output=True, timeout=30).returncode == 0
                else:
                    ok1 = True
                if ok1:
                    files[rel]["applied"]["tags"] = files[rel]["tags"]
                    stats["tagged"] += 1
                else:
                    stats["tag_errors"] += 1
    for rel, p, tagstr in remove_ops:
        if subprocess.run([TAG_BIN, "-r", tagstr, p], capture_output=True, timeout=30).returncode == 0:
            files[rel]["applied"]["tags"] = files[rel]["tags"]
            stats["untagged"] += 1
    if comment_pairs:
        if use_finder:
            ok, errs = finder_set_comments(comment_pairs)
            stats["comments"] += ok
            stats["comment_errors"] += errs
            for rec, want in comment_recs:
                if current_comment(os.path.join(rules.root, rec["rel"])) == want:
                    rec["applied"].update(comment=want, finder=True)
        else:
            for (p, want), (rec, _) in zip(comment_pairs, comment_recs):
                if set_xattr_plist(p, "com.apple.metadata:kMDItemFinderComment", want):
                    rec["applied"].update(comment=want, finder=False)
                    stats["comments_xattr_only"] += 1
    save_json(INDEX_PATH, index)
    if not quiet:
        print("apply: %d files got tags, %d had stale own tags removed, %d comments via Finder, %d comments as metadata only, errors: tags %d, comments %d, read-only skipped %d"
              % (stats["tagged"], stats["untagged"], stats["comments"], stats["comments_xattr_only"],
                 stats["tag_errors"], stats["comment_errors"], stats["read_only"]))
    return stats


# --------------------------------------------------------------------------- aliases

ALIAS_HELPER = r"""
import sys
from Foundation import NSURL
s, d = NSURL.fileURLWithPath_(sys.argv[1]), NSURL.fileURLWithPath_(sys.argv[2])
data, err = s.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(1 << 10, None, None, None)
ok = data is not None and NSURL.writeBookmarkData_toURL_options_error_(data, d, 1 << 10, None)[0]
sys.exit(0 if ok else 1)
"""
ALLOW_FINDER = True  # weekly (unattended) run sets this False: no Finder automation, no permission prompts


def make_alias(src, dst):
    """Real Finder alias (bookmark file). Order: pyobjc in-process, then /usr/bin/python3 helper
    (carries pyobjc; as a child it inherits this process's iCloud permission), then Finder (interactive only)."""
    try:
        from Foundation import NSURL  # pyobjc, present in /usr/bin/python3
        s, d = NSURL.fileURLWithPath_(src), NSURL.fileURLWithPath_(dst)
        data, err = s.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(1 << 10, None, None, None)
        if data is None:
            return False
        ok, err = NSURL.writeBookmarkData_toURL_options_error_(data, d, 1 << 10, None)
        return bool(ok)
    except ImportError:
        if os.path.exists("/usr/bin/python3"):
            r = subprocess.run(["/usr/bin/python3", "-c", ALIAS_HELPER, src, dst], capture_output=True, timeout=60)
            if r.returncode == 0:
                return True
        if not ALLOW_FINDER:
            return False
        folder, name = os.path.dirname(dst), os.path.basename(dst)
        script = ('tell application "Finder" to make new alias file at (POSIX file "%s" as alias) to '
                  '(POSIX file "%s" as alias) with properties {name:"%s"}') % (folder, src, name.replace('"', '\\"'))
        return subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, timeout=60).returncode == 0


def alias_display_name(rel, description=""):
    """Alias file name: the original name, or the description when the original name says nothing (IMG_1234.jpg)."""
    name = strip_invisible(os.path.basename(rel)).strip()
    if not clean_title(name) and description:
        stem = description.split(". ")[0][:80].strip(" ,.")
        name = stem + os.path.splitext(name)[1].lower()
    return _WS.sub(" ", name).replace("/", "-").replace(":", "-")


def trash_alias(path):
    """Move an alias file this tool created to the Trash (never rm, never an original)."""
    dest = os.path.join(os.path.expanduser("~/.Trash"), os.path.basename(path))
    if os.path.lexists(dest):
        dest += ".%d" % int(time.time())
    shutil.move(path, dest)


def dedupe_key(rel, size):
    stem, ext = os.path.splitext(os.path.basename(rel))
    k = key(stem)
    k = re.sub(r"\b(copy|עותק)\b", "", k)
    k = re.sub(r"\s\d{1,2}$", "", k).strip()
    return (k, ext.lower(), size)


def cmd_aliases(args, rules=None, quiet=False):
    rules = rules or Rules()
    index = load_json(INDEX_PATH, {"files": {}})
    files = index["files"]
    central = os.path.join(rules.root, rules.central)
    os.makedirs(central, exist_ok=True)
    stats = Counter()
    used_names = defaultdict(dict)  # category folder -> name -> rel
    planned_keys = {}
    # existing aliases first, so their names and dedupe keys are reserved
    wanted = sorted((r for r in files.values() if r.get("alias") and r.get("status") in ("identified", "folder")),
                    key=lambda r: (0 if r.get("alias_path") else 1, r["rel"]))
    for rec in wanted:
        cat = rules.categories.get(rec["category"], rules.categories["misc"])["folder"]
        dk = (cat,) + dedupe_key(rec["rel"], rec["size"])
        if dk in planned_keys and planned_keys[dk] != rec["rel"]:
            rec["alias_dupe_of"] = planned_keys[dk]
            stats["dupes_skipped"] += 1
            continue
        planned_keys[dk] = rec["rel"]
        rec.pop("alias_dupe_of", None)
        ap = rec.get("alias_path")
        folder = os.path.join(central, cat)
        name = alias_display_name(rec["rel"], rec.get("description", ""))
        if ap and os.path.lexists(os.path.join(rules.root, ap)) and ap.split("/")[-2] == cat:
            cur_name = os.path.basename(ap)
            if (cur_name != name and not os.path.lexists(os.path.join(folder, name)) and name not in used_names[cat]
                    and not getattr(args, "dry_run", False) and not cur_name.startswith(os.path.splitext(name)[0] + " - ")):
                os.rename(os.path.join(rules.root, ap), os.path.join(folder, name))  # our own alias file, never an original
                rec["alias_path"] = os.path.relpath(os.path.join(folder, name), rules.root)
                cur_name = name
                stats["renamed"] += 1
            used_names[cat][cur_name] = rec["rel"]
            stats["existing"] += 1
            stats["cat_" + cat] += 1
            continue
        if ap and os.path.lexists(os.path.join(rules.root, ap)) and not getattr(args, "dry_run", False):
            trash_alias(os.path.join(rules.root, ap))  # category changed: our old alias goes to the Trash
            rec.pop("alias_path", None)
            stats["moved_category"] += 1
        os.makedirs(folder, exist_ok=True)
        if name in used_names[cat] or os.path.lexists(os.path.join(folder, name)):
            stem, ext = os.path.splitext(name)
            parent = strip_invisible(os.path.basename(os.path.dirname(rec["rel"]))).strip()
            name = "%s - %s%s" % (stem, parent, ext)
            n = 2
            while name in used_names[cat] or os.path.lexists(os.path.join(folder, name)):
                name = "%s - %s %d%s" % (stem, parent, n, ext)
                n += 1
        dst = os.path.join(folder, name)
        if getattr(args, "dry_run", False):
            stats["would_create"] += 1
            continue
        if make_alias(os.path.join(rules.root, rec["rel"]), dst):
            rec["alias_path"] = os.path.relpath(dst, rules.root)
            used_names[cat][name] = rec["rel"]
            stats["created"] += 1
            stats["cat_" + cat] += 1
        else:
            stats["errors"] += 1
    # stale: aliases we made whose source no longer wants one
    stale = [r for r in files.values() if r.get("alias_path") and
             (not r.get("alias") or r.get("status") not in ("identified", "folder") or r.get("alias_dupe_of"))]
    for r in stale:
        ap = os.path.join(rules.root, r["alias_path"])
        if getattr(args, "prune", False) and os.path.lexists(ap):
            trash_alias(ap)
            r.pop("alias_path", None)
            stats["pruned"] += 1
        else:
            stats["stale"] += 1
    save_json(INDEX_PATH, index)
    if not quiet:
        print("aliases: %d created, %d already there (%d renamed), %d duplicates skipped, %d stale%s, errors %d"
              % (stats["created"], stats["existing"], stats["renamed"], stats["dupes_skipped"], stats["stale"],
                 " (pruned %d)" % stats["pruned"] if stats["pruned"] else "", stats["errors"]))
        print("  folder:", central)
        for k, v in sorted(stats.items()):
            if k.startswith("cat_"):
                print("   %4d  %s" % (v, k[4:]))
    return stats


# --------------------------------------------------------------------------- queue / find / report

def root_priority(rules, rec):
    try:
        return rules.roots.index(rec.get("root"))
    except ValueError:
        return 99


def cmd_queue(args):
    rules = Rules()
    files = load_json(INDEX_PATH, {"files": {}})["files"]
    q = sorted((r for r in files.values() if r.get("status") == "queued"),
               key=lambda r: (root_priority(rules, r), r["rel"]))
    if args.root:
        q = [r for r in q if args.root in r["rel"]]
    print("queued: %d" % len(q))
    by_root = Counter(r["root"] for r in q)
    for k, v in by_root.items():
        print("  %4d  %s" % (v, k))
    for r in q[: args.limit]:
        print("%s%s" % ("[cloud] " if r.get("dataless") else "", strip_invisible(r["rel"])))


def cmd_find(args):
    rules = Rules()
    files = load_json(INDEX_PATH, {"files": {}})["files"]
    toks = [t for t in key(" ".join(args.query)).split() if t]
    if not toks:
        print("empty query")
        return
    hits = []
    for r in files.values():
        if r.get("status") == "gone":
            continue
        name_k = key(os.path.basename(r["rel"]))
        tags_k = key(" ".join(r.get("tags", [])))
        desc_k = key(r.get("description", ""))
        hay = " ".join((name_k, key(r["rel"]), tags_k, desc_k))
        if not all(t in hay for t in toks):
            continue
        score = sum(3 * (t in name_k) + 2 * (t in tags_k) + (t in desc_k) for t in toks)
        score += 2 if r.get("alias") else 0
        score -= 5 if r.get("status") == "not_admin" else 0
        score += 3 if "לשליחה" in r.get("tags", []) else 0
        hits.append((score, r))
    hits.sort(key=lambda x: (-x[0], x[1]["rel"]))
    print("%d result(s) for: %s" % (len(hits), " ".join(args.query)))
    for score, r in hits[: args.limit]:
        print("\n* %s" % (r.get("description") or "(not identified yet)"))
        print("  %s" % os.path.join(rules.root, strip_invisible(r["rel"]) if args.clean else r["rel"]))
        if r.get("alias_path"):
            print("  alias: %s" % os.path.join(rules.root, r["alias_path"]))
        if args.verbose:
            print("  tags: %s | status: %s/%s%s" % (", ".join(r.get("tags", [])), r.get("status"), r.get("source"),
                                                   " | cloud-only" if r.get("dataless") else ""))


def cmd_report(args):
    rules = Rules()
    index = load_json(INDEX_PATH, {"files": {}})
    files = [r for r in index["files"].values() if r.get("status") != "gone"]
    print("index updated %s, rules %s, %d files" % (index.get("updated"), index.get("rules_hash"), len(files)))
    print("\nper root (identified by name|text|override, by folder, queued, not admin, cloud-only):")
    for root in rules.roots:
        rs = [r for r in files if r.get("root") == root]
        src = Counter(r.get("source") for r in rs if r.get("status") == "identified")
        st = Counter(r.get("status") for r in rs)
        print("  %-28s total %4d | name %4d text %3d override %3d | folder %4d | queued %4d | not admin %4d | cloud-only %4d"
              % (root, len(rs), src["name"], src["text"], src["override"], st["folder"], st["queued"],
                 st["not_admin"], sum(1 for r in rs if r.get("dataless"))))
    print("\naliases per category:")
    c = Counter(r["alias_path"].split("/")[-2] for r in files if r.get("alias_path"))
    for k, v in sorted(c.items(), key=lambda x: -x[1]):
        print("  %4d  %s" % (v, k))
    print("  total %d, in %s" % (sum(c.values()), os.path.join(rules.root, rules.central)))
    print("\ndocument types (identified + folder):")
    t = Counter(r.get("type") for r in files if r.get("status") in ("identified", "folder"))
    print("  " + ", ".join("%s %d" % kv for kv in t.most_common()))
    pend = sum(1 for r in files if r.get("status") in ("identified", "folder") and not r.get("applied", {}).get("finder"))
    print("\nfiles whose Finder comment is not yet set through Finder: %d" % pend)


# --------------------------------------------------------------------------- overrides / preview

def cmd_override(args):
    ov = load_json(OVERRIDES_PATH, {})
    if args.import_file:
        new = load_json(args.import_file, {})
        ov.update(new)
        save_json(OVERRIDES_PATH, ov)
        print("overrides: merged %d, total %d" % (len(new), len(ov)))
        return
    if not args.rel:
        print("need --rel or --import")
        return
    e = {}
    if args.not_admin:
        e["not_admin"] = True
    if args.type:
        e["type"] = args.type
    if args.persons is not None:
        e["persons"] = [p for p in args.persons.split(",") if p]
    if args.description:
        e["description"] = args.description
    if args.alias is not None:
        e["alias"] = args.alias == "yes"
    if args.category:
        e["category"] = args.category
    ov[args.rel] = e
    save_json(OVERRIDES_PATH, ov)
    print("override set for", strip_invisible(args.rel))


def evict(path):
    try:
        from Foundation import NSFileManager, NSURL
        NSFileManager.defaultManager().evictUbiquitousItemAtURL_error_(NSURL.fileURLWithPath_(path), None)
    except Exception:
        pass


def cmd_preview(args):
    """Materialise queued files one by one, write a small local preview, evict again if it was cloud-only."""
    rules = Rules()
    files = load_json(INDEX_PATH, {"files": {}})["files"]
    q = sorted((r for r in files.values() if r.get("status") == "queued"),
               key=lambda r: (root_priority(rules, r), r["rel"]))
    if args.root:
        q = [r for r in q if args.root in r["rel"]]
    if args.rels:
        wanted = [l.rstrip("\n") for l in open(args.rels, encoding="utf-8") if l.strip()]
        q = [files[w] for w in wanted if w in files]
    q = q[args.offset: args.offset + args.limit]
    os.makedirs(args.out, exist_ok=True)
    manifest = []
    for i, r in enumerate(q):
        src = os.path.join(rules.root, r["rel"])
        ext = os.path.splitext(src)[1].lower()
        was_dataless = bool(os.stat(src).st_flags & SF_DATALESS)
        stem = os.path.join(args.out, "%03d" % (args.offset + i))
        made = []
        try:
            if ext in (".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".pdf"):
                outp = stem + ".jpg"
                rr = subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", "-Z", str(args.size), src, "--out", outp],
                                    capture_output=True, timeout=120)
                if rr.returncode == 0 and os.path.exists(outp):
                    made.append(outp)
            if ext == ".pdf" and PDFTOTEXT:
                rr = subprocess.run([PDFTOTEXT, "-l", "1", "-q", src, "-"], capture_output=True, timeout=60)
                txt = rr.stdout.decode("utf-8", "ignore").strip()
                if txt:
                    open(stem + ".txt", "w").write(txt[:1200])
                    made.append(stem + ".txt")
            elif ext in (".doc", ".docx"):
                rr = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", src], capture_output=True, timeout=60)
                txt = rr.stdout.decode("utf-8", "ignore").strip()
                if txt:
                    open(stem + ".txt", "w").write(txt[:1200])
                    made.append(stem + ".txt")
        finally:
            if was_dataless and not args.keep:
                evict(src)
        manifest.append({"n": args.offset + i, "rel": r["rel"], "previews": made})
    save_json(os.path.join(args.out, "manifest-%d.json" % args.offset), manifest)
    print("previews: %d files into %s" % (len(manifest), args.out))


# --------------------------------------------------------------------------- weekly

def cmd_weekly(args):
    global ALLOW_FINDER
    ALLOW_FINDER = bool(args.finder_comments)
    rules = Rules()
    t0 = time.time()
    try:
        s = cmd_scan(args, rules, quiet=True)
        a = cmd_apply(argparse.Namespace(no_finder=not args.finder_comments), rules, quiet=True)
        al = cmd_aliases(argparse.Namespace(dry_run=False, prune=False), rules, quiet=True)
        line = ("%s ok files=%d new_or_changed=%d queued=%d tagged=%d comments=%d aliases_new=%d errors=%d %.0fs"
                % (datetime.now().isoformat(timespec="seconds"), s["files"], s["new_or_changed"],
                   s["status_queued"], a["tagged"], a["comments"] + a["comments_xattr_only"],
                   al["created"], a["tag_errors"] + a["comment_errors"] + al["errors"], time.time() - t0))
    except Exception as e:  # one line, then non-zero exit for launchd
        line = "%s FAILED %s: %s" % (datetime.now().isoformat(timespec="seconds"), type(e).__name__, e)
        os.makedirs(LOG_DIR, exist_ok=True)
        open(WEEKLY_LOG, "a").write(line + "\n")
        raise
    os.makedirs(LOG_DIR, exist_ok=True)
    open(WEEKLY_LOG, "a").write(line + "\n")
    print(line)


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="rules pass, incremental")
    p = sub.add_parser("apply", help="write Finder tags (additive) and descriptions")
    p.add_argument("--no-finder", action="store_true", help="write the comment as metadata only, do not drive Finder")
    p = sub.add_parser("aliases", help="build / refresh the central alias folder")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--prune", action="store_true", help="move stale aliases (made by this tool) to the Trash")
    p = sub.add_parser("queue", help="list unidentified files")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--root", default="")
    p = sub.add_parser("find", help="search the index")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--clean", action="store_true", help="print paths without invisible bidi characters")
    sub.add_parser("report", help="summary counts")
    p = sub.add_parser("override", help="manual identification, survives re-runs")
    p.add_argument("--rel", help="path relative to the iCloud Drive root")
    p.add_argument("--type", help="doc type id from rules.json")
    p.add_argument("--persons", help="comma separated person tags")
    p.add_argument("--description")
    p.add_argument("--alias", choices=["yes", "no"])
    p.add_argument("--category")
    p.add_argument("--not-admin", action="store_true")
    p.add_argument("--import", dest="import_file", help="merge a JSON file {rel: {...}}")
    p = sub.add_parser("preview", help="local previews of queued files for identification")
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--root", default="")
    p.add_argument("--size", type=int, default=900)
    p.add_argument("--keep", action="store_true", help="do not evict cloud-only files after preview")
    p.add_argument("--rels", help="file with one relative path per line, instead of the queue")
    p = sub.add_parser("weekly", help="scan + apply + aliases, for launchd")
    p.add_argument("--finder-comments", action="store_true", help="also drive Finder for comments (may need an Automation permission)")
    args = ap.parse_args()
    {"scan": cmd_scan, "apply": cmd_apply, "aliases": cmd_aliases, "queue": cmd_queue, "find": cmd_find,
     "report": cmd_report, "override": cmd_override, "preview": cmd_preview, "weekly": cmd_weekly}[args.cmd](args)


if __name__ == "__main__":
    main()

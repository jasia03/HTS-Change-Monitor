"""
Compare two HTS releases and list every change.

Reads the USITC JSON files that download_hts.py saves in data/raw/.

Usage:
    python diff.py data/raw/2026HTSRev20.json data/raw/2026HTSRev21.json
    python diff.py --latest          # the two newest downloaded releases
    python diff.py --all             # every consecutive pair (oldest -> newest)
    add --appendix-b to any of these to also show which Appendix B items each change touches

Output:
    data/diffs/changes_<old>_<new>.csv   one row per change

Change types:
    added, deleted          a code appears / disappears
    renumbered              a deleted code with one clear new replacement in the same group
    split                   a deleted code with several clear new replacements
    possible_split          a deleted code with new codes in the same group but no clear match
                            (a person should check)
    desc_changed            the line's own wording changed
    rate_changed            a duty rate changed (only where the rate is written, usually 8-digit)
    units_changed           the unit of quantity changed
    footnote_changed        the footnotes changed

Categories (for ranking later):
    structural   added, deleted, renumbered, split, possible_split
    description  desc_changed
    rate         rate_changed, and footnote changes that only point to Chapter 99
    other        units_changed, other footnote changes
"""
import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

try:
    from rapidfuzz import fuzz
except ImportError:  # falls back to Python's built-in difflib
    fuzz = None

RAW = Path("data/raw")
OUT = Path("data/diffs")
RATE_FIELDS = ("general", "special", "other")
SPLIT_MATCH = 85     # similarity (0-100) at or above which a new code counts as a replacement
CH99 = re.compile(r"\b99\d{2}\.\d{2}(?:\.\d{2})?(?:\.?\d{2})?")

COLUMNS = ["from_release", "to_release", "code", "code_display", "level", "chapter",
           "change_type", "category", "field", "old_value", "new_value",
           "related_codes", "match_score", "description", "full_description"]
CATEGORY = {"added": "structural", "deleted": "structural", "renumbered": "structural",
            "split": "structural", "possible_split": "structural",
            "desc_changed": "description", "rate_changed": "rate",
            "units_changed": "other", "footnote_changed": "other"}


# ---------- Step 1: one clean table per release ----------

def clean(text):
    """Trim and collapse whitespace so formatting never shows up as a change."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def fmt(code):
    """'8707100040' -> '8707.10.00.40' (dots back in, for people to read)."""
    parts = [code[:4], code[4:6], code[6:8], code[8:10]]
    return ".".join(p for p in parts if p)


def footnote_text(footnotes):
    values = [clean(f.get("value")) for f in footnotes or [] if isinstance(f, dict)]
    return " | ".join(sorted(v for v in values if v))


def load_release(path):
    """
    Return {code: row} for every numbered line in one release.

    Header rows with no code (e.g. "Horses:") are not returned, but their text is
    kept in each child's full_description. 10-digit lines inherit the rates of the
    line above them that states rates (usually the 8-digit line).
    """
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    table = {}
    desc_by_indent = {}    # indent -> description of the latest line at that depth
    rates_by_indent = {}   # indent -> rates of the latest line at that depth that states rates
    duplicates = 0

    for row in rows:
        indent = int(row.get("indent") or 0)
        desc = clean(row.get("description"))
        for stack in (desc_by_indent, rates_by_indent):   # forget anything at this depth or deeper
            for k in [k for k in stack if k >= indent]:
                del stack[k]
        desc_by_indent[indent] = desc

        rates = {f: clean(row.get(f)) for f in RATE_FIELDS}
        stated = any(rates.values())
        if stated:
            rates_by_indent[indent] = rates

        code = clean(row.get("htsno")).replace(".", "")
        if not code.isdigit():
            continue          # header row: used only for full_description above
        if code in table:
            duplicates += 1
            continue

        inherited = rates_by_indent[max(rates_by_indent)] if rates_by_indent else {}
        table[code] = {
            "code": code,
            "level": len(code),
            "description": desc,
            "full_description": " > ".join(desc_by_indent[k] for k in sorted(desc_by_indent)),
            "stated": stated,
            **{f: rates[f] for f in RATE_FIELDS},                          # as written
            **{f"eff_{f}": inherited.get(f, "") for f in RATE_FIELDS},     # after inheriting
            "units": ", ".join(clean(u) for u in row.get("units") or []),
            "footnotes": footnote_text(row.get("footnotes")),
        }
    if duplicates:
        print(f"  note: {duplicates} repeated codes in {Path(path).name} (kept the first)")
    return table


# ---------- Steps 2-4: compare two tables ----------

def similarity(a, b):
    """0-100: how alike two descriptions are, ignoring word order."""
    if fuzz:
        return round(fuzz.token_set_ratio(a, b))
    a, b = " ".join(sorted(set(a.lower().split()))), " ".join(sorted(set(b.lower().split())))
    return round(100 * SequenceMatcher(None, a, b).ratio())


def group_of(code):
    """The parent group to search for replacements: 10-digit -> 8, 8 -> 6, 6 -> 4."""
    return code[:max(4, len(code) - 2)]


def make_row(rel, item, change_type, **extra):
    row = {
        "from_release": rel[0], "to_release": rel[1],
        "code": item["code"], "code_display": fmt(item["code"]),
        "level": item["level"], "chapter": item["code"][:2],
        "change_type": change_type, "category": CATEGORY[change_type],
        "field": "", "old_value": "", "new_value": "", "related_codes": "", "match_score": "",
        "description": item["description"], "full_description": item["full_description"],
    }
    row.update(extra)
    return row


def diff(old, new, rel=("old", "new")):
    """Return a list of change rows (dicts with COLUMNS keys)."""
    changes = []
    deleted = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    added_by_group = {}
    for c in added:
        added_by_group.setdefault((group_of(c), len(c)), []).append(c)

    # Deleted codes, paired with likely replacements (Step 4)
    replaces = {}   # new code -> old code it probably replaces
    for c in deleted:
        candidates = added_by_group.get((group_of(c), len(c)), [])
        if not candidates:
            changes.append(make_row(rel, old[c], "deleted"))
            continue
        scored = sorted(((similarity(old[c]["description"], new[n]["description"]), n)
                         for n in candidates), reverse=True)
        strong = [n for s, n in scored if s >= SPLIT_MATCH]
        if len(strong) == 1:
            kind, related, score = "renumbered", strong, scored[0][0]
        elif strong:
            kind, related, score = "split", strong, min(s for s, n in scored if n in strong)
        else:   # new codes appeared in the same group, but none clearly matches
            kind, related, score = "possible_split", [n for _, n in scored], scored[0][0]
        for n in related:
            replaces.setdefault(n, c)
        changes.append(make_row(rel, old[c], kind, match_score=score,
                                related_codes="; ".join(fmt(n) for n in sorted(related))))

    # Added codes
    for c in added:
        related = fmt(replaces[c]) if c in replaces else ""
        changes.append(make_row(rel, new[c], "added", related_codes=related))

    # Codes in both releases: compare field by field (Step 3)
    for c in sorted(set(old) & set(new)):
        o, n = old[c], new[c]
        if o["description"] != n["description"]:
            changes.append(make_row(rel, n, "desc_changed", field="description",
                                    old_value=o["description"], new_value=n["description"]))
        if o["stated"] or n["stated"]:   # only where a rate is written, so children don't repeat it
            for f in RATE_FIELDS:
                if o[f] != n[f]:
                    changes.append(make_row(rel, n, "rate_changed", field=f,
                                            old_value=o[f], new_value=n[f]))
        if o["units"] != n["units"]:
            changes.append(make_row(rel, n, "units_changed", field="units",
                                    old_value=o["units"], new_value=n["units"]))
        if o["footnotes"] != n["footnotes"]:
            only_ch99 = bool(CH99.search(o["footnotes"] + n["footnotes"])) and \
                CH99.sub("", o["footnotes"]) == CH99.sub("", n["footnotes"])
            changes.append(make_row(rel, n, "footnote_changed", field="footnotes",
                                    category="rate" if only_ch99 else "other",
                                    old_value=o["footnotes"], new_value=n["footnotes"]))
    return changes


# ---------- Optional: which Appendix B items does each change touch? ----------

def appendix_b_items(code, items):
    """Item numbers whose rules overlap this code. Works for 4-, 6-, 8- and 10-digit codes."""
    lo, hi = code.ljust(10, "0"), code.ljust(10, "9")
    hits = set()
    for it in items:
        for s in it.specs:
            if s.lo <= hi and lo <= s.hi:
                if lo == hi and any(e.matches(lo) for e in s.excludes):
                    continue    # a 10-digit code that the rule explicitly excludes
                hits.add(it.num)
    return sorted(hits)


def add_appendix_b(changes):
    from appendix_b import load_rules
    items = load_rules()
    for ch in changes:
        codes = [ch["code"]] + [c.replace(".", "") for c in ch["related_codes"].split("; ") if c]
        hits = sorted({n for c in codes for n in appendix_b_items(c, items)})
        ch["appendix_b_items"] = "; ".join(map(str, hits))


# ---------- Running it ----------

def release_order():
    """Downloaded release files, oldest first (dates from releases_2025_2026.csv)."""
    dates = {}
    with open("releases_2025_2026.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            dates[row["name"]] = datetime.strptime(row["effective_start"], "%m/%d/%Y")
    have = [p for p in RAW.glob("*.json") if p.stem in dates]
    return sorted(have, key=lambda p: dates[p.stem])


def run_pair(old_path, new_path, with_appendix_b=False):
    old_path, new_path = Path(old_path), Path(new_path)
    rel = (old_path.stem, new_path.stem)
    print(f"{rel[0]} -> {rel[1]}")
    changes = diff(load_release(old_path), load_release(new_path), rel)
    columns = list(COLUMNS)
    if with_appendix_b:
        add_appendix_b(changes)
        columns.append("appendix_b_items")

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"changes_{rel[0]}_{rel[1]}.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(changes)

    counts = Counter(ch["change_type"] for ch in changes)
    print(f"  {len(changes)} changes: " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    if with_appendix_b:
        touched = sum(1 for ch in changes if ch["appendix_b_items"])
        print(f"  {touched} touch Appendix B")
    print(f"  saved {out}")
    return changes


def main():
    ap = argparse.ArgumentParser(description="Compare two HTS releases.")
    ap.add_argument("files", nargs="*", help="old.json new.json")
    ap.add_argument("--latest", action="store_true", help="diff the two newest downloaded releases")
    ap.add_argument("--all", action="store_true", help="diff every consecutive downloaded pair")
    ap.add_argument("--appendix-b", action="store_true", help="add an appendix_b_items column")
    args = ap.parse_args()

    if len(args.files) == 2:
        pairs = [tuple(args.files)]
    elif args.latest or args.all:
        files = release_order()
        if len(files) < 2:
            ap.error("need at least 2 release files in data/raw (run download_hts.py)")
        pairs = list(zip(files, files[1:])) if args.all else [tuple(files[-2:])]
    else:
        ap.error("give two files, or use --latest or --all")

    for old_path, new_path in pairs:
        run_pair(old_path, new_path, args.appendix_b)


if __name__ == "__main__":
    main()

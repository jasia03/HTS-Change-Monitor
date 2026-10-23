"""
For every Appendix B rule that matches nothing in the newest HTS file:
  - find the last downloaded release where it still matched,
  - the first release where it no longer did,
  - and the new codes added nearby in that release (likely replacements).
Also prints how codes under 8707.10 changed (the split named in CPSC's memo).

Uses whatever files are in data/raw. More files = more precise answers.

Usage:
    python trace_dead_codes.py
Output:
    data/dead_code_trace.csv
"""
import csv
import json
from datetime import datetime
from pathlib import Path

from appendix_b import load_rules

RAW = Path("data/raw")


def release_order():
    """Downloaded release names, oldest first (dates from releases_2025_2026.csv)."""
    dates = {}
    with open("releases_2025_2026.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            dates[row["name"]] = datetime.strptime(row["effective_start"], "%m/%d/%Y")
    have = [p.stem for p in RAW.glob("*.json") if p.stem in dates]
    return sorted(have, key=dates.get)


def load(name):
    """{code10: description} for all 10-digit lines except chapter 99."""
    out = {}
    for row in json.loads((RAW / f"{name}.json").read_text(encoding="utf-8")):
        d = (row.get("htsno") or "").replace(".", "")
        if len(d) == 10 and d.isdigit() and not d.startswith("99"):
            out[d] = (row.get("description") or "").strip()
    return out


def fmt(c):
    return f"{c[:4]}.{c[4:6]}.{c[6:]}"


def main():
    names = release_order()
    if len(names) < 2:
        print("Need at least 2 files in data/raw.")
        return
    print("Releases used (oldest -> newest):", ", ".join(names))
    snaps = {n: load(n) for n in names}
    latest = snaps[names[-1]]
    items = load_rules()

    rows = []
    print("\nDEAD RULES")
    for it in items:
        for s in it.specs:
            if any(s.matches(c) for c in latest):
                continue
            present = [any(s.matches(c) for c in snaps[n]) for n in names]
            if not any(present):
                rows.append([it.num, s.raw, "", "", "Not in any downloaded release (gone before "
                             f"{names[0]}, or a typo in Appendix B)", "", ""])
                print(f"  item {it.num} {s.raw}: not in any downloaded release")
                continue
            last = max(i for i, p in enumerate(present) if p)
            before, after = names[last], names[last + 1]
            gone = sorted(c for c in snaps[before] if s.matches(c))
            prefix = s.lo[:6]  # look for new codes in the same 6-digit subheading,
            new = sorted(c for c in snaps[after] if c not in snaps[before] and c.startswith(prefix))
            if not new:        # then widen to the 4-digit heading
                new = sorted(c for c in snaps[after] if c not in snaps[before] and c.startswith(s.lo[:4]))
            rows.append([it.num, s.raw, before, after,
                         f"Removed between {before} and {after}",
                         "; ".join(f"{fmt(c)} {snaps[before][c]}" for c in gone),
                         "; ".join(f"{fmt(c)} {snaps[after][c]}" for c in new)])
            print(f"  item {it.num} {s.raw}: last seen {before}, gone in {after}")
            for c in new[:6]:
                print(f"      new nearby: {fmt(c)}  {snaps[after][c][:70]}")

    Path("data").mkdir(exist_ok=True)
    with open("data/dead_code_trace.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "rule", "last_seen_in", "first_missing_in", "finding",
                    "codes_removed", "new_codes_nearby (possible replacements)"])
        w.writerows(rows)
    print("\nSaved data/dead_code_trace.csv")
    print("Note: gaps between downloaded releases mean 'gone in X' really means "
          "'gone somewhere between the previous file and X'.")

    print("\n8707.10 (vehicle bodies) across releases:")
    for n in names:
        codes = sorted(c for c in snaps[n] if c.startswith("870710"))
        print(f"  {n:<14} {', '.join(fmt(c) for c in codes)}")


if __name__ == "__main__":
    main()

"""
Label every change from diff.py with how much it matters to CPSC.

Labels (checked in this order; a change gets the first that fits):
    1             covered by an Appendix B rule
    needs_review  only matches a rule with a human condition ("where applies", "campers", ...)
    2             not covered, but in the same 6-digit subheading as a narrow Appendix B rule
    3             not near any rule, but its wording matches the CPSC product vocabulary
    not_relevant  none of the above (still listed in the report)

Priority (1 = most urgent), by how badly the change can break targeting:
    1  split, possible_split, renumbered, deleted   (a code CPSC may rely on stops existing)
    2  added                                         (may need adding to Appendix B)
    3  desc_changed                                  (products under the code may have changed)
    4  rate, units, footnote changes                 (usually informational)

Usage:
    python relevance.py data/diffs/changes_2026HTSRev20_2026HTSRev21.csv
    python relevance.py --latest        # newest file in data/diffs
    python relevance.py --all           # every file in data/diffs
Output:
    data/scored/scored_<old>_<new>.csv   sorted most important first
"""
import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from appendix_b import load_rules

DIFFS = Path("data/diffs")
OUT = Path("data/scored")
VOCAB = Path("cpsc_vocabulary.csv")
DECISIONS = Path("data/feedback/decisions.csv")

TIER_ORDER = {"1": 0, "needs_review": 1, "2": 2, "3": 3, "not_relevant": 4}
PRIORITY = {"split": 1, "possible_split": 1, "renumbered": 1, "deleted": 1,
            "added": 2, "desc_changed": 3,
            "rate_changed": 4, "units_changed": 4, "footnote_changed": 4}


def fmt(code):
    parts = [code[:4], code[4:6], code[6:8], code[8:10]]
    return ".".join(p for p in parts if p)


# ---------- inputs ----------

def load_vocab(path=VOCAB):
    """[(category, phrase, regex)]. Matches whole words, allowing a plural 's'/'es'."""
    vocab = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            phrase = row["phrase"].strip().lower()
            if phrase:
                pattern = re.compile(r"\b" + re.escape(phrase) + r"(?:e?s)?\b", re.IGNORECASE)
                vocab.append((row["category"].strip(), phrase, pattern))
    return vocab


def change_codes(change):
    """The changed code plus any related codes (e.g. the new codes a split created)."""
    related = [c.replace(".", "") for c in change.get("related_codes", "").split("; ") if c]
    return [change["code"]] + related


# ---------- matching ----------

def rule_matches(code, items):
    """
    (hits, excluded) for one code of any length.
    hits:     [(item, spec)] whose rule overlaps the code
    excluded: [(item, spec)] whose rule contains the code but explicitly excludes it
    """
    lo, hi = code.ljust(10, "0"), code.ljust(10, "9")
    hits, excluded = [], []
    for it in items:
        for s in it.specs:
            if s.lo <= hi and lo <= s.hi:
                if lo == hi and any(e.matches(lo) for e in s.excludes):
                    excluded.append((it, s))
                else:
                    hits.append((it, s))
    return hits, excluded


def near_rules(code, items):
    """Narrow rules (inside one 6-digit subheading) that share this code's subheading."""
    if len(code) < 6:
        return []
    return [(it, s) for it in items for s in it.specs
            if s.lo[:6] == s.hi[:6] == code[:6]]


def vocab_match(change, vocab):
    text = " ".join([change.get("full_description", ""), change.get("new_value", "")])
    for category, phrase, pattern in vocab:
        if pattern.search(text):
            return category, phrase
    return None


# ---------- the label ----------

def classify(change, items, vocab):
    """Return (tier, reason, appendix_b_items) for one change."""
    codes = change_codes(change)
    if change["code"].startswith("99"):
        return "not_relevant", "Chapter 99 line (temporary tariff provision, not a product code)", ""

    firm, conditional, excluded = [], [], []
    for c in codes:
        hits, exc = rule_matches(c, items)
        firm += [(c, it, s) for it, s in hits if not s.qualifier]
        conditional += [(c, it, s) for it, s in hits if s.qualifier]
        excluded += [(c, it, s) for it, s in exc]
    item_nums = "; ".join(str(n) for n in sorted({it.num for _, it, _ in firm + conditional}))

    if firm:
        c, it, s = firm[0]
        who = "" if c == change["code"] else f"related code {fmt(c)} "
        return "1", f"{who}covered by Appendix B item {it.num} (rule {s.raw}: {it.description})", item_nums

    if conditional:
        c, it, s = conditional[0]
        return ("needs_review",
                f"matches item {it.num} rule {s.raw}, which only applies with a condition "
                f"[{s.qualifier}]; a person must decide", item_nums)

    if excluded:
        c, it, s = excluded[0]
        return "not_relevant", f"explicitly excluded by Appendix B item {it.num} (rule {s.raw})", ""

    for c in codes:
        near = near_rules(c, items)
        if near:
            it, s = near[0]
            return ("2", f"not covered, but in the same subheading ({fmt(c[:6])}) as watched "
                         f"rule {s.raw} (item {it.num}); check whether it should be added", "")

    hit = vocab_match(change, vocab)
    if hit:
        category, phrase = hit
        return "3", f"description mentions '{phrase}' ({category}); check whether it is in CPSC scope", ""

    return "not_relevant", "no Appendix B rule, nearby rule, or CPSC product wording", ""


# ---------- reviewer decisions (from feedback.py) ----------

def load_decisions(path=DECISIONS):
    """
    (exact, by_code):
      exact    {(from, to, code, change_type, field): decision}  answers about this very change
      by_code  {(code, tool_tier): newest 'wrong' decision}  remembered for future releases, but only
               when the tool gives that code the same label again (same question, same answer)
    """
    exact, by_code = {}, {}
    if not Path(path).exists():
        return exact, by_code
    with open(path, encoding="utf-8-sig") as f:
        for d in csv.DictReader(f):
            code = d["code"].replace(".", "")
            exact[(d["from_release"], d["to_release"], code, d["change_type"], d["field"])] = d
            if d["verdict"] == "wrong" and d["correct_tier"] in TIER_ORDER:
                key = (code, d["tool_tier"])
                if key not in by_code or d["reviewed_at"] > by_code[key]["reviewed_at"]:
                    by_code[key] = d
    return exact, by_code


def apply_decision(ch, decisions):
    """Override the tool's tier with a reviewer's decision, keeping the tool's answer in tool_tier."""
    exact, by_code = decisions
    ch["tool_tier"], ch["reviewed"] = ch["tier"], ""
    who = lambda d: (d.get("reviewer") or "a reviewer") + f" ({d['reviewed_at'][:10]})"
    note = lambda d: f": {d['note']}" if d.get("note") else ""
    d = exact.get((ch.get("from_release", ""), ch.get("to_release", ""), ch["code"],
                   ch["change_type"], ch.get("field", "")))
    if d and d["verdict"] == "correct":
        ch["reviewed"] = "confirmed"
    elif d and d["verdict"] == "wrong" and d["correct_tier"] in TIER_ORDER:
        ch["tier"], ch["reviewed"] = d["correct_tier"], "corrected"
        ch["reason"] = f"Corrected by {who(d)}{note(d)}. Tool said: {ch['reason']}"
    elif (ch["code"], ch["tool_tier"]) in by_code:
        d = by_code[(ch["code"], ch["tool_tier"])]
        ch["tier"], ch["reviewed"] = d["correct_tier"], "remembered"
        ch["reason"] = (f"Set by an earlier review of this code by {who(d)}{note(d)}. "
                        f"Tool said: {ch['reason']}")


def score(changes, items, vocab, decisions=None):
    decisions = decisions or ({}, {})
    for ch in changes:
        tier, reason, item_nums = classify(ch, items, vocab)
        ch["tier"] = tier
        ch["priority"] = str(PRIORITY.get(ch["change_type"], 4))
        ch["reason"] = reason
        ch["appendix_b_items"] = item_nums
        apply_decision(ch, decisions)
    changes.sort(key=lambda c: (TIER_ORDER[c["tier"]], int(c["priority"]), c["code"]))
    return changes


# ---------- running it ----------

def run_file(path, items, vocab, decisions=None):
    path = Path(path)
    with open(path, encoding="utf-8-sig") as f:
        changes = list(csv.DictReader(f))     # every value stays text: leading zeros are safe
    if not changes:
        print(f"{path.name}: no changes")
        return []
    score(changes, items, vocab, decisions)

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / path.name.replace("changes_", "scored_")
    first = ["tier", "priority", "code_display", "change_type", "reason", "appendix_b_items",
             "tool_tier", "reviewed"]
    columns = first + [k for k in changes[0] if k not in first]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(changes)

    counts = Counter(c["tier"] for c in changes)
    reviewed = Counter(c["reviewed"] for c in changes if c["reviewed"])
    print(f"{path.name}: {len(changes)} changes -> " +
          ", ".join(f"{t} {counts[t]}" for t in TIER_ORDER if counts[t]) +
          (" (reviewer decisions: " + ", ".join(f"{k} {v}" for k, v in reviewed.items()) + ")"
           if reviewed else ""))
    for c in [c for c in changes if c["tier"] == "1"][:5]:
        print(f"  Tier 1  {c['change_type']:<15} {c['code_display']:<14} {c['reason'][:70]}")
    print(f"  saved {out}")
    return changes


def main():
    ap = argparse.ArgumentParser(description="Label HTS changes by CPSC relevance.")
    ap.add_argument("file", nargs="?", help="a changes_*.csv file from diff.py")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    files = sorted(DIFFS.glob("changes_*.csv"), key=lambda p: p.stat().st_mtime)
    if args.file:
        files = [Path(args.file)]
    elif args.latest and files:
        files = files[-1:]
    elif not args.all:
        ap.error("give a changes file, or use --latest or --all")
    if not files:
        ap.error("no files in data/diffs (run diff.py first)")

    items, vocab, decisions = load_rules(), load_vocab(), load_decisions()
    if decisions[0]:
        print(f"Applying {len(decisions[0])} reviewer decisions from {DECISIONS}")
    for p in files:
        run_file(p, items, vocab, decisions)


if __name__ == "__main__":
    main()

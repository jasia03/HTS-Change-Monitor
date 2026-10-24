"""
Collect reviewers' Right/Wrong answers from the report, and measure how often the tool was right.

Reviewers click "Download review" in report.html, which saves review_<old>_<new>.csv.
Put those files in data/feedback/inbox/, then:

    python feedback.py import          # merge every file in the inbox into decisions.csv
    python feedback.py import a.csv b.csv
    python feedback.py stats           # how often each tier was right

After importing, rerun relevance.py (and summarize.py, report.py): corrected labels are applied,
and a code a reviewer moved keeps its new label in future releases when the tool would give it
the same label again.

Files:
    data/feedback/inbox/        downloaded review files go here
    data/feedback/decisions.csv every decision, one row per change (newest answer wins)
"""
import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

INBOX = Path("data/feedback/inbox")
DECISIONS = Path("data/feedback/decisions.csv")
COLUMNS = ["from_release", "to_release", "code", "change_type", "field", "tool_tier",
           "verdict", "correct_tier", "note", "reviewer", "reviewed_at"]
TIERS = ["1", "needs_review", "2", "3", "not_relevant"]


def key(d):
    return (d["from_release"], d["to_release"], d["code"].replace(".", ""), d["change_type"], d["field"])


def read(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    missing = set(COLUMNS) - set(rows[0].keys()) if rows else set()
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
    return rows


def load():
    return {key(d): d for d in read(DECISIONS)} if DECISIONS.exists() else {}


def save(decisions):
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with DECISIONS.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(decisions.values(), key=lambda d: (d["to_release"], d["code"])))


def import_files(paths):
    decisions = load()
    added = updated = skipped = 0
    for p in paths:
        for d in read(p):
            if d["verdict"] not in ("correct", "wrong"):
                skipped += 1
                continue
            if d["verdict"] == "wrong" and d["correct_tier"] not in TIERS:
                skipped += 1           # "wrong" without saying what it should be: can't be applied
                continue
            k = key(d)
            if k not in decisions:
                decisions[k] = d
                added += 1
            elif d["reviewed_at"] > decisions[k]["reviewed_at"]:
                decisions[k] = d
                updated += 1
        print(f"  read {p}")
    save(decisions)
    print(f"{added} new, {updated} updated, {skipped} skipped (no verdict, or 'Wrong' without a label). "
          f"{len(decisions)} decisions in {DECISIONS}")
    if skipped:
        print("Tip: when marking a label Wrong, choose what it should be, or it can't be used.")


def stats():
    decisions = list(load().values())
    if not decisions:
        print(f"No decisions yet. Import some first: python feedback.py import")
        return
    by_tier = defaultdict(Counter)
    moved = Counter()
    for d in decisions:
        by_tier[d["tool_tier"]][d["verdict"]] += 1
        if d["verdict"] == "wrong":
            moved[(d["tool_tier"], d["correct_tier"])] += 1

    print(f"{len(decisions)} reviewed labels\n")
    print(f"{'Tool said':<14}{'reviewed':>9}{'right':>7}{'wrong':>7}{'% right':>9}")
    for t in TIERS:
        c = by_tier.get(t)
        if not c:
            continue
        n = c["correct"] + c["wrong"]
        print(f"{t:<14}{n:>9}{c['correct']:>7}{c['wrong']:>7}{100 * c['correct'] / n:>8.0f}%")
    if moved:
        print("\nWhen the tool was wrong, reviewers said it should be:")
        for (a, b), n in moved.most_common():
            print(f"  {a:<14} -> {b:<14} {n}")
    print("\nFor CPSC, 'Tool said 1 / % right' is precision for Tier 1. A low % right for "
          "'not_relevant' means the tool is missing CPSC changes.")


def main():
    ap = argparse.ArgumentParser(description="Merge reviewer answers and measure accuracy.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="merge downloaded review files into decisions.csv")
    imp.add_argument("files", nargs="*")
    sub.add_parser("stats", help="how often each tier was right")
    args = ap.parse_args()

    if args.cmd == "import":
        files = args.files or sorted(INBOX.glob("*.csv"))
        if not files:
            ap.error(f"no files given and none in {INBOX}/")
        import_files(files)
    else:
        stats()


if __name__ == "__main__":
    main()

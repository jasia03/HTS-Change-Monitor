"""
Validate Appendix B rules against an HTS snapshot (risk mitigation from the plan:
"validate every parsed code against the HTS itself").

For each rule it reports how many HTS 10-digit lines it covers. A rule covering
zero lines is either a typo in Appendix B or a code USITC has since deleted —
exactly the kind of drift this project exists to catch.

Usage:
    python validate_appendix_b.py data/raw/2026HTSRev21.json
Outputs:
    data/appendix_b_validation.csv   one row per rule
    data/appendix_b_coverage.csv     every covered 10-digit HTS line (the expanded list)
"""
import csv
import json
import sys
from pathlib import Path

from appendix_b import load_rules


def stat_lines(snapshot_path):
    """Yield (code10, description) for every 10-digit statistical line."""
    for row in json.loads(Path(snapshot_path).read_text(encoding="utf-8")):
        d = (row.get("htsno") or "").replace(".", "")
        if len(d) == 10 and d.isdigit() and not d.startswith("99"):
            yield d, (row.get("description") or "").strip()


def main(snapshot):
    items = load_rules()
    lines = list(stat_lines(snapshot))
    print(f"{snapshot}: {len(lines)} ten-digit lines (excluding chapter 99)")

    out = Path("data")
    out.mkdir(exist_ok=True)
    covered = {}
    dead = []
    with open(out / "appendix_b_validation.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "rule", "kind", "qualifier", "lines_covered", "status"])
        for it in items:
            for s in it.specs:
                hits = [c for c, _ in lines if s.matches(c)]
                for c in hits:
                    covered.setdefault(c, []).append(it.num)
                status = "OK" if hits else "NO MATCH - stale code or typo?"
                if not hits:
                    dead.append((it.num, s.raw))
                w.writerow([it.num, s.raw, s.kind, s.qualifier, len(hits), status])

    desc = dict(lines)
    with open(out / "appendix_b_coverage.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["hts10", "description", "appendix_b_items"])
        for c in sorted(covered):
            w.writerow([f"{c[:4]}.{c[4:6]}.{c[6:]}", desc[c], ";".join(map(str, sorted(set(covered[c]))))])

    print(f"Appendix B covers {len(covered)} of {len(lines)} ten-digit lines "
          f"({100 * len(covered) / len(lines):.1f}%)")
    print(f"{len(dead)} rules match nothing:")
    for num, raw in dead:
        print(f"  item {num}: {raw}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if not Path(sys.argv[1]).exists():
        files = sorted(Path("data/raw").glob("*.json")) if Path("data/raw").exists() else []
        print(f"File not found: {sys.argv[1]}")
        print("Files available:" if files else "No files in data/raw. Run: python download_hts.py")
        for f in files:
            print(f"  {f}")
        sys.exit(1)
    main(sys.argv[1])

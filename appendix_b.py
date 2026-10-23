"""
Parse CPSC/CBP ACE MOU Appendix B (July 2026) into machine-checkable rules,
and test whether any HTS code is covered by them.

Appendix B is NOT a flat list of ~600 10-digit codes. It is 65 line items mixing:
  - whole chapters            "Chapter 95 inclusive"
  - headings / subheadings    "2404", "3006.50", "9304.00"
  - full/partial stat codes   "1704.90.3550", "8501.31.81xx" (xx = any)
  - ranges                    "2806-2843", "4421.10.0000-4421.91.8800"
  - exclusions                "3926 (except 3926.20.1010 and 3926.90.3000)"
  - human qualifiers          "where applies", "(people only)", "(campers)"
So coverage must be evaluated as rules, not by set membership.

Usage:
    python appendix_b.py                      # writes appendix_b_rules.csv, prints warnings
    from appendix_b import load_rules, covered_by
"""
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / "appendix_b_raw.txt"

CODE = r"\d{4}(?:\.\d{2}(?:\.[\dx]{2}(?:[\dx]{2})?)?)?"
QUALIFIER_WORDS = ["where applies", "people only", "off road", "campers",
                   "portion of child safety seats", "where not CPSC",
                   "aircraft", "automotive"]


def digits(code: str) -> str:
    """'8501.31.81xx' -> '85013181xx'"""
    return code.replace(".", "").strip()


@dataclass
class Spec:
    kind: str            # chapter | prefix | range
    lo: str              # 10-char lower bound (digits)
    hi: str              # 10-char upper bound (digits)
    raw: str
    qualifier: str = ""
    excludes: list = field(default_factory=list)   # list[Spec]

    def matches(self, code10: str) -> bool:
        if not (self.lo <= code10 <= self.hi):
            return False
        return not any(e.matches(code10) for e in self.excludes)


def bounds(code: str):
    d = digits(code).replace("x", "")
    return d.ljust(10, "0"), d.ljust(10, "9")


def make_spec(token: str, qualifier: str = "") -> Spec:
    token = token.strip()
    m = re.fullmatch(r"Chapter (\d{2}) inclusive", token)
    if m:
        ch = m.group(1)
        return Spec("chapter", ch.ljust(10, "0"), ch.ljust(10, "9"), token, qualifier)
    m = re.fullmatch(rf"({CODE})\s*-\s*({CODE})", token)
    if m:
        lo, _ = bounds(m.group(1))
        _, hi = bounds(m.group(2))
        return Spec("range", lo, hi, token, qualifier)
    if re.fullmatch(CODE, token):
        lo, hi = bounds(token)
        return Spec("prefix", lo, hi, token, qualifier)
    raise ValueError(f"Unparseable code token: {token!r}")


def split_top_level(s: str):
    """Split on commas not inside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in s:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [p.strip() for p in out if p.strip()]


@dataclass
class Item:
    num: int
    description: str
    specs: list
    warnings: list


def parse_item(line: str) -> Item:
    m = re.match(r"(\d+)\.\s*(.*?)\s*\|\s*(.*)", line)
    num, codes, desc = int(m.group(1)), m.group(2), m.group(3)
    specs, warnings = [], []
    for part in split_top_level(codes):
        paren = re.search(r"\((.*)\)", part)
        inner = paren.group(1) if paren else ""
        body = re.sub(r"\(.*\)", "", part).strip()
        qual = []
        for w in QUALIFIER_WORDS:
            if w in body:
                qual.append(w)
                body = body.replace(w, "").strip()
            if w in inner:
                qual.append(w)
        # Defect: two codes separated only by a space (missing comma or dash)
        bare = re.findall(CODE, body)
        if len(bare) == 2 and "-" not in body:
            warnings.append(f"'{part}': two codes with no separator; parsed as two prefixes")
            for b in bare:
                specs.append(make_spec(b, "; ".join(qual)))
            continue
        spec = make_spec(body, "; ".join(qual))
        if inner.startswith("except"):
            ex_text = inner[len("except"):]
            for ex in re.findall(rf"{CODE}\s*-\s*{CODE}|{CODE}", ex_text):
                spec.excludes.append(make_spec(ex))
        if spec.kind == "range" and spec.lo[:4] != spec.hi[:4] and "." in body.split("-")[0]:
            if digits(body.split("-")[0])[:4] != digits(body.split("-")[1])[:4] \
                    and len(digits(body.split("-")[0])) > 4 and len(digits(body.split("-")[1].strip())) > 4:
                warnings.append(f"'{body}': range crosses headings at stat-code level; possible typo")
        if spec.lo > spec.hi:
            warnings.append(f"'{body}': lower bound > upper bound")
        if qual:
            warnings.append(f"'{part.strip()}': human qualifier [{'; '.join(qual)}] -> needs manual review")
        specs.append(spec)
    return Item(num, desc, specs, warnings)


def load_rules(path: Path = RAW):
    return [parse_item(l) for l in path.read_text().splitlines() if l.strip()]


def covered_by(code: str, items) -> list:
    """Return list of (item_num, spec.raw, qualifier) covering an HTS code."""
    d = digits(code)
    if not d.isdigit() or len(d) < 4:
        return []
    lo, hi = d.ljust(10, "0"), d.ljust(10, "9")
    return [(it.num, s.raw, s.qualifier) for it in items for s in it.specs if s.lo <= hi and lo <= s.hi]


def write_csv(items, out: Path):
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "description", "kind", "raw", "lo", "hi",
                    "excludes", "qualifier", "needs_review"])
        for it in items:
            for s in it.specs:
                w.writerow([it.num, it.description, s.kind, s.raw, s.lo, s.hi,
                            "; ".join(e.raw for e in s.excludes), s.qualifier,
                            "yes" if s.qualifier else ""])


if __name__ == "__main__":
    items = load_rules()
    write_csv(items, HERE / "appendix_b_rules.csv")
    n_specs = sum(len(i.specs) for i in items)
    print(f"{len(items)} items -> {n_specs} rules")
    kinds = {}
    for i in items:
        for s in i.specs:
            kinds[s.kind] = kinds.get(s.kind, 0) + 1
    print("by kind:", kinds)
    print("\nWARNINGS")
    for i in items:
        for w in i.warnings:
            print(f"  item {i.num}: {w}")
    # quick self-checks
    tests = {"9503.00.0073": True, "8707.10.0090": True, "8707.10.0040": False,
             "3926.20.1010": False, "3926.20.9050": True, "0101.21.0010": False,
             "8525.80.2000": False, "8525.89.1000": True}
    print("\nSELF-CHECK")
    ok = True
    for code, expect in tests.items():
        got = bool(covered_by(code, items))
        ok &= got == expect
        print(f"  {code}: covered={got} expected={expect} {'OK' if got == expect else 'FAIL'}")
    sys.exit(0 if ok else 1)

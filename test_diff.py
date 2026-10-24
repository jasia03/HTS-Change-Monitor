"""
Tests for diff.py using two tiny hand-made releases in USITC's JSON format.

Run:  python test_diff.py      (or: pytest test_diff.py)
"""
import json
import tempfile
from pathlib import Path

from diff import diff, load_release, appendix_b_items


def line(htsno, indent, desc, general="", units=None, footnotes=None):
    return {"htsno": htsno, "indent": str(indent), "description": desc,
            "superior": None, "units": units or [], "general": general,
            "special": "", "other": "", "footnotes": footnotes or []}


OLD = [
    line("8707", 0, "Bodies (including cabs), for the motor vehicles of headings 8701 to 8705:"),
    line("8707.10.00", 1, "For the vehicles of heading 8703", general="2.5%"),
    line("8707.10.00.20", 2, "For ambulances", units=["No."]),
    line("8707.10.00.40", 2, "Other", units=["No."]),
    line("", 0, "Toys:"),                                      # header row, no code
    line("9503.00.00", 1, "Tricycles, scooters, dolls; other toys", general="Free"),
    line("9503.00.00.73", 2, "Other toys, battery operated", units=["No."]),
    line("9503.00.00.90", 2, "Other", units=["No."]),
    line("9506.62.40", 1, "Inflatable balls", general="Free",
         footnotes=[{"columns": ["general"], "value": "See 9903.88.15.", "type": "endnote"}]),
    line("", 0, "Live horses:"),
    line("0101.21.00", 1, "Purebred breeding horses", general="Free"),
    line("0101.21.00.10", 2, "Males", units=["No."]),
]

NEW = [
    line("8707", 0, "Bodies (including cabs), for the motor vehicles of headings 8701 to 8705:"),
    line("8707.10.00", 1, "For the vehicles of heading 8703", general="2.5%"),
    line("8707.10.00.20", 2, "For ambulances", units=["No."]),
    line("8707.10.00.50", 2, "Other, of electric vehicles", units=["No."]),       # 0040 split
    line("8707.10.00.90", 2, "Other, other", units=["No."]),                      # into 0050 + 0090
    line("", 0, "Toys:"),
    line("9503.00.00", 1, "Tricycles, scooters, dolls; other toys", general="3%"),  # rate change
    line("9503.00.00.73", 2, "Other toys, battery-operated or electric", units=["No."]),
    line("9503.00.00.90", 2, "Other", units=["kg"]),                               # units change
    line("9506.62.40", 1, "Inflatable balls", general="Free",
         footnotes=[{"columns": ["general"], "value": "See 9903.88.16.", "type": "endnote"}]),
    line("", 0, "Live horses:"),
    line("0101.21.00", 1, "Purebred breeding horses", general="Free"),
    line("0101.21.00.20", 2, "Males", units=["No."]),                              # renumbered
]


def build():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "old.json").write_text(json.dumps(OLD), encoding="utf-8")
    (tmp / "new.json").write_text(json.dumps(NEW), encoding="utf-8")
    old, new = load_release(tmp / "old.json"), load_release(tmp / "new.json")
    return old, new, diff(old, new)


def by(changes, code, kind):
    return [c for c in changes if c["code"] == code and c["change_type"] == kind]


def test_header_rows_and_inheritance():
    old, _, _ = build()
    assert "" not in old                                       # header row is not a code
    t = old["9503000073"]
    assert t["full_description"] == "Toys: > Tricycles, scooters, dolls; other toys > Other toys, battery operated"
    assert t["eff_general"] == "Free" and t["general"] == ""   # inherited, not written
    assert old["8707100040"]["eff_general"] == "2.5%"


def test_split():
    _, _, ch = build()
    row = by(ch, "8707100040", "split") or by(ch, "8707100040", "possible_split")
    assert row, "8707.10.00.40 should be flagged as a split"
    assert "8707.10.00.50" in row[0]["related_codes"] and "8707.10.00.90" in row[0]["related_codes"]
    assert by(ch, "8707100050", "added")[0]["related_codes"] == "8707.10.00.40"


def test_renumbered():
    _, _, ch = build()
    row = by(ch, "0101210010", "renumbered")
    assert row and row[0]["related_codes"] == "0101.21.00.20"


def test_rate_reported_once():
    _, _, ch = build()
    rates = [c for c in ch if c["change_type"] == "rate_changed"]
    assert [(c["code"], c["old_value"], c["new_value"]) for c in rates] == [("95030000", "Free", "3%")]


def test_desc_units_and_ch99_footnote():
    _, _, ch = build()
    assert by(ch, "9503000073", "desc_changed")
    assert by(ch, "9503000090", "units_changed")[0]["new_value"] == "kg"
    fn = by(ch, "95066240", "footnote_changed")[0]
    assert fn["category"] == "rate"                            # only the Chapter 99 pointer moved


def test_unchanged_codes_not_reported():
    _, _, ch = build()
    assert not [c for c in ch if c["code"] in ("8707100020", "8707", "87071000")]


def test_appendix_b_overlap():
    from appendix_b import load_rules
    items = load_rules()
    assert appendix_b_items("87071000", items) == [57]        # 8-digit line containing 8707.10.0090
    assert appendix_b_items("8707100040", items) == []         # the old code was not listed
    assert appendix_b_items("9503000073", items) == [64]
    assert appendix_b_items("3926201010", items) == []         # explicitly excluded


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")

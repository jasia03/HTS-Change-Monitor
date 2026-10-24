"""
Tests for reviewer feedback: feedback.py import, and relevance.py applying decisions.

Run:  python test_feedback.py      (or: pytest test_feedback.py)
"""
import csv
import tempfile
from pathlib import Path

import feedback
from appendix_b import load_rules
from relevance import load_decisions, load_vocab, score
from report import build_alert, render_report

ITEMS, VOCAB = load_rules(), load_vocab()
HEAD = feedback.COLUMNS


def decision(code, verdict, correct="", tool="2", change_type="added", rel=("Rev10", "Rev11"),
             when="2026-10-23T10:00:00Z", note=""):
    return dict(zip(HEAD, [rel[0], rel[1], code, change_type, "", tool, verdict, correct, note, "JS", when]))


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HEAD)
        w.writeheader()
        w.writerows(rows)


def change(code, change_type="added", rel=("Rev10", "Rev11")):
    return {"code": code.replace(".", ""), "code_display": code, "change_type": change_type, "field": "",
            "related_codes": "", "full_description": "", "new_value": "",
            "from_release": rel[0], "to_release": rel[1]}


def with_tmp_feedback():
    tmp = Path(tempfile.mkdtemp())
    feedback.DECISIONS = tmp / "decisions.csv"
    return tmp


def test_import_keeps_newest_and_skips_unusable():
    tmp = with_tmp_feedback()
    write(tmp / "a.csv", [decision("8707.10.00.50", "wrong", "1", when="2026-10-23T10:00:00Z"),
                          decision("8707.10.00.30", "wrong", "")])          # no label: skipped
    write(tmp / "b.csv", [decision("8707.10.00.50", "correct", when="2026-10-23T11:00:00Z")])
    feedback.import_files([tmp / "a.csv", tmp / "b.csv"])
    saved = list(feedback.load().values())
    assert len(saved) == 1 and saved[0]["verdict"] == "correct"             # newer answer won


def test_exact_correction_and_confirmation():
    tmp = with_tmp_feedback()
    write(feedback.DECISIONS, [decision("8707.10.00.50", "wrong", "1", note="other half of split"),
                               decision("9503.00.00.73", "correct", tool="1", change_type="desc_changed")])
    d = load_decisions(feedback.DECISIONS)
    out = {c["code"]: c for c in score([change("8707.10.00.50"), change("9503.00.00.73", "desc_changed")],
                                       ITEMS, VOCAB, d)}
    a = out["8707100050"]
    assert (a["tier"], a["tool_tier"], a["reviewed"]) == ("1", "2", "corrected")
    assert "other half of split" in a["reason"]
    assert out["9503000073"]["reviewed"] == "confirmed"


def test_remembered_only_for_the_same_question():
    tmp = with_tmp_feedback()
    # reviewer: 8708.10.00.00 'needs_review' should be Covered
    write(feedback.DECISIONS, [decision("8708.10.00.00", "wrong", "1", tool="needs_review",
                                        change_type="rate_changed")])
    d = load_decisions(feedback.DECISIONS)
    later = score([change("8708.10.00.00", "desc_changed", rel=("Rev11", "Rev12"))], ITEMS, VOCAB, d)[0]
    assert (later["tier"], later["reviewed"]) == ("1", "remembered")
    # a code the tool labels differently is not overridden
    other = score([change("8707.10.00.50", "added", rel=("Rev11", "Rev12"))], ITEMS, VOCAB, d)[0]
    assert other["reviewed"] == ""


def test_report_exports_the_tools_original_label():
    c = change("8707.10.00.50")
    c.update(tier="1", tool_tier="2", reviewed="corrected", summary="s", reason="r", priority="2")
    html = render_report([c], build_alert([c], ("Rev10", "Rev11"), ""))
    assert 'data-tier="2"' in html and "corrected by a reviewer" in html
    assert 'id="export"' in html


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")

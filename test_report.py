"""
Tests for report.py.

Run:  python test_report.py      (or: pytest test_report.py)
"""
from report import build_alert, render_report


def change(code, tier, change_type="added", summary="Something changed.", related=""):
    return {"code": code.replace(".", ""), "code_display": code, "tier": tier,
            "change_type": change_type, "summary": summary, "reason": "why",
            "related_codes": related, "priority": "1"}


REL = ("2026HTSRev10", "2026HTSRev11")


def test_urgency_and_headline():
    red = build_alert([change("9503.00.00.73", "1"), change("0101.21.00.10", "not_relevant")], REL, "")
    assert red["urgency"] == "red" and red["headline"] == "1 change affects CPSC-watched codes"
    amber = build_alert([change("8707.10.00.30", "2"), change("8708.10.00.00", "needs_review")], REL, "")
    assert amber["urgency"] == "amber" and amber["headline"] == "2 changes may affect CPSC"
    grey = build_alert([change("0101.21.00.10", "not_relevant")], REL, "")
    assert grey["urgency"] == "grey" and grey["headline"] == "No changes affect CPSC-watched codes"


def test_split_is_drawn_and_text_is_escaped():
    changes = [change("8707.10.00.40", "1", "possible_split", summary="<b>x</b> & y",
                      related="8707.10.00.30; 8707.10.00.90")]
    html = render_report(changes, build_alert(changes, REL, "Overview"))
    assert 'class="lineage"' in html and "8707.10.00.30" in html and "8707.10.00.90" in html
    assert "&lt;b&gt;x&lt;/b&gt; &amp; y" in html and "<b>x</b>" not in html


def test_not_relevant_section_starts_folded():
    changes = [change("9503.00.00.73", "1"), change("0101.21.00.10", "not_relevant")]
    html = render_report(changes, build_alert(changes, REL, ""))
    assert '<details class="section" open><summary><h2>Act on these' in html
    assert '<details class="section"><summary><h2>Everything else' in html


def test_empty_release():
    html = render_report([], build_alert([], REL, ""))
    assert "The two releases are identical" in html


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")

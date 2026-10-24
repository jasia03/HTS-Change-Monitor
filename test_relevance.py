"""
Tests for relevance.py.

Run:  python test_relevance.py      (or: pytest test_relevance.py)
"""
from appendix_b import load_rules
from relevance import classify, load_vocab, score

ITEMS, VOCAB = load_rules(), load_vocab()


def change(code, change_type="desc_changed", related="", desc="", new_value=""):
    return {"code": code, "change_type": change_type, "related_codes": related,
            "full_description": desc, "new_value": new_value}


def tier(ch):
    return classify(ch, ITEMS, VOCAB)[0]


def test_tier_1_direct():
    assert tier(change("9503000073")) == "1"                 # Chapter 95 inclusive
    assert tier(change("87071000")) == "1"                   # 8-digit line holding 8707.10.0090


def test_tier_1_through_related_code():
    # the old code is not listed, but one of the codes it was split into is
    ch = change("8707100040", "possible_split", related="8707.10.00.50; 8707.10.00.90")
    t, reason, items = classify(ch, ITEMS, VOCAB)
    assert t == "1" and "8707.10.00.90" in reason and items == "57"


def test_needs_review():
    assert tier(change("8708100000")) == "needs_review"       # 8708 "where applies"


def test_tier_2_near_a_narrow_rule():
    t, reason, _ = classify(change("8707100040", "deleted"), ITEMS, VOCAB)
    assert t == "2" and "8707.10" in reason


def test_explicit_exclusion_is_not_relevant():
    t, reason, _ = classify(change("3926201010"), ITEMS, VOCAB)
    assert t == "not_relevant" and "excluded" in reason


def test_tier_3_wording():
    ch = change("9027894500", "added", desc="Instruments > Carbon monoxide alarms")
    t, reason, _ = classify(ch, ITEMS, VOCAB)
    assert t == "3" and "carbon monoxide alarm" in reason


def test_whole_words_only():
    # 'toy' must not match inside 'Toyota'; 'crib' must not match inside 'described'
    assert tier(change("0101210010", desc="Toyota parts described elsewhere")) == "not_relevant"


def test_not_relevant_and_chapter_99():
    assert tier(change("0101210010", desc="Purebred breeding horses > Males")) == "not_relevant"
    assert tier(change("9903881500", desc="toys")) == "not_relevant"


def test_engines_no_longer_covered():
    # the corrected item 55 range must not reach headings 8406-8408
    assert tier(change("8407210000")) != "1"


def test_sorting():
    changes = [change("0101210010", "added"),
               change("9503000073", "rate_changed"),
               change("9503000090", "deleted")]
    out = score(changes, ITEMS, VOCAB)
    assert [(c["tier"], c["priority"]) for c in out] == [("1", "1"), ("1", "4"), ("not_relevant", "2")]


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")

"""
Tests for summarize.py. Uses a fake Claude client, so no API key or internet is needed.

Run:  python test_summarize.py      (or: pytest test_summarize.py)
"""
import json
from types import SimpleNamespace

from summarize import passes_check, summarize, template_summary


def change(code_display, change_type, tier="1", **kw):
    ch = {"code": code_display.replace(".", ""), "code_display": code_display,
          "change_type": change_type, "tier": tier, "priority": "1", "category": "structural",
          "related_codes": "", "old_value": "", "new_value": "", "field": "", "reason": "",
          "description": "Other", "full_description": "Bodies > For the vehicles of heading 8703 > Other"}
    ch.update(kw)
    return ch


class FakeClient:
    """Pretends to be anthropic.Anthropic(); returns whatever `reply(items)` builds."""
    def __init__(self, reply):
        self.reply, self.calls = reply, 0
        self.messages = SimpleNamespace(create=self.create)

    def create(self, model, max_tokens, system, messages):
        self.calls += 1
        content = messages[0]["content"]
        text = self.reply(content) if content.startswith("[") else "Overview text with no numbers."
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_templates_cover_every_change_type():
    kinds = ["added", "deleted", "renumbered", "split", "possible_split",
             "desc_changed", "rate_changed", "units_changed", "footnote_changed"]
    for k in kinds:
        s = template_summary(change("8707.10.00.40", k, related_codes="8707.10.00.90",
                                    old_value="2.5%", new_value="3%", field="general"))
        assert "8707.10.00.40" in s and not s.endswith("changed (" + k + ").")


def test_short_desc_explains_other():
    s = template_summary(change("8707.10.00.40", "deleted"))
    assert "For the vehicles of heading 8703: Other" in s


def test_fact_check():
    src = "Code 8707.10.00.40 was split into 8707.10.00.50; 8707.10.00.90."
    assert passes_check("8707.10.00.40 was split into 8707.10.00.50 and 8707.10.00.90.", src)
    assert not passes_check("8707.10.00.40 was split into 8707.10.00.60.", src)    # invented code
    assert not passes_check("The rate rose to 25% in 2026.", src)                 # invented numbers
    assert not passes_check("", src)


def test_llm_good_bad_and_broken_answers():
    changes = [change("8707.10.00.40", "split", related_codes="8707.10.00.50; 8707.10.00.90"),
               change("9503.00.00.73", "deleted"),
               change("0101.21.00.10", "deleted", tier="not_relevant")]

    def reply(content):
        items = json.loads(content)
        out = []
        for it in items:
            if "8707" in it["note"]:
                out.append({"id": it["id"], "summary": "Vehicle body code 8707.10.00.40 was split "
                                                        "into 8707.10.00.50 and 8707.10.00.90."})
            else:   # invents a code -> must be rejected
                out.append({"id": it["id"], "summary": "Toy code 9503.00.00.99 was removed."})
        return "```json\n" + json.dumps(out) + "\n```"

    client = FakeClient(reply)
    cache = {}
    overview, source, stats = summarize(changes, ("RevA", "RevB"), client, cache=cache)
    assert changes[0]["summary_source"] == "llm" and "Vehicle body" in changes[0]["summary"]
    assert changes[1]["summary_source"] == "template"          # failed the fact check
    assert changes[2]["summary_source"] == "template"          # not relevant: never sent
    assert stats["llm"] == 1 and stats["rejected"] == 1
    assert source == "llm"

    # second run: the good answer comes from the cache, no new rewrite calls for it
    again = [dict(c) for c in changes[:1]]
    for c in again:
        c.pop("summary"), c.pop("summary_source")
    client2 = FakeClient(lambda content: "not json")
    summarize(again, ("RevA", "RevB"), client2, cache=cache)
    assert again[0]["summary_source"] == "llm (cached)"


def test_api_failure_falls_back_to_templates():
    changes = [change("8707.10.00.40", "deleted")]
    summarize(changes, ("RevA", "RevB"), FakeClient(lambda content: "this is not json"), cache={})
    assert changes[0]["summary_source"] == "template"


def test_no_client_means_templates_and_overview():
    changes = [change("8707.10.00.40", "deleted"), change("0101.21.00.10", "added", tier="not_relevant")]
    overview, source, _ = summarize(changes, ("RevA", "RevB"), None)
    assert source == "template" and "2 changes, 1 of them relevant to CPSC" in overview
    assert "1 watched code was removed" in overview


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")

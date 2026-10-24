"""
Turn scored changes into plain-English sentences, plus a short overview per release.

How it works:
  1. Every change gets a template sentence built only from its own fields. Always correct, free.
  2. If an Anthropic API key is set, Claude rewrites the template sentences in plainer English,
     about 20 at a time. Each rewrite is checked: it must not contain any number or code that
     isn't in the original. Anything that fails the check keeps its template sentence.
  3. Every Claude answer is saved in data/cache/summaries.json, so reruns cost nothing.

By default only CPSC-relevant changes (Tier 1, needs_review, 2, 3) go to Claude;
not_relevant changes keep their template sentence.

Setup (only for step 2):
    pip install anthropic python-dotenv
    put ANTHROPIC_API_KEY=... in .env    (never commit .env)

Usage:
    python summarize.py --latest              # newest file in data/scored
    python summarize.py --all
    python summarize.py data/scored/scored_2026HTSRev20_2026HTSRev21.csv
    add --no-llm to use templates only, --llm-all to send not_relevant changes too
Output:
    data/summaries/summarized_<old>_<new>.csv   the scored file plus summary + summary_source
    data/summaries/overview_<old>_<new>.txt     a short overview of the release
"""
import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

SCORED = Path("data/scored")
OUT = Path("data/summaries")
CACHE = Path("data/cache/summaries.json")
MODEL = os.environ.get("HTS_SUMMARY_MODEL", "claude-haiku-5-5")
BATCH = 20
RELEVANT = ("1", "needs_review", "2", "3")
TIER_NAMES = {"1": "Tier 1 (covered)", "needs_review": "needs review",
              "2": "Tier 2 (near a rule)", "3": "Tier 3 (similar wording)",
              "not_relevant": "not relevant"}

SYSTEM = """You rewrite notes about changes to the U.S. Harmonized Tariff Schedule (HTS)
for staff at the Consumer Product Safety Commission, who are not tariff experts.

For each item, write one plain-English sentence of at most 30 words that says what changed.
Rules:
- Use only the facts in the item. Do not add codes, numbers, dates, rates or reasons.
- Copy every HTS code exactly as written, with its dots.
- Prefer everyday words: "removed" not "deleted", "split into" for splits.
- If the item says a person should check something, keep that.

Reply with JSON only, no other text: [{"id": <id>, "summary": "<sentence>"}, ...]"""

OVERVIEW_SYSTEM = """You write a short overview of one HTS release for CPSC staff.
Use only the counts and sentences given. Do not add numbers, codes or facts.
Write at most 5 sentences of plain English. Start with what CPSC most needs to act on.
Reply with the overview text only."""


# ---------- step 1: template sentences ----------

def short_desc(ch, limit=90):
    """A readable label: the line's text, plus its parent when the line just says 'Other'."""
    parts = [p.strip().rstrip(":") for p in ch.get("full_description", "").split(" > ") if p.strip()]
    text = ": ".join(parts[-2:]) if parts else ch.get("description", "")
    text = text.rstrip(":")
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def join_codes(related):
    """'a; b; c' -> 'a, b and c'"""
    codes = [c for c in related.split("; ") if c]
    return " and ".join([", ".join(codes[:-1]), codes[-1]]) if len(codes) > 1 else "".join(codes)


def template_summary(ch):
    code, rel, d = ch["code_display"], join_codes(ch.get("related_codes", "")), short_desc(ch)
    old, new = ch.get("old_value") or "blank", ch.get("new_value") or "blank"
    kind = ch["change_type"]
    if kind == "added":
        return f"New code {code} added ({d})" + (f", replacing {rel}." if rel else ".")
    if kind == "deleted":
        return f"Code {code} ({d}) was removed with no clear replacement."
    if kind == "renumbered":
        return f"Code {code} ({d}) was renumbered to {rel}."
    if kind == "split":
        return f"Code {code} ({d}) was split into {rel}."
    if kind == "possible_split":
        return (f"Code {code} ({d}) was removed, and new codes {rel} appeared in the same group; "
                f"they may replace it, so a person should check.")
    if kind == "desc_changed":
        return f"The wording of {code} changed from \"{old}\" to \"{new}\"."
    if kind == "rate_changed":
        return f"The {ch.get('field', '')} duty rate on {code} ({d}) changed from {old} to {new}."
    if kind == "units_changed":
        return f"The unit of quantity for {code} changed from {old} to {new}."
    if kind == "footnote_changed":
        extra = " (only its Chapter 99 reference changed)" if ch.get("category") == "rate" else ""
        return f"The footnotes on {code} changed{extra}."
    return f"{code} changed ({kind})."


# ---------- step 2: Claude rewrite with a fact check ----------

NUMBER = re.compile(r"\d[\d.,%]*\d|\d")


def numbers_in(text):
    return {n.rstrip(".,") for n in NUMBER.findall(text)}


def passes_check(summary, source):
    """The rewrite may not contain any number or code that isn't in the source text."""
    if not summary or len(summary.split()) > 60:
        return False
    return numbers_in(summary) <= numbers_in(source)


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def get_client():
    """An Anthropic client, or None (with a reason) if the API can't be used."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "no ANTHROPIC_API_KEY set"
    try:
        import anthropic
    except ImportError:
        return None, "anthropic is not installed (pip install anthropic)"
    return anthropic.Anthropic(), ""


def ask(client, system, user, max_tokens=4000):
    resp = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def cache_key(ch, template):
    raw = json.dumps([MODEL, template, ch["change_type"], ch.get("old_value", ""),
                      ch.get("new_value", "")], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_cache():
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def llm_rewrite(changes, client, cache):
    """Fill ch['summary'] with checked Claude rewrites where possible. Returns counts."""
    stats = Counter()
    todo = []
    for ch in changes:
        key = cache_key(ch, ch["summary"])
        if key in cache:
            ch["summary"], ch["summary_source"] = cache[key], "llm (cached)"
            stats["cached"] += 1
        else:
            todo.append((key, ch))

    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        items = [{"id": i, "note": ch["summary"], "change_type": ch["change_type"],
                  "relevance": ch.get("reason", "")} for i, (_, ch) in enumerate(batch)]
        try:
            answers = {a["id"]: a.get("summary", "").strip()
                       for a in parse_json(ask(client, SYSTEM, json.dumps(items, ensure_ascii=False)))}
        except Exception as e:   # bad JSON, network error, rate limit: keep templates for this batch
            print(f"  batch {start // BATCH + 1}: Claude failed ({type(e).__name__}); using templates")
            stats["failed"] += len(batch)
            continue
        for i, (key, ch) in enumerate(batch):
            summary = answers.get(i, "")
            source = " ".join([ch["summary"], ch["code_display"], ch.get("related_codes", ""),
                               ch.get("old_value", ""), ch.get("new_value", ""), ch.get("reason", "")])
            if passes_check(summary, source):
                ch["summary"], ch["summary_source"] = summary, "llm"
                cache[key] = summary
                stats["llm"] += 1
            else:
                stats["rejected"] += 1      # keeps its template sentence
    return stats


# ---------- the release overview ----------

def template_overview(changes, rel):
    tiers = Counter(c["tier"] for c in changes)
    total = len(changes)

    def n(count, one, many):
        return f"{count} {one if count == 1 else many}"

    parts = []
    if tiers["1"]:
        parts.append(n(tiers["1"], "touches CPSC-watched codes", "touch CPSC-watched codes"))
    if tiers["needs_review"]:
        parts.append(n(tiers["needs_review"], "needs a decision", "need a decision"))
    if tiers["2"] + tiers["3"]:
        parts.append(n(tiers["2"] + tiers["3"], "is worth checking", "are worth checking"))
    if parts:
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        lines = [f"Of {n(total, 'change', 'changes')} in {rel[1]}, {joined}."]
    else:
        lines = [f"None of the {n(total, 'change', 'changes')} in {rel[1]} affect CPSC-watched codes."]

    urgent = sum(1 for c in changes if c["tier"] == "1" and c.get("priority") == "1")
    if urgent:
        lines.append(f"{n(urgent, 'watched code was', 'watched codes were')} removed, split or "
                     f"renumbered, so CPSC targeting may need updating.")
    ch99 = sum(1 for c in changes if c.get("chapter") == "99")
    if ch99:
        lines.append(f"{n(ch99, 'change is a Chapter 99 tariff provision', 'changes are Chapter 99 tariff provisions')}, "
                     f"which do not affect product coverage.")
    return " ".join(lines)


def llm_overview(changes, rel, client, fallback):
    top = [c["summary"] for c in changes if c["tier"] in ("1", "needs_review")][:15]
    user = fallback + "\n\nMost important changes:\n" + "\n".join(f"- {s}" for s in top)
    try:
        text = ask(client, OVERVIEW_SYSTEM, user, max_tokens=600).strip()
    except Exception as e:
        print(f"  overview: Claude failed ({type(e).__name__}); using template")
        return fallback, "template"
    return (text, "llm") if passes_check(text, user) and len(text.split()) <= 150 else (fallback, "template")


# ---------- running it ----------

def summarize(changes, rel, client=None, llm_all=False, cache=None):
    for ch in changes:
        ch["summary"], ch["summary_source"] = template_summary(ch), "template"
    stats = Counter()
    overview, overview_source = template_overview(changes, rel), "template"
    if client is not None:
        cache = load_cache() if cache is None else cache
        chosen = [c for c in changes if llm_all or c["tier"] in RELEVANT]
        stats = llm_rewrite(chosen, client, cache)
        save_cache(cache)
        overview, overview_source = llm_overview(changes, rel, client, overview)
    return overview, overview_source, stats


def run_file(path, client, llm_all):
    path = Path(path)
    with open(path, encoding="utf-8-sig") as f:
        changes = list(csv.DictReader(f))
    rel = tuple(path.stem.replace("scored_", "").split("_", 1)) if "_" in path.stem else ("old", "new")
    if not changes:
        print(f"{path.name}: no changes")
        return
    overview, overview_source, stats = summarize(changes, rel, client, llm_all)

    OUT.mkdir(parents=True, exist_ok=True)
    out_csv = OUT / path.name.replace("scored_", "summarized_")
    columns = list(changes[0].keys())
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(changes)
    out_txt = OUT / path.name.replace("scored_", "overview_").replace(".csv", ".txt")
    out_txt.write_text(overview + "\n", encoding="utf-8")

    print(f"{path.name}: {len(changes)} summaries"
          + (f" (Claude: {stats['llm']} new, {stats['cached']} cached, "
             f"{stats['rejected']} rejected by the fact check, {stats['failed']} failed)" if stats else ""))
    print(f"  overview ({overview_source}): {overview[:150]}{'…' if len(overview) > 150 else ''}")
    print(f"  saved {out_csv} and {out_txt}")


def main():
    ap = argparse.ArgumentParser(description="Plain-English summaries of scored HTS changes.")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="templates only")
    ap.add_argument("--llm-all", action="store_true", help="also send not_relevant changes to Claude")
    args = ap.parse_args()

    files = sorted(SCORED.glob("scored_*.csv"), key=lambda p: p.stat().st_mtime)
    if args.file:
        files = [Path(args.file)]
    elif args.latest and files:
        files = files[-1:]
    elif not args.all:
        ap.error("give a scored file, or use --latest or --all")
    if not files:
        ap.error("no files in data/scored (run relevance.py first)")

    client = None
    if not args.no_llm:
        client, why = get_client()
        if client is None:
            print(f"Using templates only: {why}.")
    for p in files:
        run_file(p, client, args.llm_all)


if __name__ == "__main__":
    main()

"""
Build the outputs people see, from summarize.py's files:

    data/outputs/<new release>/report.html       full report, alert card at the top
    data/outputs/<new release>/alert.json        the alert as data (read by the Chrome extension)

Usage:
    python report.py --latest                 # newest file in data/summaries
    python report.py data/summaries/summarized_2026HTSRev10_2026HTSRev11.csv
    add --publish to also copy report.html and alert.json into docs/latest/ (served by GitHub Pages)
"""
import argparse
import csv
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path

SUMMARIES = Path("data/summaries")
OUTPUTS = Path("data/outputs")
PUBLISH = Path("docs/latest")
HTS_LOOKUP = "https://hts.usitc.gov/search?query={code}"   # check this link once in a browser

TIERS = ["1", "needs_review", "2", "3", "not_relevant"]
TIER_LABEL = {"1": "Covered", "needs_review": "Needs a decision", "2": "Near a watched rule",
              "3": "Similar wording", "not_relevant": "Not relevant"}
SECTIONS = [  # (title, intro, tiers, open by default)
    ("Act on these", "These changes touch codes CPSC already watches.", ["1"], True),
    ("Needs a decision", "These match rules with a condition, such as \u201cwhere applies\u201d. "
                         "A person decides whether they count.", ["needs_review"], True),
    ("Check whether to add", "Not on the list, but close to a watched code or worded like a "
                             "CPSC product.", ["2", "3"], True),
    ("Everything else", "Listed so nothing is hidden.", ["not_relevant"], False),
]
TYPE_LABEL = {"added": "Added", "deleted": "Removed", "renumbered": "Renumbered", "split": "Split",
              "possible_split": "Possible split", "desc_changed": "Reworded",
              "rate_changed": "Rate change", "units_changed": "Units change",
              "footnote_changed": "Footnote change"}
LINEAGE = ("split", "possible_split", "renumbered")

# Colours: light first, dark second (the report follows the reader's system setting)
URGENCY = {"red": ("#B42318", "#F97066"), "amber": ("#B54708", "#FDB022"),
           "grey": ("#5D6B7A", "#98A2B3")}
TIER_COLOR = {"1": "var(--red)", "needs_review": "var(--amber)", "2": "var(--steel)",
              "3": "var(--steel-soft)", "not_relevant": "var(--line-strong)"}


# ---------- the alert, as data ----------

def build_alert(changes, rel, overview):
    tiers = Counter(c["tier"] for c in changes)
    types = Counter(c["change_type"] for c in changes)
    watched = tiers["1"]
    maybe = tiers["needs_review"] + tiers["2"] + tiers["3"]
    if watched:
        urgency = "red"
        headline = f"{watched} change{'s' if watched != 1 else ''} affect{'s' if watched == 1 else ''} CPSC-watched codes"
    elif maybe:
        urgency = "amber"
        headline = f"{maybe} change{'s' if maybe != 1 else ''} may affect CPSC"
    else:
        urgency = "grey"
        headline = "No changes affect CPSC-watched codes"
    top = [c for c in changes if c["tier"] in ("1", "needs_review", "2", "3")][:8]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "from_release": rel[0], "to_release": rel[1],
        "urgency": urgency, "headline": headline, "overview": overview,
        "total_changes": len(changes),
        "tier_counts": {t: tiers[t] for t in TIERS},
        "type_counts": dict(types.most_common()),
        "top_changes": [{
            "code": c["code_display"], "tier": c["tier"], "change_type": c["change_type"],
            "summary": c.get("summary", ""), "related_codes": c.get("related_codes", ""),
        } for c in top],
    }


# ---------- the report page ----------

def code_link(code):
    return (f'<a class="code" href="{escape(HTS_LOOKUP.format(code=code))}" '
            f'target="_blank" rel="noopener">{escape(code)}</a>')


def lineage(c):
    """Old code on the left, the code(s) that replaced it on the right."""
    new = [x for x in c.get("related_codes", "").split("; ") if x]
    if not new:
        return ""
    targets = "".join(f'<li>{code_link(n)}</li>' for n in new)
    note = ("Replacement not confirmed: check these codes." if c["change_type"] == "possible_split"
            else "")
    return (f'<div class="lineage" role="img" aria-label="{escape(c["code_display"])} replaced by '
            f'{escape(", ".join(new))}"><div class="from">{code_link(c["code_display"])}</div>'
            f'<div class="branch" aria-hidden="true"></div><ul class="to">{targets}</ul></div>'
            + (f'<p class="lineage-note">{note}</p>' if note else ""))


def review_controls():
    options = "".join(f'<option value="{t}">{escape(TIER_LABEL[t])}</option>' for t in TIERS)
    return f"""
      <div class="review">
        <span class="review-q">Is this label right?</span>
        <button type="button" class="vote" data-v="correct" aria-pressed="false">Right</button>
        <button type="button" class="vote" data-v="wrong" aria-pressed="false">Wrong</button>
        <span class="fix" hidden>
          <label>Should be <select class="should-be"><option value="">Choose a label</option>{options}</select></label>
          <input class="note" type="text" placeholder="Note (optional)" aria-label="Note">
        </span>
      </div>"""


def change_item(c):
    kind = TYPE_LABEL.get(c["change_type"], c["change_type"])
    body = lineage(c) if c["change_type"] in LINEAGE else ""
    reviewed = c.get("reviewed", "")
    badge = {"confirmed": " · confirmed by a reviewer", "corrected": " · corrected by a reviewer",
             "remembered": " · set by an earlier review"}.get(reviewed, "")
    return f"""
    <li class="change" style="--tier:{TIER_COLOR[c['tier']]}" data-code="{escape(c['code_display'])}"
        data-type="{escape(c['change_type'])}" data-field="{escape(c.get('field', ''))}"
        data-tier="{escape(c.get('tool_tier') or c['tier'])}">
      <div class="change-head">
        <span class="kind">{escape(kind)}</span>{code_link(c['code_display'])}
        <span class="tier-name">{escape(TIER_LABEL[c['tier']])}{escape(badge)}</span>
      </div>
      <p class="summary">{escape(c.get('summary', ''))}</p>{body}
      <p class="reason">{escape(c.get('reason', ''))}</p>{review_controls()}
    </li>"""


def triage_strip(alert):
    total = alert["total_changes"] or 1
    counts = alert["tier_counts"]
    bars = "".join(
        f'<span style="flex:{counts[t]} 1 0;background:{TIER_COLOR[t]}" '
        f'title="{TIER_LABEL[t]}: {counts[t]}"></span>' for t in TIERS if counts[t])
    legend = "".join(
        f'<li><span class="swatch" style="background:{TIER_COLOR[t]}"></span>'
        f'{escape(TIER_LABEL[t])} <strong>{counts[t]}</strong></li>' for t in TIERS if counts[t])
    return (f'<div class="strip" aria-hidden="true">{bars}</div>'
            f'<ul class="legend" aria-label="Changes by relevance, {total} in total">{legend}</ul>')


def render_report(changes, alert):
    light, dark = URGENCY[alert["urgency"]]
    sections = []
    for title, intro, tiers, is_open in SECTIONS:
        rows = [c for c in changes if c["tier"] in tiers]
        if not rows:
            continue
        items = "".join(change_item(c) for c in rows)
        sections.append(
            f'<details class="section"{" open" if is_open else ""}><summary><h2>{escape(title)}'
            f'</h2><span class="count">{len(rows)}</span></summary><p class="intro">{escape(intro)}</p>'
            f'<ol class="changes">{items}</ol></details>')
    if not changes:
        sections.append('<p class="empty">The two releases are identical. Nothing to review.</p>')
    generated = datetime.strptime(alert["generated_at"], "%Y-%m-%dT%H:%M:%SZ").strftime("%B %d, %Y, %H:%M UTC")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HTS {escape(alert['to_release'])}: {escape(alert['headline'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {{
  color-scheme: light;
  --paper: #F4F6F8; --sheet: #FFFFFF; --ink: #17212B; --muted: #5B6875;
  --line: #DCE2E8; --line-strong: #B9C3CD;
  --red: #B42318; --amber: #B54708; --steel: #2F6690; --steel-soft: #6C93B5;
  --urgent: {light};
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --paper: #12171D; --sheet: #1A2129; --ink: #E7ECF1; --muted: #9AA7B4;
    --line: #2C3540; --line-strong: #4A5664;
    --red: #F97066; --amber: #FDB022; --steel: #7CB3E0; --steel-soft: #A9C9E6;
    --urgent: {dark};
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--paper); color: var(--ink);
  font: 400 16px/1.55 "Public Sans", "Segoe UI", system-ui, sans-serif; }}
.page {{ max-width: 52rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }}
a {{ color: inherit; }}
a:focus-visible, summary:focus-visible {{ outline: 3px solid var(--steel); outline-offset: 2px; }}
.code {{ font-variant-numeric: tabular-nums; font-weight: 600; letter-spacing: .01em;
  text-decoration-color: var(--line-strong); text-underline-offset: 3px; }}

/* the alert card */
.alert {{ background: var(--sheet); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }}
.alert-head {{ border-top: 6px solid var(--urgent); padding: 1.6rem 1.75rem 1.4rem; }}
.releases {{ margin: 0; color: var(--muted); font-size: .95rem; }}
.alert h1 {{ margin: .35rem 0 .6rem; font-size: clamp(1.7rem, 4.2vw, 2.4rem); line-height: 1.12;
  font-weight: 700; letter-spacing: -.015em; max-width: 26ch; }}
.overview {{ margin: 0; max-width: 64ch; color: var(--ink); }}
.alert-body {{ padding: 1.1rem 1.75rem 1.5rem; border-top: 1px solid var(--line); }}
.strip {{ display: flex; gap: 3px; height: 12px; border-radius: 6px; overflow: hidden; }}
.strip span {{ min-width: 6px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: .4rem 1.4rem; list-style: none; margin: .75rem 0 0;
  padding: 0; font-size: .92rem; color: var(--muted); }}
.legend strong {{ color: var(--ink); font-variant-numeric: tabular-nums; margin-left: .2rem; }}
.swatch {{ display: inline-block; width: .7rem; height: .7rem; border-radius: 3px; margin-right: .4rem;
  vertical-align: -.05rem; }}

/* sections */
.section {{ margin-top: 2.25rem; }}
.section > summary {{ display: flex; align-items: baseline; gap: .7rem; cursor: pointer; list-style: none; }}
.section > summary::-webkit-details-marker {{ display: none; }}
.section > summary::before {{ content: ""; width: .5rem; height: .5rem; border: solid var(--muted);
  border-width: 0 2px 2px 0; transform: rotate(-45deg); transition: transform .15s; align-self: center; }}
.section[open] > summary::before {{ transform: rotate(45deg); }}
.section h2 {{ margin: 0; font-size: 1.3rem; font-weight: 650; }}
.count {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
.intro {{ margin: .3rem 0 1rem 1.2rem; color: var(--muted); max-width: 64ch; }}
.changes {{ list-style: none; margin: 0; padding: 0; display: grid; gap: .6rem; }}
.change {{ min-width: 0; background: var(--sheet); border: 1px solid var(--line); border-left: 4px solid var(--tier);
  border-radius: 10px; padding: .9rem 1.1rem; }}
.change-head {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: .3rem .75rem; }}
.kind {{ font-weight: 600; }}
.tier-name {{ margin-left: auto; font-size: .85rem; color: var(--muted); }}
.summary {{ margin: .35rem 0 0; max-width: 68ch; }}
.reason {{ margin: .45rem 0 0; font-size: .88rem; color: var(--muted); max-width: 72ch; overflow-wrap: anywhere; }}

/* the memorable part: old code branching into its replacements */
.lineage {{ display: grid; grid-template-columns: auto 2.5rem auto; align-items: center;
  margin: .8rem 0 .1rem; width: fit-content; max-width: 100%; }}
.lineage .from, .lineage .to li {{ border: 1.5px solid var(--line-strong); border-radius: 8px;
  padding: .3rem .7rem; background: var(--paper); white-space: nowrap; }}
.lineage .from {{ border-color: var(--tier); justify-self: start; }}
.lineage .branch {{ align-self: stretch; position: relative; }}
.lineage .branch::before {{ content: ""; position: absolute; left: 0; width: 50%; top: 50%;
  border-top: 1.5px solid var(--line-strong); }}
.lineage .to {{ list-style: none; margin: 0; padding: 0; display: grid; gap: .4rem; position: relative; }}
.lineage .to li {{ position: relative; }}
.lineage .to li::before {{ content: ""; position: absolute; left: calc(-1.25rem - 1.5px); width: 1.25rem;
  top: 50%; border-top: 1.5px solid var(--line-strong); }}
.lineage .to::before {{ content: ""; position: absolute; left: calc(-1.25rem - 1.5px); top: 1rem;
  bottom: 1rem; border-left: 1.5px solid var(--line-strong); }}
.lineage-note {{ margin: .4rem 0 0; font-size: .88rem; color: var(--amber); }}

.review {{ display: flex; flex-wrap: wrap; align-items: center; gap: .45rem .6rem; margin-top: .75rem;
  padding-top: .65rem; border-top: 1px dashed var(--line); font-size: .9rem; }}
.review-q {{ color: var(--muted); }}
.vote, .bar-btn {{ font: inherit; font-size: .9rem; padding: .25rem .8rem; border-radius: 999px; cursor: pointer;
  border: 1.5px solid var(--line-strong); background: transparent; color: var(--ink); }}
.vote[data-v="correct"][aria-pressed="true"] {{ background: var(--steel); border-color: var(--steel); color: var(--sheet); }}
.vote[data-v="wrong"][aria-pressed="true"] {{ background: var(--amber); border-color: var(--amber); color: var(--sheet); }}
.fix {{ display: flex; flex-wrap: wrap; gap: .45rem; flex: 1 1 100%; }}
.fix[hidden] {{ display: none; }}
.fix .note {{ flex: 1 1 14rem; }}
.fix select, .fix input, .reviewbar input {{ font: inherit; font-size: .9rem; padding: .25rem .5rem;
  border: 1.5px solid var(--line-strong); border-radius: 8px; background: var(--sheet); color: var(--ink); }}
.change.done {{ border-color: var(--line); }}
.reviewbar {{ position: sticky; top: 0; z-index: 2; display: flex; flex-wrap: wrap; align-items: center;
  gap: .6rem 1rem; margin-top: 1rem; padding: .7rem 1rem; background: var(--sheet);
  border: 1px solid var(--line); border-radius: 12px; font-size: .92rem; }}
.reviewbar .progress {{ margin: 0; margin-right: auto; }}
.reviewbar strong {{ font-variant-numeric: tabular-nums; }}
.bar-btn.primary {{ background: var(--steel); border-color: var(--steel); color: var(--sheet); font-weight: 600; }}
.vote:focus-visible, .bar-btn:focus-visible, .fix select:focus-visible, .fix input:focus-visible,
.reviewbar input:focus-visible {{ outline: 3px solid var(--steel); outline-offset: 2px; }}
.empty {{ margin-top: 2rem; color: var(--muted); }}
footer {{ margin-top: 3rem; font-size: .85rem; color: var(--muted); }}
@media (max-width: 34rem) {{
  .alert-head, .alert-body {{ padding-left: 1.1rem; padding-right: 1.1rem; }}
  .tier-name {{ margin-left: 0; width: 100%; }}
  .lineage {{ grid-template-columns: auto; }}
  .lineage .branch {{ display: none; }}
  .lineage .to {{ margin: .5rem 0 0 1.5rem; }}
  .lineage .to::before {{ top: -.5rem; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style>
</head>
<body>
<main class="page">
  <section class="alert" aria-labelledby="headline">
    <div class="alert-head">
      <p class="releases">HTS {escape(alert['to_release'])}, compared with {escape(alert['from_release'])}</p>
      <h1 id="headline">{escape(alert['headline'])}</h1>
      <p class="overview">{escape(alert['overview'])}</p>
    </div>
    <div class="alert-body">{triage_strip(alert)}</div>
  </section>
  {review_bar(changes, alert)}
  {''.join(sections)}
  <footer>Generated {generated} from USITC data and CPSC\u2013CBP Appendix B.
  Prototype for CPSC Challenge X; check important changes against the official HTS.</footer>
</main>
<script>{review_script(alert)}</script>
</body>
</html>
"""


# ---------- reviewer feedback (kept in the browser, downloaded as CSV) ----------

def review_bar(changes, alert):
    if not changes:
        return ""
    return f"""<section class="reviewbar" aria-label="Your review">
    <p class="progress"><strong id="done-count">0</strong> of {len(changes)} labels reviewed</p>
    <label>Your name <input id="reviewer" type="text" autocomplete="name"></label>
    <button type="button" class="bar-btn primary" id="export">Download review</button>
    <button type="button" class="bar-btn" id="clear">Clear my answers</button>
  </section>"""


def review_script(alert):
    rel = json.dumps({"from": alert["from_release"], "to": alert["to_release"]})
    return r"""
(() => {
  const REL = %s;
  const KEY = "hts-review:" + REL.from + ":" + REL.to;
  let state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { state = {}; }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} };
  const items = [...document.querySelectorAll(".change")];
  const id = li => [li.dataset.code, li.dataset.type, li.dataset.field].join("|");
  const nameBox = document.getElementById("reviewer");
  try { nameBox.value = localStorage.getItem("hts-reviewer") || ""; } catch (e) {}
  nameBox?.addEventListener("input", () => { try { localStorage.setItem("hts-reviewer", nameBox.value); } catch (e) {} });

  function paint(li) {
    const a = state[id(li)];
    li.querySelectorAll(".vote").forEach(b => b.setAttribute("aria-pressed", String(!!a && a.verdict === b.dataset.v)));
    const fix = li.querySelector(".fix");
    fix.hidden = !(a && a.verdict === "wrong");
    if (a) { li.querySelector(".should-be").value = a.correct_tier || ""; li.querySelector(".note").value = a.note || ""; }
    li.classList.toggle("done", !!a);
    document.getElementById("done-count").textContent = items.filter(x => state[id(x)]).length;
  }

  items.forEach(li => {
    const touch = patch => {
      state[id(li)] = { ...(state[id(li)] || {}), ...patch, reviewed_at: new Date().toISOString() };
      save(); paint(li);
    };
    li.querySelectorAll(".vote").forEach(b => b.addEventListener("click", () => {
      const cur = state[id(li)];
      if (cur && cur.verdict === b.dataset.v) { delete state[id(li)]; save(); paint(li); return; }
      touch(b.dataset.v === "correct" ? { verdict: "correct", correct_tier: "", note: cur?.note || "" }
                                      : { verdict: "wrong" });
      if (b.dataset.v === "wrong") li.querySelector(".should-be").focus();
    }));
    li.querySelector(".should-be").addEventListener("change", e => touch({ correct_tier: e.target.value }));
    li.querySelector(".note").addEventListener("input", e => touch({ note: e.target.value }));
    paint(li);
  });

  const cell = v => /[",\n]/.test(v) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);
  document.getElementById("export")?.addEventListener("click", () => {
    const head = ["from_release","to_release","code","change_type","field","tool_tier",
                  "verdict","correct_tier","note","reviewer","reviewed_at"];
    const rows = items.filter(li => state[id(li)]).map(li => {
      const a = state[id(li)];
      return [REL.from, REL.to, li.dataset.code, li.dataset.type, li.dataset.field, li.dataset.tier,
              a.verdict, a.correct_tier || "", a.note || "", nameBox?.value || "", a.reviewed_at];
    });
    if (!rows.length) { alert("Mark at least one label as Right or Wrong first."); return; }
    const csv = "\ufeff" + [head, ...rows].map(r => r.map(cell).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "review_" + REL.from + "_" + REL.to + ".csv";
    document.body.appendChild(a); a.click(); a.remove();
  });
  document.getElementById("clear")?.addEventListener("click", () => {
    if (!confirm("Clear all your answers for this report?")) return;
    state = {}; save(); items.forEach(paint);
  });
})();
""" % rel


# ---------- running it ----------

def run_file(path, publish=False):
    path = Path(path)
    with open(path, encoding="utf-8-sig") as f:
        changes = list(csv.DictReader(f))
    rel = tuple(path.stem.replace("summarized_", "").split("_", 1))
    overview_path = path.with_name(path.name.replace("summarized_", "overview_")).with_suffix(".txt")
    overview = overview_path.read_text(encoding="utf-8").strip() if overview_path.exists() else ""

    alert = build_alert(changes, rel, overview)
    out = OUTPUTS / rel[1]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(render_report(changes, alert), encoding="utf-8")
    (out / "alert.json").write_text(json.dumps(alert, indent=2), encoding="utf-8")
    print(f"{rel[0]} -> {rel[1]}: {alert['headline']} ({alert['urgency']})")
    print(f"  saved {out}/report.html and alert.json")

    if publish:
        PUBLISH.mkdir(parents=True, exist_ok=True)
        for name in ("report.html", "alert.json"):
            shutil.copy(out / name, PUBLISH / name)
        print(f"  copied to {PUBLISH}/ (commit and push to update GitHub Pages)")
    return alert


def main():
    ap = argparse.ArgumentParser(description="Build the HTS change report and alert.")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--publish", action="store_true", help="copy outputs into docs/latest/")
    args = ap.parse_args()

    files = sorted(SUMMARIES.glob("summarized_*.csv"), key=lambda p: p.stat().st_mtime)
    if args.file:
        files = [Path(args.file)]
    elif args.latest and files:
        files = files[-1:]
    else:
        ap.error("give a summarized file, or use --latest")
    if not files:
        ap.error("no files in data/summaries (run summarize.py first)")
    for p in files:
        run_file(p, args.publish)


if __name__ == "__main__":
    main()

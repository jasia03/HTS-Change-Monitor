# HTS Change Monitor

A protoype for **U.S. Consumer Product Safety Commission (CPSC)**. It checks for new releases of the U.S. Harmonized Tariff Schedule (HTS), finds what changed, flags the changes that touch codes CPSC watches, and alerts staff through a Chrome extension and a web report.

## How it works

1. **Watch:** asks USITC which HTS release is current.
2. **Download:** gets the full schedule for that release and the one before it.
3. **Diff:** lists every code added, removed, split, renumbered or reworded.
4. **Relevance:** labels each change by checking it against CPSC's Appendix B (294 rules).
5. **Summarize:** writes one plain-English sentence per change.
6. **Publish:** builds a report and an alert file that the Chrome extension reads.

## Tiers

| Tiers | Meaning | What to do |
| --- | --- | --- |
| Covered | Matches an Appendix B rule | Act on it |
| Needs a decision | Matches only a rule with a condition, like "8708 where applies" | A person decides |
| Near a watched rule | Same 6-digit subheading as a narrow rule, but not on it | Consider adding it |
| Similar wording | Description contains a CPSC product word | Check the scope |
| Not relevant | None of the above | Listed, never hidden |

## Ways to Run the pipeline

```bash
python run_pipeline.py                                          # if you want to run the pipeline only on the newest release
python run_pipeline.py --old 2026HTSRev10 --new 2026HTSRev11    # a specific pair of release
python run_pipeline.py --check-only                             # just check for a new release
```
Add `--no-llm` for template summaries (no API key needed). Then commit and push `docs/latest/` so the website and extension update. The report is published at `https://jasia03.github.io/<repo>/latest/report.html`.

## Chrome extension

1. Open `chrome://extensions`, turn on **Developer mode** -> **Load unpacked** -> `extension/` folder.
2. Click the extension's icon and paste `https://jasia03.github.io/<repo>/latest/alert.json`.
The extension pop-up shows how many changes happened and their tiers and what action is needed : to act, to decide, and not relevant to CPSC.

## Reviewer feedback

Each change in the report has **Right** and **Wrong** buttons. Click **Download review**, put the file in `data/feedback/inbox/`, then run:
```bash
python feedback.py import    # save the decisions
python feedback.py stats     # how often each label was right
```
The next pipeline run applies the decisions.

## Main files

| File | Purpose |
| --- | --- |
| `run_pipeline.py` | Runs every step with one command |
| `download_hts.py` | Downloads HTS releases from USITC |
| `appendix_b_raw.txt`, `appendix_b.py` | CPSC's Appendix B, turned into 294 rules |
| `diff.py` | Finds every change between two releases |
| `relevance.py`, `cpsc_vocabulary.csv` | Labels each change |
| `summarize.py` | Writes the plain-English summaries |
| `report.py` | Builds the report and `alert.json` |
| `feedback.py` | Merges reviewer decisions |
| `validate_appendix_b.py`, `trace_dead_codes.py` | Find Appendix B rules that no longer match any code |
| `extension/` | The Chrome extension |

## Tests

```bash
for t in test_*.py; do python $t | tail -1; done
```
38 tests across 6 files. They use small sample data, so no internet or API key is needed.

## Known limits

- USITC sometimes blocks automated downloads (HTTP 403). If that happens, download the file in a browser, save it as `data/raw/<release name>.json`, and run again.
- The product word list for "similar wording" is a starter list; extend it over time.
- Item 55 of Appendix B was corrected from `8401.91.30xx` to `8409.91.30xx` (a likely typo). 
- Keep `.env` and `data/raw/` out of Git.

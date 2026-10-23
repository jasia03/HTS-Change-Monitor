# Task 1: USITC data access, Appendix B parsing, historical revisions

## Run it

```bash
pip install requests
python appendix_b.py                                   # parse Appendix B, run self-checks
python download_hts.py                                 # pulls all 55 releases (2025 + 2026)
python validate_appendix_b.py data/raw/2026HTSRev21.json
```

## 1. USITC data access: confirmed

Both endpoints were tested live on 2026-10-16. Neither needs an API key.

| Purpose | Endpoint |
|---|---|
| List of releases (for the monitor) | `https://hts.usitc.gov/reststop/releaseList` |
| Full revision, JSON | `https://www.usitc.gov/sites/default/files/tata/hts/hts_{YEAR}_revision_{N}_json.json` |
| Basic edition, JSON | `https://www.usitc.gov/sites/default/files/tata/hts/hts_{YEAR}_basic_edition_json.json` |

The current release is **2026HTSRev21**, effective 10/09/2026. The monitor only needs to poll `releaseList` and watch for a new entry with `"status": "current"`.

There are 55 releases in scope: the 2025 Basic edition plus 32 revisions, and the 2026 Basic edition plus 21 revisions. They are listed in `releases_2025_2026.csv`. 2026 is on pace to exceed 2025's count.

### Things in the data that will bite the diff engine

- **Release names are inconsistent across years.** Examples include `2023HTSARev4a`, `NTE`, and `chapter98`, and the list isn't sorted. Order releases by `releaseStartDate`, not by name.
- **Text-only header rows.** Some rows have an empty `htsno` and `"superior": "true"` (e.g. "Horses:"). They carry meaning for the parent chain, so keep them for hierarchy and skip them when matching codes.
- **Rates live on the 8-digit line.** The 10-digit statistical lines under it have blank rate fields and must inherit from their parent.
- `indent` is a string, `htsno` has dots, and there's a misspelled field `addiitionalDuties` alongside `additionalDuties`.
- **Many lines footnote Chapter 99** (e.g. "See 9903.88.15"). Those are the rate-only changes you want to separate from structural ones.

## 2. Appendix B: parsed, and it's not what the brief implies

The July 2026 Appendix B, from the CPSC memo dated Aug 4, 2026, is **not a list of ~600 codes**. It has 65 line items that expand to **294 rules**:

- 16 whole chapters (e.g. Chapter 95 inclusive)
- 111 ranges
- 167 headings, subheadings, or codes, including `xx` wildcards
- exclusions such as `3926 (except 3926.20.1010 and 3926.90.3000)`

So Tier 1 relevance has to be a rule match (`appendix_b.covered_by(code)`), not a set lookup. Run the validator to get the expanded 10-digit count. It will be far more than 600.

`appendix_b_raw.txt` is a hand-cleaned transcription. The PDF's two-column layout interleaves codes with descriptions (items 14, 15, 55, 56, 57, 59, 63), so automated text extraction scrambles them. Spot-check it against the PDF once.

### Defects found in Appendix B itself

These are worth showing judges, since they demonstrate why validation matters:

| Item | Issue |
|---|---|
| 55 | `8409.91.1040 8409.91.1080` has no separator. It was probably meant as a range. |
| 55 | `8401.91.30xx-8409.91.50xx` is probably a typo for `8409.91.30xx`, since heading 8401 is nuclear reactors. |
| 46 | `7419.91` and `7419.99.xxxx` look stale; heading 7419 was restructured in the 2022 HS edition. The validator will confirm. |
| 6, 46, 57, 63 | Ten rules carry human qualifiers ("where applies", "people only", "campers", "except aircraft/automotive"). A machine can't resolve these, so they're flagged `needs_review`. |

## 3. A free ground-truth case

The memo says USITC **split 8707.10.0040 into two codes** (vehicle bodies), and CPSC responded by listing 8707.10.0090. This is a real "HTS changed, CPSC acted" event, which makes it the first backtest: the diff engine should flag it as a Tier 1 split. Diffing the July 2026 revisions (Rev 11 through Rev 15) will show which revision introduced it.

## Files

| File | What |
|---|---|
| `appendix_b_raw.txt` | Cleaned 65-item transcription |
| `appendix_b.py` | Parser + `covered_by()` matcher + self-tests (all pass) |
| `appendix_b_rules.csv` | 294 rules with bounds, exclusions, review flags |
| `download_hts.py` | Downloads all releases, writes `data/manifest.csv` with SHA-256 |
| `validate_appendix_b.py` | Checks every rule against a snapshot; outputs the expanded code list |
| `releases_2025_2026.csv` | Release inventory with effective dates |

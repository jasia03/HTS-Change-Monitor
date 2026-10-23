"""
Download every HTS release for the chosen years from USITC and record a manifest.

Sources (both confirmed working on 2026-10-16):
  Release list : https://hts.usitc.gov/reststop/releaseList   (JSON, no key)
  Full files   : https://www.usitc.gov/sites/default/files/tata/hts/hts_{YEAR}_revision_{N}_json.json
                 https://www.usitc.gov/sites/default/files/tata/hts/hts_{YEAR}_basic_edition_json.json

Usage:
    pip install requests
    python download_hts.py                 # 2025 + 2026
    python download_hts.py --years 2026
"""
import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests

RELEASE_LIST = "https://hts.usitc.gov/reststop/releaseList"
STATIC = "https://www.usitc.gov/sites/default/files/tata/hts/hts_{year}_{slug}_json.json"
OUT = Path("data/raw")
# usitc.gov blocks requests that don't look like a web browser (HTTP 403),
# so we send normal browser headers and reuse one session (keeps cookies).
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.usitc.gov/harmonized_tariff_information/hts/archive/list",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# Release names are NOT consistent across years (e.g. '2023HTSARev4a', 'NTE',
# 'chapter98'), so we only trust this pattern for 2024+ and sort by dates, not names.
NAME_RE = re.compile(r"^(\d{4})HTS(Basic|Rev(\d+))$")


def get_releases(years):
    r = SESSION.get(RELEASE_LIST, timeout=60)
    r.raise_for_status()
    rows = []
    for rel in r.json():
        m = NAME_RE.match(rel["name"])
        if not m or int(m.group(1)) not in years:
            continue
        year = int(m.group(1))
        slug = "basic_edition" if m.group(2) == "Basic" else f"revision_{m.group(3)}"
        rows.append({
            "name": rel["name"],
            "year": year,
            "rev": 0 if m.group(2) == "Basic" else int(m.group(3)),
            "status": rel["status"],
            "start": rel["releaseStartDate"],
            "end": rel["releaseEndDate"] or "",
            "merged_revisions": len(rel.get("mergedRevisions") or []),
            "url": STATIC.format(year=year, slug=slug),
        })
    rows.sort(key=lambda x: datetime.strptime(x["start"], "%m/%d/%Y"))
    return rows


def download(rel, force=False):
    dest = OUT / f"{rel['name']}.json"
    if dest.exists() and not force:
        status = "cached"
    else:
        r = SESSION.get(rel["url"], timeout=300)
        if r.status_code != 200:
            return {**rel, "file": "", "status_dl": f"HTTP {r.status_code}", "rows": 0, "sha256": ""}
        dest.write_bytes(r.content)
        status = "downloaded"
        time.sleep(1)  # be polite
    data = dest.read_bytes()
    try:
        rows = len(json.loads(data))
    except ValueError:  # empty file or a saved web page instead of the JSON
        return {**rel, "file": "", "status_dl": f"BAD FILE ({len(data):,} bytes) - delete it",
                "rows": 0, "sha256": ""}
    return {**rel, "file": str(dest), "status_dl": status, "rows": rows,
            "sha256": hashlib.sha256(data).hexdigest()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2025, 2026])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    try:  # visit the archive page first to pick up any cookies the site sets
        SESSION.get(HEADERS["Referer"], timeout=60)
    except requests.RequestException:
        pass
    releases = get_releases(set(args.years))
    print(f"{len(releases)} releases found for {args.years}")

    results = []
    for rel in releases:
        res = download(rel, args.force)
        print(f"  {res['name']:<16} {res['start']}  {res['status_dl']:<10} rows={res['rows']}")
        results.append(res)

    with open("data/manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    failed = [r for r in results if not r["file"]]
    print(f"\nDone. {len(results) - len(failed)} ok, {len(failed)} failed. Manifest: data/manifest.csv")
    for r in failed:
        print(f"  FAILED {r['name']}: {r['status_dl']} {r['url']}")
    if failed:
        print("\nIf files still fail: open a URL above in your browser, save the file into")
        print("data/raw/ named like 2026HTSRev21.json, then rerun this script.")
        print("Saved files are detected automatically and marked 'cached'.")


if __name__ == "__main__":
    main()

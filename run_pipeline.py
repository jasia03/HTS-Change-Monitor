"""
Run the whole HTS Change Monitor in one command.

    1. Ask USITC which release is current.
    2. Stop if it's the release we already published (docs/latest/alert.json).
    3. Otherwise download the new release and the one before it (cached files are reused).
    4. diff -> relevance -> summaries -> report, then publish to docs/latest/.

Usage:
    python run_pipeline.py                        # check, and run only if there's a new release
    python run_pipeline.py --check-only           # just say whether there's a new release
    python run_pipeline.py --force                # rerun on the current release anyway
    python run_pipeline.py --old 2026HTSRev10 --new 2026HTSRev11   # a specific pair
    --no-llm       template summaries only (no API key needed)
    --no-publish   build the report but don't copy it to docs/latest/

Every run is logged in data/runs.csv. If any step fails, nothing is published, and the
command exits with an error so a scheduled job shows it as failed.

After a run that published something, commit and push docs/latest/ so GitHub Pages
(and the Chrome extension) pick it up.
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # find diff.py etc. next to this file

PUBLISHED = Path("docs/latest/alert.json")
RUNS_LOG = Path("data/runs.csv")


class PipelineError(Exception):
    """A step failed; the message says which and why."""


# ---------- talking to USITC (kept small so tests can replace them) ----------

def find_releases(years):
    """Releases for these years from USITC, oldest first: dicts with name, start, status, url."""
    import download_hts
    try:   # visit the archive page first, as download_hts.py does, to pick up cookies
        download_hts.SESSION.get(download_hts.HEADERS["Referer"], timeout=60)
    except Exception:
        pass
    return download_hts.get_releases(set(years))


def fetch(release):
    """Download one release (or reuse the saved copy). Returns the file path."""
    import download_hts
    download_hts.OUT.mkdir(parents=True, exist_ok=True)
    result = download_hts.download(release)
    if not result["file"]:
        raise PipelineError(f"could not download {release['name']}: {result['status_dl']} "
                            f"({release['url']})")
    return Path(result["file"])


# ---------- deciding what to run ----------

def last_published():
    try:
        return json.loads(PUBLISHED.read_text(encoding="utf-8"))["to_release"]
    except (FileNotFoundError, KeyError, ValueError):
        return ""


def current_release(releases):
    current = [r for r in releases if str(r.get("status", "")).lower() == "current"]
    return current[-1] if current else releases[-1]


def pick_pair(releases, old_name=None, new_name=None):
    """(old, new) release dicts: the given names, or the current release and the one before it."""
    by_name = {r["name"]: r for r in releases}
    if new_name:
        if new_name not in by_name:
            raise PipelineError(f"{new_name} is not in USITC's release list")
        new = by_name[new_name]
    else:
        new = current_release(releases)
    if old_name:
        if old_name not in by_name:
            raise PipelineError(f"{old_name} is not in USITC's release list")
        old = by_name[old_name]
    else:
        i = releases.index(new)
        if i == 0:
            raise PipelineError(f"no release before {new['name']} in the years searched")
        old = releases[i - 1]
    return old, new


# ---------- the steps ----------

def step(name, func, *args):
    print(f"\n== {name}")
    start = time.time()
    try:
        result = func(*args)
    except PipelineError:
        raise
    except Exception as e:
        raise PipelineError(f"{name} failed: {type(e).__name__}: {e}") from e
    print(f"   ({time.time() - start:.1f} s)")
    return result


def run_steps(old_path, new_path, use_llm=True, publish=True):
    """diff -> relevance -> summaries -> report. Returns the alert dict."""
    import diff
    import relevance
    import report
    import summarize
    from appendix_b import load_rules

    rel = (old_path.stem, new_path.stem)
    pair = f"{rel[0]}_{rel[1]}"
    changes = step("Diff", diff.run_pair, old_path, new_path)

    summarized = summarize.OUT / f"summarized_{pair}.csv"
    if changes:
        decisions = relevance.load_decisions()
        if decisions[0]:
            print(f"   applying {len(decisions[0])} reviewer decisions")
        step("Relevance", relevance.run_file, relevance.DIFFS / f"changes_{pair}.csv",
             load_rules(), relevance.load_vocab(), decisions)
        client = None
        if use_llm:
            client, why = summarize.get_client()
            if client is None:
                print(f"   summaries: templates only ({why})")
        step("Summaries", summarize.run_file, relevance.OUT / f"scored_{pair}.csv", client, False)
    else:   # identical releases: still publish a (grey) alert so the extension shows it was checked
        print("\n== No differences between the two releases")
        summarize.OUT.mkdir(parents=True, exist_ok=True)
        summarized.write_text("code,code_display,change_type,tier,priority,summary,reason,related_codes\n",
                              encoding="utf-8")
        summarized.with_name(f"overview_{pair}.txt").write_text(
            f"{rel[1]} is identical to {rel[0]}: no codes, descriptions or rates changed.\n",
            encoding="utf-8")
    return step("Report", report.run_file, summarized, publish)


def log_run(row):
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    new_file = not RUNS_LOG.exists()
    with RUNS_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["run_at", "result", "old", "new", "headline", "detail"])
        if new_file:
            w.writeheader()
        w.writerow(row)


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Check USITC for a new HTS release and run the whole pipeline.")
    ap.add_argument("--check-only", action="store_true", help="only report whether there's a new release")
    ap.add_argument("--force", action="store_true", help="run even if this release was already published")
    ap.add_argument("--old", help="older release name, e.g. 2026HTSRev10")
    ap.add_argument("--new", help="newer release name, e.g. 2026HTSRev11")
    ap.add_argument("--no-llm", action="store_true", help="template summaries only")
    ap.add_argument("--no-publish", action="store_true", help="don't copy outputs to docs/latest/")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    log = {"run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "result": "", "old": "", "new": "",
           "headline": "", "detail": ""}
    try:
        years = {now.year - 1, now.year}   # last year too, so a Basic edition can be compared with
        for name in (args.old, args.new):  # the previous year's final revision
            if name and name[:4].isdigit():
                years.add(int(name[:4]))
        print(f"Checking USITC for {', '.join(map(str, sorted(years)))} releases...")
        releases = step("Release list", find_releases, sorted(years))
        if not releases:
            raise PipelineError("USITC returned no releases for those years")
        old, new = pick_pair(releases, args.old, args.new)
        log.update(old=old["name"], new=new["name"])

        seen = last_published()
        is_new = new["name"] != seen
        print(f"\nCurrent: {current_release(releases)['name']}   last published: {seen or 'nothing yet'}")
        if args.check_only:
            print("NEW RELEASE: run the pipeline." if is_new else "No new release.")
            log.update(result="checked", detail="new release" if is_new else "no new release")
            return "new" if is_new else "up to date"
        if not is_new and not (args.force or args.old or args.new):
            print("No new release. Nothing to do (use --force to rerun).")
            log.update(result="up to date")
            return "up to date"

        print(f"\nRunning {old['name']} -> {new['name']}")
        old_path = step(f"Download {old['name']}", fetch, old)
        new_path = step(f"Download {new['name']}", fetch, new)
        alert = run_steps(old_path, new_path, use_llm=not args.no_llm, publish=not args.no_publish)

        log.update(result="published" if not args.no_publish else "built", headline=alert["headline"])
        print(f"\nDone: {alert['headline']} ({alert['urgency']}).")
        if not args.no_publish:
            print("Next: commit and push docs/latest/ so GitHub Pages and the extension update.")
        return "published" if not args.no_publish else "built"

    except PipelineError as e:
        print(f"\nFAILED: {e}\nNothing was published.", file=sys.stderr)
        log.update(result="failed", detail=str(e))
        return "failed"
    finally:
        log_run(log)


if __name__ == "__main__":
    sys.exit(1 if main() == "failed" else 0)

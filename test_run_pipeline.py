"""
Tests for run_pipeline.py. USITC is replaced by small hand-made releases, so no internet is needed.

Run:  python test_run_pipeline.py      (or: pytest test_run_pipeline.py)
"""
import csv
import json
import os
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
import run_pipeline                       # noqa: E402
from test_diff import NEW, OLD            # noqa: E402  the same small releases diff.py is tested on

RELEASES = [
    {"name": "2026HTSRev10", "start": "07/01/2026", "status": "expired", "url": "https://example.org/10"},
    {"name": "2026HTSRev11", "start": "07/15/2026", "status": "current", "url": "https://example.org/11"},
]
CONTENT = {"2026HTSRev10": OLD, "2026HTSRev11": NEW}
calls = {"fetch": 0}


def fake_find(years):
    return [dict(r) for r in RELEASES]


def fake_fetch(release):
    calls["fetch"] += 1
    if release.get("broken"):
        raise run_pipeline.PipelineError(f"could not download {release['name']}: HTTP 403")
    path = Path("data/raw") / f"{release['name']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(CONTENT[release["name"]]), encoding="utf-8")
    return path


run_pipeline.find_releases = fake_find
run_pipeline.fetch = fake_fetch


def in_fresh_folder():
    """Run in an empty project folder (the pipeline uses relative paths like data/ and docs/)."""
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(HERE / "cpsc_vocabulary.csv", tmp / "cpsc_vocabulary.csv")
    os.chdir(tmp)
    RELEASES[0].pop("broken", None)
    CONTENT["2026HTSRev11"] = NEW
    return tmp


def published():
    return json.loads(Path("docs/latest/alert.json").read_text())


def runs():
    with open("data/runs.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_new_release_runs_everything_and_publishes():
    in_fresh_folder()
    assert run_pipeline.main(["--no-llm"]) == "published"
    a = published()
    assert (a["from_release"], a["to_release"], a["urgency"]) == ("2026HTSRev10", "2026HTSRev11", "red")
    assert Path("docs/latest/report.html").exists()
    for f in ("data/diffs/changes_2026HTSRev10_2026HTSRev11.csv",
              "data/scored/scored_2026HTSRev10_2026HTSRev11.csv",
              "data/summaries/summarized_2026HTSRev10_2026HTSRev11.csv"):
        assert Path(f).exists(), f
    assert runs()[-1]["result"] == "published"


def test_same_release_does_nothing_unless_forced():
    in_fresh_folder()
    run_pipeline.main(["--no-llm"])
    before = calls["fetch"]
    assert run_pipeline.main(["--no-llm"]) == "up to date"
    assert calls["fetch"] == before                       # nothing downloaded
    assert run_pipeline.main(["--no-llm", "--force"]) == "published"
    assert [r["result"] for r in runs()] == ["published", "up to date", "published"]


def test_check_only():
    in_fresh_folder()
    assert run_pipeline.main(["--check-only"]) == "new"
    assert not Path("docs/latest/alert.json").exists()     # checking never publishes
    run_pipeline.main(["--no-llm"])
    assert run_pipeline.main(["--check-only"]) == "up to date"


def test_specific_pair_and_unknown_name():
    in_fresh_folder()
    assert run_pipeline.main(["--no-llm", "--old", "2026HTSRev10", "--new", "2026HTSRev11"]) == "published"
    assert run_pipeline.main(["--no-llm", "--new", "2026HTSRev99"]) == "failed"
    assert "not in USITC's release list" in runs()[-1]["detail"]


def test_identical_releases_publish_a_grey_alert():
    in_fresh_folder()
    CONTENT["2026HTSRev11"] = OLD
    assert run_pipeline.main(["--no-llm"]) == "published"
    a = published()
    assert a["urgency"] == "grey" and a["total_changes"] == 0
    assert "identical" in a["overview"]


def test_failed_download_publishes_nothing():
    in_fresh_folder()
    RELEASES[0]["broken"] = True
    assert run_pipeline.main(["--no-llm"]) == "failed"
    assert not Path("docs/latest/alert.json").exists()
    assert "HTTP 403" in runs()[-1]["detail"]


def test_reviewer_decisions_are_applied():
    in_fresh_folder()
    Path("data/feedback").mkdir(parents=True)
    with open("data/feedback/decisions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["from_release", "to_release", "code", "change_type", "field", "tool_tier",
                    "verdict", "correct_tier", "note", "reviewer", "reviewed_at"])
        w.writerow(["2026HTSRev10", "2026HTSRev11", "9503.00.00.73", "desc_changed", "description",
                    "1", "wrong", "not_relevant", "test", "JS", "2026-10-24T10:00:00Z"])
    run_pipeline.main(["--no-llm"])
    with open("data/scored/scored_2026HTSRev10_2026HTSRev11.csv", encoding="utf-8-sig") as f:
        row = [r for r in csv.DictReader(f) if r["code"] == "9503000073"][0]
    assert (row["tier"], row["reviewed"]) == ("not_relevant", "corrected")


if __name__ == "__main__":
    start = os.getcwd()
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    try:
        for t in tests:
            t()
            print(f"ok  {t.__name__}")
    finally:
        os.chdir(start)
    print(f"\nAll {len(tests)} tests passed.")

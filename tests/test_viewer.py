import json
import re
from pathlib import Path
from core.build_viewer import build, collect


def make_run(tmp_path):
    d = tmp_path / "run" / "meta" / "p" / "sample0"
    d.mkdir(parents=True)
    (d / "attempt_0.go").write_text("package main // a0")
    (d / "attempt_1.go").write_text("package main // a1")
    (d / "result.json").write_text(json.dumps({
        "program": "p", "provider": "meta", "model": "m", "effort": "low", "sample": 0, "status": "verified",
        "single_shot_ok": False, "repairs_used": 1, "cases": 6, "total_cost_usd": 0.0, "total_list_cost_usd": 0.05,
        "attempts": [{"n": 0, "kind": "translate", "built": True, "passed_cases": 4, "output_tokens": 9,
                      "cost_usd": 0.0, "list_cost_usd": 0.02, "failure": "oops </script><b>x</b>"}],
        "final_go": "package main // a1"}))
    progs = tmp_path / "progs" / "t1"
    progs.mkdir(parents=True)
    (progs / "p.cbl").write_text("       PROGRAM-ID. P.\n")
    return tmp_path / "run", tmp_path / "progs"


def test_collects_attempts_cobol_and_summary(tmp_path):
    run, progs = make_run(tmp_path)
    data = collect(run, progs)
    r = data["runs"][0]
    assert set(r["attempt_go"]) == {"attempt_0.go", "attempt_1.go"} and "final_go" not in r
    assert "PROGRAM-ID. P." in r["cobol"] and data["summary"][0]["verified"] == "1/1"


def test_page_embeds_valid_json_that_cannot_close_the_script_tag(tmp_path):
    run, progs = make_run(tmp_path)
    out = build(run, tmp_path / "viewer" / "index.html", progs)
    html = out.read_text()
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert "</script" not in blob
    assert json.loads(blob)["runs"][0]["attempts"][0]["failure"].startswith("oops </script>")


def test_empty_run_dir_still_builds(tmp_path):
    out = build(tmp_path / "none", tmp_path / "v.html", tmp_path)
    assert "No results found" in out.read_text()
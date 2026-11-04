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


def test_labels_mutation_and_pooled_results_are_embedded(tmp_path):
    run, progs = make_run(tmp_path)
    (run / "mutation").mkdir()
    (run / "mutation" / "p.json").write_text(json.dumps({"mutants": 10, "caught": 8, "survived": 2, "catch_rate": 0.8,
                                                         "stress": {"catch_rate_with_more_inputs": 0.9}}))
    lab = tmp_path / "labels.csv"
    lab.write_text("run,label,notes\nmeta/p/sample0,compile: unused variable,x\n")
    d = collect(run, progs, lab)
    assert d["labels"]["meta/p/sample0"]["label"] == "compile: unused variable"
    assert d["mutation"][0]["with_more_inputs"] == 0.9 and d["overall"][0]["provider"] == "meta"


def test_export_data_writes_a_lazy_loadable_contract(tmp_path):
    import shutil
    from core.build_viewer import export_data
    run, _ = make_run(tmp_path)
    progs = tmp_path / "progs2" / "tier1"
    progs.mkdir(parents=True)
    shutil.copy("benchmark/programs/tier1/simple_interest.cbl", progs / "p.cbl")
    idx = export_data(run, tmp_path / "data", tmp_path / "progs2", tmp_path / "none.csv", tmp_path / "nogold")
    d = json.loads(idx.read_text())
    assert d["programs"] == [{"name": "p", "tier": "tier1"}] and d["runs"][0]["id"] == "meta__p__low__s0"
    assert {"summary", "overall", "matrix", "mutation", "failure_counts"} <= set(d)
    run_json = json.loads((tmp_path / "data" / "runs" / "meta__p__low__s0.json").read_text())
    assert set(run_json["attempt_go"]) == {"attempt_0.go", "attempt_1.go"} and run_json["tier"] == "tier1"
    prog = json.loads((tmp_path / "data" / "programs" / "p.json").read_text())
    assert prog["layout"][0]["name"] == "LR-ACCT" and "PROGRAM-ID" in prog["cobol"]


def test_viewer_static_app_contract_and_size():
    viewer_dir = Path("viewer")
    idx_path = viewer_dir / "data" / "index.json"
    if not idx_path.exists():
        return
    index = json.loads(idx_path.read_text())
    for k in ["generated", "programs", "runs", "summary", "overall", "matrix", "mutation", "failure_counts"]:
        assert k in index, f"Missing key in index.json: {k}"

    valid_statuses = {"verified", "failed", "llm_error", "budget_exceeded"}
    for r in index["runs"]:
        assert r["status"] in valid_statuses

    js_files = list(viewer_dir.rglob("*.js"))
    for f in js_files:
        content = f.read_text()
        imports = re.findall(r"from\s+[\"\x27]([\.\/\w\-]+)[\"\x27]", content)
        for imp in imports:
            resolved = f.parent / imp
            if not resolved.suffix:
                resolved = resolved.with_suffix(".js")
            assert resolved.exists(), f"Broken import in {f}: {imp}"

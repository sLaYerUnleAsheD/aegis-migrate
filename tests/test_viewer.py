import json
from pathlib import Path
from core.build_viewer import build, collect, run_id


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
    assert r["id"] == "meta__p__effort-low__s0"


def test_build_writes_lazy_json_not_an_html_blob(tmp_path):
    run, progs = make_run(tmp_path)
    dest = build(run, tmp_path / "viewer" / "index.html", progs)
    index = json.loads((dest / "index.json").read_text())
    rid = "meta__p__effort-low__s0"
    assert index["runs"][0]["id"] == rid
    assert "cobol" not in index["runs"][0] and "attempt_go" not in index["runs"][0]
    payload = json.loads((dest / "runs" / f"{rid}.json").read_text())
    assert payload["attempts"][0]["failure"].startswith("oops </script>")
    assert payload["attempt_go"]["attempt_1.go"] == "package main // a1"
    prog = json.loads((dest / "programs" / "p.json").read_text())
    assert "PROGRAM-ID. P." in prog["cobol"] and prog["tier"] == "t1"
    html = tmp_path / "viewer" / "index.html"
    assert not html.exists() or html.stat().st_size < 100_000


def test_empty_run_dir_still_builds(tmp_path):
    dest = build(tmp_path / "none", tmp_path / "v.html", tmp_path)
    index = json.loads((dest / "index.json").read_text())
    assert index["runs"] == [] and index["matrix"] == []


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
    assert d["failure_counts"]["compile: unused variable"] == 1
    assert d["matrix"][0]["provider"] == "meta" and d["matrix"][0]["first_try"] == "0/1"


def test_run_id_format():
    assert run_id({"provider": "modal", "program": "payroll_report", "effort": "default", "sample": 1}) == (
        "modal__payroll_report__effort-default__s1")


def test_viewer_static_app_contract_and_size():
    import re
    viewer_dir = Path("viewer")
    if not (viewer_dir / "data" / "index.json").exists():
        return
    index = json.loads((viewer_dir / "data" / "index.json").read_text())
    for k in ["generated", "programs", "runs", "summary", "overall", "matrix", "mutation", "failure_counts"]:
        assert k in index, f"Missing key in index.json: {k}"

    valid_statuses = {"verified", "failed", "llm_error", "budget_exceeded"}
    for r in index["runs"]:
        assert r["status"] in valid_statuses

    pr_run = viewer_dir / "data" / "runs" / "modal__payroll_report__effort-default__s1.json"
    if pr_run.exists():
        pr_data = json.loads(pr_run.read_text())
        assert pr_data["status"] == "verified"
        assert len(pr_data["attempts"]) == 2
        assert "130.00" in pr_data["attempts"][0]["failure"]
        assert "9,040.00" in pr_data["attempts"][0]["failure"]

    js_files = list(viewer_dir.rglob("*.js"))
    for f in js_files:
        content = f.read_text()
        imports = re.findall(r"from\s+[\"\x27]([\.\/\w\-]+)[\"\x27]", content)
        for imp in imports:
            resolved = f.parent / imp
            if not resolved.suffix:
                resolved = resolved.with_suffix(".js")
            assert resolved.exists(), f"Broken import in {f}: {imp}"

    total_kb = sum(p.stat().st_size for p in [viewer_dir / "index.html", viewer_dir / "styles.css", viewer_dir / "data" / "index.json"] + js_files) / 1024
    assert total_kb < 200, f"Initial bundle exceeds 200 KB: {total_kb:.1f} KB"

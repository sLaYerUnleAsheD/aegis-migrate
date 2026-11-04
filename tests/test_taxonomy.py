import csv
import json
from core.taxonomy import auto_tag, collect_failures, write_csv


def test_tags_for_each_failure_kind():
    assert auto_tag("BUILD ERROR:\nmain.go:3: undefined: x") == "compile_error"
    assert auto_tag("NO GO CODE: nothing") == "no_code"
    assert auto_tag("[c1] crash\nexit code 2") == "runtime_crash"
    assert auto_tag("[c1] timeout\nexceeded") == "timeout"
    assert auto_tag("[c1] stdout_diff\n-A\u00b7\u00b7\u00b7\u00b71.00\n+A\u00b7\u00b71.00") == "alignment_or_whitespace"
    assert auto_tag("[c1] stdout_diff\n-A 1.00\n-B 2.00\n+A 1.00") == "missing_or_extra_lines"
    assert auto_tag("[c1] stdout_diff\n-DEPT ENG 5\n+DEPT OPS 5") == "text_mismatch"
    assert auto_tag("[c1] stdout_diff\n-X 50.00 238,804.53\n+X 50.00 0.00") == "zero_result"
    assert auto_tag("[c1] stdout_diff\n-T 376,616.85\n+T 376,616.84") == "cent_off_by_rounding"
    assert auto_tag("[c1] stdout_diff\n-TOTAL 100.00\n+TOTAL 250.00") == "total_mismatch"
    assert auto_tag("[c1] stdout_diff\n-A 100.00\n+A 250.00") == "value_mismatch"


def test_real_modal_failure_is_tagged_zero_result():
    real = ("[case-05] stdout_diff\n-02CS87\u00b7\u00b7\u00b750,887.43\u00b7\u00b7238,804.53\n"
            "+02CS87\u00b7\u00b7\u00b750,887.43\u00b7\u00b7\u00b7\u00b7\u00b70.00\n"
            "-1A7XRW\u00b7\u00b70.24\u00b7\u00b70.01\n+1A7XRW\u00b7\u00b70.24\u00b7\u00b70.00\n"
            "-TOTAL\u00b7INTEREST:\u00b7990,144,283.79\n+TOTAL\u00b7INTEREST:\u00b7989,905,479.03")
    assert auto_tag(real) == "zero_result"


def test_collect_and_csv(tmp_path):
    d = tmp_path / "run" / "modal" / "p" / "sample0"
    d.mkdir(parents=True)
    (d / "attempt_0.go").write_text("a\nfmt.Sscan(x)\nc\n")
    (d / "main.go").write_text("a\nstrconv.ParseInt(x)\nc\n")
    base = {"program": "p", "provider": "modal", "sample": 0, "repairs_used": 1, "status": "verified"}
    (d / "result.json").write_text(json.dumps({**base, "single_shot_ok": False, "attempts": [
        {"failure": "[c] stdout_diff\n-X 5.00\n+X 0.00"}]}))
    ok = tmp_path / "run" / "meta" / "p" / "sample0"
    ok.mkdir(parents=True)
    (ok / "result.json").write_text(json.dumps({**base, "provider": "meta", "single_shot_ok": True,
                                                "attempts": [{"failure": ""}]}))
    rows = collect_failures(tmp_path / "run")
    assert len(rows) == 1 and rows[0]["auto_tag"] == "zero_result"
    assert "-fmt.Sscan(x)" in rows[0]["repair_diff"] and "+strconv.ParseInt(x)" in rows[0]["repair_diff"]
    write_csv(rows, tmp_path / "f.csv")
    got = list(csv.DictReader((tmp_path / "f.csv").open()))
    assert got[0]["run"] == "modal/p/sample0" and got[0]["label_source"] == "auto"
    assert got[0]["label"].startswith("library semantics: fmt.Sscan")


def test_repair_diff_ignores_comments_and_spacing(tmp_path):
    from core.taxonomy import repair_diff
    d = tmp_path / "r"
    d.mkdir()
    (d / "attempt_0.go").write_text("// header\nvar  x   int // note\n\n// why\nn := fmt.Sscan(t)\n")
    (d / "main.go").write_text("var x int\nn := strconv.ParseInt(t)\n")
    diff = repair_diff(d)
    assert "-n := fmt.Sscan(t)" in diff and "+n := strconv.ParseInt(t)" in diff
    assert "header" not in diff and "note" not in diff and "var" not in diff.replace("var x int", "")
    (d / "main.go").write_text("var x int\nn := fmt.Sscan(t)\n")
    assert repair_diff(d).startswith("(no code change")


def test_formatting_failures_are_not_mistaken_for_rounding():
    assert auto_tag("[c] stdout_diff\n-ACCOUNT\u00b7ACC0\u00b7BALANCE:\u00b7\u00b70.00\n+ACCOUNT\u00b7ACC0\u00b7BALANCE:\u00b7\u00b7000") == "number_format"
    assert auto_tag("[c] stdout_diff\n-TAXPAYERS:\u00b7008\u00b7TOTAL:\u00b750.01\n+TAXPAYERS:\u00b78\u00b7TOTAL:\u00b750.01") == "number_format"


def test_truncated_diff_views_are_compared_pairwise():
    t = ("[c] stdout_diff\n-A\u00b7\u00b710.00\n-B\u00b7\u00b720.00\n-C\u00b7\u00b730.00\n+A\u00b7010.00\n+B\u00b7020.00\n... 4 more differing lines")
    assert auto_tag(t) == "number_format"


def test_hand_labels_are_merged(tmp_path):
    from core.taxonomy import load_labels
    d = tmp_path / "run" / "modal" / "p" / "sample0"
    d.mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({"program": "p", "provider": "modal", "sample": 0, "status": "verified",
        "repairs_used": 1, "single_shot_ok": False, "attempts": [{"failure": "BUILD ERROR:\nx"}]}))
    lab = tmp_path / "l.csv"
    lab.write_text("run,label,notes\nmodal/p/sample0,compile: unused variable,n\n")
    row = collect_failures(tmp_path / "run", load_labels(lab))[0]
    assert row["label"] == "compile: unused variable" and row["notes"] == "n"


def test_auto_labels_from_real_compiler_messages():
    from core.taxonomy import auto_label
    b = lambda m: "BUILD ERROR:\n# go_harness\n" + m
    assert auto_label(b("./main.go:79:2: declared and not used: qd")) == "compile: unused variable"
    assert auto_label(b("./main.go:79:2: declared and not used: q\n./main.go:58:7: assignment mismatch: 1 variable but a.QuoRem returns 2 values")) == "compile: hallucinated or misused library API"
    assert auto_label(b("abs.GreaterOrEqual undefined (type decimal.Decimal has no field or method GreaterOrEqual)")) == "compile: hallucinated or misused library API"
    assert auto_label(b("cannot use int64(scale) (value of type int64) as int32 value in argument to v.StringFixed")) == "compile: integer or struct type mismatch"
    assert auto_label(b("invalid operation: intDigits + scale (mismatched types int and int32)")) == "compile: integer or struct type mismatch"
    assert auto_label(b("./main.go:244:102: syntax error: unexpected ) at end of statement")) == "compile: syntax error"
    assert auto_label("[case-01] crash\nexit code 2\npanic: runtime error: index out of range [5] with length 5") == "runtime: index out of range"


def test_auto_labels_from_the_repair_diff():
    from core.taxonomy import auto_label
    diff = "--- first attempt\n+++ final\n@@\n-fmt.Sscan(t, &n)\n+n, err := strconv.ParseInt(t, 10, 64)"
    assert auto_label("[c] stdout_diff\n-X 5.00\n+X 0.00", diff).startswith("library semantics: fmt.Sscan")
    diff2 = "-onePointFive := decimal.New(15, 1)\n+onePointFive := decimal.New(15, -1)"
    assert auto_label("[c] stdout_diff\n-X 130.00\n+X 9,040.00", diff2) == "library semantics: decimal.New exponent sign"
    assert auto_label("[c] stdout_diff\n-T 8\n+T 008", "") == "COBOL formatting: numeric-edited or zoned output"


def test_hand_labels_win_over_auto_labels(tmp_path):
    from core.taxonomy import load_labels
    d = tmp_path / "run" / "m" / "p" / "sample0"
    d.mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({"program": "p", "provider": "m", "sample": 0, "status": "verified",
        "repairs_used": 1, "single_shot_ok": False, "attempts": [{"failure": "BUILD ERROR:\ndeclared and not used: x"}]}))
    lab = tmp_path / "l.csv"
    lab.write_text("run,label,notes\nm/p/sample0,my own label,why\n")
    r = collect_failures(tmp_path / "run", load_labels(lab))[0]
    assert (r["label"], r["label_source"]) == ("my own label", "hand")
    r2 = collect_failures(tmp_path / "run", {})[0]
    assert (r2["label"], r2["label_source"]) == ("compile: unused variable", "auto")
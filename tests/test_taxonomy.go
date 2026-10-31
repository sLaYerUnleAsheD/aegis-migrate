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
    assert got[0]["run"] == "modal/p/sample0" and got[0]["label"] == ""
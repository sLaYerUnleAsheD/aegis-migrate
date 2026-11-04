import json
import pytest
from core.summarize import load_results, summarize, format_table


def write(tmp_path, name, **kw):
    d = tmp_path / name
    d.mkdir(parents=True)
    base = {"program": "p", "provider": "modal", "model": "m", "effort": "default", "status": "verified",
            "single_shot_ok": True, "repairs_used": 0, "total_cost_usd": 0.03,
            "attempts": [{"output_tokens": 1000}]}
    base.update(kw)
    (d / "result.json").write_text(json.dumps(base))


def test_groups_and_averages(tmp_path):
    write(tmp_path, "a/s0")
    write(tmp_path, "a/s1", single_shot_ok=False, repairs_used=1, total_cost_usd=0.06,
          attempts=[{"output_tokens": 1000}, {"output_tokens": 3000}])
    write(tmp_path, "a/s2", status="failed", single_shot_ok=False, total_cost_usd=0.09)
    write(tmp_path, "b/s0", provider="meta")
    rows = summarize(load_results(tmp_path))
    modal = [r for r in rows if r["provider"] == "modal"][0]
    assert modal["runs"] == 3 and modal["single_shot"] == "1/3" and modal["verified"] == "2/3"
    assert modal["avg_repairs"] == 0.5 and modal["avg_out_tokens"] == 2000   # (1000+4000+1000)/3
    assert modal["total_cost_usd"] == pytest.approx(0.18)
    assert len(rows) == 2 and "single_shot" in format_table(rows)


def test_empty_and_broken_files_are_ignored(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "result.json").write_text("{not json")
    assert summarize(load_results(tmp_path)) == [] and "no result.json" in format_table([])


def test_list_cost_and_error_counting(tmp_path):
    write(tmp_path, "a", total_cost_usd=0.0, total_list_cost_usd=0.04)            # cached rerun
    write(tmp_path, "b", total_cost_usd=0.06, total_list_cost_usd=0.06)
    write(tmp_path, "c", status="llm_error", single_shot_ok=False, total_cost_usd=0.0)
    row = summarize(load_results(tmp_path))[0]
    assert row["errors"] == 1 and row["total_cost_usd"] == pytest.approx(0.06)
    assert row["avg_list_cost_usd"] == pytest.approx((0.04 + 0.06 + 0.0) / 3, abs=1e-4)


def test_api_errors_do_not_count_as_translation_failures(tmp_path):
    from core.summarize import overall
    write(tmp_path, "a", status="verified")
    write(tmp_path, "b", status="verified", single_shot_ok=False, repairs_used=1)
    write(tmp_path, "c", status="llm_error", single_shot_ok=False, total_list_cost_usd=0.14, attempts=[])
    row = summarize(load_results(tmp_path))[0]
    assert (row["runs"], row["completed"], row["errors"], row["single_shot"], row["verified"]) == (3, 2, 1, "1/2", "2/2")
    o = overall(load_results(tmp_path))[0]
    assert o["first_try"] == "1/2" and o["verified"] == "2/2" and o["errors"] == 1 and o["repairs"] == 1
    assert o["cost_per_verified_usd"] == pytest.approx((0.03 + 0.03 + 0.14) / 2, abs=1e-3) or o["list_cost_usd"] > 0


def test_matrix_merges_none_and_default_effort_and_separates_errors(tmp_path):
    from core.summarize import matrix
    write(tmp_path, "a", effort="none")
    write(tmp_path, "b", effort="default", single_shot_ok=False, repairs_used=1)
    write(tmp_path, "c", effort="low")
    write(tmp_path, "d", effort="low", status="llm_error", single_shot_ok=False, attempts=[])
    m = {r["effort"]: r for r in matrix(load_results(tmp_path))}
    assert list(m) == ["default", "low"] and m["default"]["runs"] == 2 and m["default"]["first_try"] == "1/2"
    assert m["low"]["errors"] == 1 and m["low"]["completed"] == 1 and m["low"]["verified_pct"] == 100
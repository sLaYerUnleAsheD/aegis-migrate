import zlib
from pathlib import Path
import pytest
from core.mutate import generate, run_mutation_test, _spans
from core.verify import CaseResult, VerifyResult

REF = Path("benchmark/reference_go/simple_interest/main.go").read_text()


def test_mutants_differ_and_are_deterministic():
    a = generate(REF)
    b = generate(REF)
    assert a and [m.source for m in a] == [m.source for m in b]
    assert all(m.source != REF for m in a) and len({m.source for m in a}) == len(a)


def test_expected_operators_appear_for_the_reference_program():
    ops = {m.operator for m in generate(REF)}
    assert {"slice-end-minus-one", "slice-start-plus-one", "width-minus-one", "width-plus-one",
            "drop-space-in-format", "gt-to-ge", "blank-literal-to-empty"} <= ops


def test_nothing_is_mutated_inside_comments_or_strings_for_code_operators():
    src = 'package main\n// x.Round(2) a == b\nvar s = "y.Round(2) == z"\nfunc f(d D) D { return d.Round(2) }\n'
    muts = [m for m in generate(src) if m.operator in ("round-to-truncate", "eq-to-ne")]
    assert [m.operator for m in muts] == ["round-to-truncate"] and muts[0].line == 4


def test_each_mutant_is_a_single_edit():
    for m in generate(REF):
        assert len(m.source) - len(REF) == len(m.mutated) - len(m.original)
        i = REF.index(m.original) if m.original in REF else 0
        assert m.source.count("\n") == REF.count("\n")


def test_cap_samples_deterministically_and_keeps_order():
    full = generate(REF)
    assert len(full) > 10
    a = generate(REF, max_mutants=10, seed=3)
    b = generate(REF, max_mutants=10, seed=3)
    c = generate(REF, max_mutants=10, seed=4)
    assert len(a) == 10 and [m.source for m in a] == [m.source for m in b]
    assert [m.source for m in a] != [m.source for m in c]
    assert [m.id for m in a] == list(range(10))


def test_spans_handle_escapes_and_raw_strings():
    src = 'a := "x\\"y" // c\nb := `raw "q"` + \'\\n\'\n'
    kinds = [k for _, _, k in _spans(src)]
    assert kinds == ["string", "comment", "string", "char"]


def fake_verifier(go, cases):
    """Deterministic stand-in: ORIG passes; other sources are build errors / survivors / caught by hash."""
    h = zlib.crc32(go.encode()) % 7
    if go == REF:
        ok, built = True, True
    else:
        built, ok = h != 0, h == 1
    return VerifyResult(built=built, build_error=None if built else "err",
                        cases=[CaseResult("c", ok, "match" if ok else "stdout_diff", "")])


def test_classification_and_catch_rate():
    rep = run_mutation_test(REF, [("c", b"", None)], fake_verifier, log=lambda *_: None)
    assert rep["mutants"] == rep["caught"] + rep["survived"] + rep["build_error"] > 0
    expected = rep["caught"] / (rep["caught"] + rep["survived"])
    assert rep["catch_rate"] == pytest.approx(expected, abs=1e-4)
    assert len(rep["survivors"]) == rep["survived"]
    assert sum(sum(v.values()) for v in rep["by_operator"].values()) == rep["mutants"]


def test_refuses_to_mutate_a_program_that_does_not_verify():
    bad = lambda go, cases: VerifyResult(built=True, cases=[CaseResult("c", False, "stdout_diff", "d")])
    with pytest.raises(ValueError):
        run_mutation_test(REF, [("c", b"", None)], bad, log=lambda *_: None)


def test_no_denominator_gives_none_rate():
    only_build_errors = lambda go, c: (VerifyResult(built=True, cases=[CaseResult("c", True, "match")])
                                       if go == REF else VerifyResult(built=False, build_error="x"))
    rep = run_mutation_test(REF, [("c", b"", None)], only_build_errors, log=lambda *_: None)
    assert rep["catch_rate"] is None and rep["caught"] == 0


def test_plus_one_operator_applies_to_model_style_code():
    muts = [m for m in generate("package main\nfunc f() { WsCount = (WsCount + 1) % 100000 }\n")
            if m.operator == "plus-one-to-plus-two"]
    assert len(muts) == 1 and "(WsCount + 2)" in muts[0].source


def stress_verifier(go, cases):
    """ORIG passes. Other sources: crc%7==0 build error; ==1 survives only on the SMALL set;
    ==2 always survives (equivalent); anything else is always caught."""
    h = zlib.crc32(go.encode()) % 7
    small = len(cases) == 1
    if go == REF:
        ok, built = True, True
    else:
        built = h != 0
        ok = (h == 1 and small) or h == 2
    return VerifyResult(built=built, build_error=None if built else "err",
                        cases=[CaseResult("c", ok, "match" if ok else "stdout_diff", "")])


def test_stress_pass_separates_test_gaps_from_equivalent_mutants():
    small, big = [("c", b"", None)], [("c1", b"", None), ("c2", b"", None)]
    rep = run_mutation_test(REF, small, stress_verifier, log=lambda *_: None, stress_cases=big)
    st = rep["stress"]
    assert st["baseline_ok"] and st["caught_with_more_inputs"] + st["still_surviving"] == rep["survived"]
    flags = {s["with_more_inputs"] for s in rep["survivors"]}
    assert flags <= {"caught", "still_survives"}
    assert st["catch_rate_with_more_inputs"] == pytest.approx(
        (rep["caught"] + st["caught_with_more_inputs"]) / (rep["caught"] + rep["survived"]), abs=1e-4)
    assert st["catch_rate_with_more_inputs"] >= rep["catch_rate"]


def test_original_failing_the_stress_set_is_reported_not_hidden():
    def v(go, cases):
        ok = len(cases) == 1          # everything passes on the small set, nothing on the big one
        return VerifyResult(built=True, cases=[CaseResult("c", ok, "match" if ok else "stdout_diff", "")])
    rep = run_mutation_test(REF, [("c", b"", None)], v, log=lambda *_: None,
                            stress_cases=[("a", b"", None), ("b", b"", None)])
    assert rep["survived"] > 0 and rep["stress"]["baseline_ok"] is False
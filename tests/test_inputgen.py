from pathlib import Path
import pytest
from cobol_adapter.analyzer import analyze, record_layout
from cobol_adapter.inputgen import (generate_cases, generate_records, numeric_candidates,
                                    UnsupportedLayout, expand_fields)

PROG = Path("benchmark/programs/tier1/simple_interest.cbl")


def layout():
    return record_layout(analyze(PROG.read_text()))


def test_every_record_is_exactly_21_bytes_and_ascii():
    for label, rec in generate_records(layout(), seed=3):
        assert len(rec) == 21, label
        rec.decode("ascii")


def test_numeric_fields_are_digits_only():
    for label, rec in generate_records(layout(), seed=3):
        assert rec[6:21].decode().isdigit(), label


def test_deterministic_for_same_seed_and_different_otherwise():
    a = [c.data for c in generate_cases(layout(), seed=1)]
    b = [c.data for c in generate_cases(layout(), seed=1)]
    c = [c.data for c in generate_cases(layout(), seed=2)]
    assert a == b and a != c


def test_boundaries_are_present():
    recs = {r for _, r in generate_records(layout(), seed=0)}
    assert b"ACC006000000000010010" in recs      # principal = 0
    assert any(r[6:15] == b"999999999" for r in recs)   # principal = max
    assert any(r[6:15] == b"000000005" for r in recs)   # lowest digit 5 (rounding)


def test_numeric_candidates_stay_in_range():
    for d in (1, 2, 4, 9):
        assert all(0 <= c <= 10**d - 1 for c in numeric_candidates(d))


def test_signed_and_comp3_are_rejected_not_guessed():
    base = dict(offset=0, size=5, category="numeric", digits=5, scale=0,
                signed=False, usage="DISPLAY", occurs=None, pic="9(5)")
    with pytest.raises(UnsupportedLayout):
        expand_fields([dict(base, name="A", signed=True)])
    with pytest.raises(UnsupportedLayout):
        expand_fields([dict(base, name="B", usage="COMP-3")])


def test_cases_chunking_covers_all_records():
    cs = generate_cases(layout(), seed=0, per_file=8)
    assert sum(c.records for c in cs) == len(generate_records(layout(), seed=0))
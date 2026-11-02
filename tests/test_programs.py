"""Every benchmark program must be well formed. These checks exist because of real mistakes:
a 13-byte sample for an 11-byte record, a reserved word as PROGRAM-ID, comments past column 72."""
import json
from pathlib import Path
from cobol_adapter.analyzer import analyze, record_layout
from cobol_adapter.inputgen import generate_records, load_hints

PROGRAMS = sorted(Path("benchmark/programs").rglob("*.cbl"))
# reserved words that GnuCOBOL 3.1.2 rejects as a program name or that are risky in this role
BAD_PROGRAM_IDS = {"OVERFLOW", "LABEL", "TABLE", "STATUS", "SECTION", "PROGRAM", "DATA", "FILE"}


def record_length(a):
    lay = record_layout(a)
    return max(f["offset"] + f["size"] for f in lay)


def test_there_are_programs_in_every_tier():
    assert {p.parent.name for p in PROGRAMS} >= {"tier1", "tier2", "tier3"} and len(PROGRAMS) >= 7


def test_programs_are_inside_the_supported_subset():
    for p in PROGRAMS:
        a = analyze(p.read_text())
        assert a.unsupported == [] and a.warnings == [], (p.name, a.unsupported, a.warnings)
        assert a.program_id not in BAD_PROGRAM_IDS, (p.name, a.program_id)


def test_sample_lines_match_the_record_length():
    for p in PROGRAMS:
        sample = p.with_name(p.stem + ".sample.dat")
        assert sample.exists(), f"{p.name}: missing sample"
        n = record_length(analyze(p.read_text()))
        for i, line in enumerate(sample.read_text().split("\n")[:-1], 1):
            assert len(line) == n, f"{sample.name} line {i}: {len(line)} bytes, record is {n}"


def test_no_line_exceeds_72_columns():
    for p in PROGRAMS:
        for i, line in enumerate(p.read_text().splitlines(), 1):
            assert len(line) <= 72, f"{p.name} line {i} is {len(line)} columns"


def test_hint_files_name_real_fields_and_valid_values():
    for p in PROGRAMS:
        hints = load_hints(p)
        if not hints:
            continue
        fields = {f["name"]: f for f in record_layout(analyze(p.read_text()))}
        for name, values in hints.items():
            if name.startswith("__"):
                continue
            assert name in fields, f"{p.name}: hint for unknown field {name}"
            f = fields[name]
            for v in values:
                if f["category"] == "numeric":
                    assert isinstance(v, int) and 0 <= v <= 10 ** f["digits"] - 1, (p.name, name, v)
                else:
                    assert isinstance(v, str) and len(v) <= f["size"], (p.name, name, v)


def test_hints_guarantee_the_branches_that_matter_without_relying_on_luck():
    p = Path("benchmark/programs/tier3/order_check.cbl")
    lay = record_layout(analyze(p.read_text()))
    guaranteed = [r for _, r in generate_records(lay, seed=0, n_random=0, hints=load_hints(p))]
    assert {"N", "S", "C", "R", "X"} <= {r[5:6].decode() for r in guaranteed}   # every WHEN, plus OTHER
    assert any(r[6:9] == b"000" for r in guaranteed)                           # the zero-quantity branch
    plain = [r for _, r in generate_records(lay, seed=0, n_random=0)]
    assert not {"N", "S", "C"} <= {r[5:6].decode() for r in plain}             # no hints: left to chance


def test_inputs_for_programs_without_hints_are_unchanged_by_the_feature():
    p = Path("benchmark/programs/tier1/simple_interest.cbl")
    lay = record_layout(analyze(p.read_text()))
    assert generate_records(lay, seed=7, n_random=10) == generate_records(lay, seed=7, n_random=10, hints={})
    assert load_hints(p) == {}


def test_tier_boundaries_are_hit_by_the_commission_hints():
    p = Path("benchmark/programs/tier2/commission_tiers.cbl")
    lay = record_layout(analyze(p.read_text()))
    recs = {r[4:12] for _, r in generate_records(lay, seed=0, n_random=0, hints=load_hints(p))}
    # 1000.00, 1000.01, 5000.00, 5000.01, 20000.00, 20000.01: both sides of every tier limit
    assert {b"00100000", b"00100001", b"00500000", b"00500001", b"02000000", b"02000001"} <= recs


def test_sample_records_are_added_only_when_the_hints_ask_for_it():
    from cobol_adapter.inputgen import cases_for_program
    d = Path("benchmark/programs/tier3/date_validate.cbl")
    lay = record_layout(analyze(d.read_text()))
    data = b"".join(c.data for c in cases_for_program(d, lay))
    for line in d.with_name("date_validate.sample.dat").read_text().split("\n")[:-1]:
        assert line.encode() in data                       # every hand-written date is tested
    s = Path("benchmark/programs/tier1/simple_interest.cbl")
    assert b"".join(c.data for c in cases_for_program(s, record_layout(analyze(s.read_text())))) != b""


def test_tax_hints_expose_rounding_in_every_bracket():
    """Mutation testing found a test gap: ROUNDED vs truncation only differed in one bracket.
    Each bracket needs an income where rounding the tax changes the cents."""
    from decimal import Decimal as D, ROUND_DOWN, ROUND_HALF_UP
    p = Path("benchmark/programs/tier1/tax_calc.cbl")
    recs = [r for _, r in generate_records(record_layout(analyze(p.read_text())), seed=0, n_random=0, hints=load_hints(p))]

    def tax(inc, mode):
        qz = lambda x: x.quantize(D("0.01"), rounding=mode)
        if inc <= 10000:
            return qz(inc * D("0.10")), 1
        if inc <= 40000:
            return qz(D(1000) + (inc - 10000) * D("0.20")), 2
        return qz(D(7000) + (inc - 40000) * D("0.30")), 3

    brackets = set()
    for r in recs:
        inc = D(int(r[5:13])) / 100
        (a, br), (b, _) = tax(inc, ROUND_HALF_UP), tax(inc, ROUND_DOWN)
        if a != b:
            brackets.add(br)
    assert brackets == {1, 2, 3}
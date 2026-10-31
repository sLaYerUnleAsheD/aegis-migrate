from pathlib import Path
import pytest
from cobol_adapter.analyzer import analyze, record_layout, parse_pic, split_sentences, normalize_source

PROG = Path("benchmark/programs/tier1/simple_interest.cbl")


def test_program_basics():
    a = analyze(PROG.read_text())
    assert a.program_id == "SIMPLEINT"
    assert a.files == {"LOAN-FILE": "input.dat"}
    assert a.unsupported == []
    assert set(a.risk_features) == {"ROUNDED", "EDITED-OUTPUT"}


def test_record_layout_offsets_and_sizes():
    lay = record_layout(analyze(PROG.read_text()))
    got = [(f["name"], f["offset"], f["size"], f["scale"]) for f in lay]
    assert got == [("LR-ACCT", 0, 6, 0), ("LR-PRINCIPAL", 6, 9, 2),
                   ("LR-RATE", 15, 4, 2), ("LR-YEARS", 19, 2, 0)]


def test_perform_graph():
    a = analyze(PROG.read_text())
    g = {p.name: p.performs for p in a.paragraphs}
    assert g["MAIN-PARA"] == ["READ-PARA", "PROCESS-PARA", "SUMMARY-PARA"]
    assert g["PROCESS-PARA"] == ["READ-PARA"]


def test_go_types_use_decimal_not_float():
    go = analyze(PROG.read_text()).go_types
    assert "LrPrincipal decimal.Decimal" in go and "LrYears int64" in go
    assert "float" not in go


def test_pic_parsing():
    p = parse_pic("S9(5)V99")
    assert (p.category, p.digits, p.scale, p.signed) == ("numeric", 7, 2, True)
    e = parse_pic("Z,ZZZ,ZZ9.99")
    assert (e.category, e.size) == ("edited", 12)
    assert parse_pic("X(10)").size == 10


def test_pic_period_is_not_a_sentence_end():
    s = split_sentences("01 A PIC Z,ZZ9.99. 01 B PIC X.")
    assert s == ["01 A PIC Z,ZZ9.99", "01 B PIC X"]


def test_comment_lines_and_columns_ignored():
    src = "      * a comment line\n       01 X PIC 9.   IGNORED-SEQ-AREA\n"
    assert "comment" not in normalize_source(src)


SRC_RISKY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RISKY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  REC.
           05 AMT        PIC S9(7)V99 COMP-3.
           05 AMT-X      REDEFINES AMT PIC X(5).
           05 TBL        OCCURS 3 PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL SELECT 1 END-EXEC
           COMPUTE AMT ROUNDED = 1 ON SIZE ERROR DISPLAY "X"
           STOP RUN.
"""


def test_risk_and_unsupported_detection():
    a = analyze(SRC_RISKY)
    assert {"COMP-3", "REDEFINES", "OCCURS", "ROUNDED", "SIZE-ERROR", "SIGNED"} <= set(a.risk_features)
    assert "EXEC SQL" in a.unsupported


def test_comp3_size_and_redefines_not_additive():
    a = analyze(SRC_RISKY)
    rec = a.records[0]
    amt = rec.children[0]
    assert amt.size == 5            # 9 digits -> 9//2 + 1 bytes
    assert rec.size == 5 + 6        # AMT(5) + TBL(3*2 counted in group) ; REDEFINES adds 0


SRC_LITERAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Total.  Due: 5. "
           STOP RUN.
"""


def test_string_literals_survive_case_spaces_and_periods():
    body = analyze(SRC_LITERAL).paragraphs[0].body
    assert '"Total.  Due: 5. "' in body          # exact: case, double space, periods


def test_keywords_inside_literals_do_not_trigger_risks():
    src = SRC_LITERAL.replace('"Total.  Due: 5. "', '"ROUNDED EXEC SQL SORT"')
    a = analyze(src)
    assert a.risk_features == [] and a.unsupported == []


def test_scope_warnings():
    free = "IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\n"
    assert any("FREE" in w for w in analyze(free).warnings)
    copy = SRC_LITERAL.replace("PROCEDURE DIVISION.", "       COPY CUSTREC.\n       PROCEDURE DIVISION.")
    assert any("COPY" in w for w in analyze(copy).warnings)
    assert analyze(Path("benchmark/programs/tier1/simple_interest.cbl").read_text()).warnings == []


def test_code_past_column_72_is_flagged_but_comments_are_not():
    long_code = "       " + "DISPLAY " + "\"" + "x" * 70 + "\"."
    src = ("      * " + "c" * 80 + "\n"
           "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n"
           "       PROCEDURE DIVISION.\n       MAIN-PARA.\n" + long_code + "\n")
    warns = analyze(src).warnings
    assert any("column 72" in w and "6" in w for w in warns)       # the long CODE line (line 6)
    assert not any("lines 1" in w for w in warns)                   # the long comment (line 1) is fine
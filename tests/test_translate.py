from pathlib import Path
import pytest
from cobol_adapter.analyzer import analyze
from core import translate

PROG = Path("benchmark/programs/tier1/simple_interest.cbl")


def test_prompt_contains_program_layout_and_go_types():
    src = PROG.read_text()
    p = translate.build_prompt(src, analyze(src))
    assert "PROGRAM-ID. SIMPLEINT" in p
    assert "LR-PRINCIPAL | 6 | 9 | 9(7)V99" in p and "record length: 21 bytes" in p
    assert "LrPrincipal decimal.Decimal" in p
    assert "LOAN-FILE -> input.dat" in p


def test_rules_are_static_and_come_from_system_not_prompt():
    src = PROG.read_text()
    assert translate.RULES not in translate.build_prompt(src, analyze(src))
    assert "ROUNDED" in translate.RULES and "Shift(-2)" in translate.RULES


def test_repair_prompt_includes_previous_code_and_failure():
    src = PROG.read_text()
    p = translate.build_repair_prompt(src, analyze(src), "package main\n// v1", "-ACC002 0.01\n+ACC002 0.00")
    assert "// v1" in p and "+ACC002 0.00" in p and "complete corrected Go file" in p


def test_extract_go_variants():
    assert translate.extract_go("text\n```go\npackage main\nfunc main(){}\n```\nbye") == "package main\nfunc main(){}\n"
    assert translate.extract_go("```Go\npackage main\n```").startswith("package main")
    assert translate.extract_go("package main\nfunc main(){}").startswith("package main")
    with pytest.raises(translate.TranslationError):
        translate.extract_go("I cannot do that.")
    with pytest.raises(translate.TranslationError):
        translate.extract_go("```python\nprint(1)\n```")
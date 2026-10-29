"""Pipeline control-flow tests with a fake model, oracle and verifier (no cost, no cobc/go)."""
from pathlib import Path
import pytest
from cobol_adapter.oracle import OracleResult
from core.llm import BudgetExceeded, LLMResult, LLMTruncated
from core.pipeline import migrate
from core.verify import CaseResult, VerifyResult

PROG = Path("benchmark/programs/tier1/simple_interest.cbl")
GO = "```go\npackage main\nfunc main(){}\n```"


class FakeClient:
    provider, model = "fake", "fake-1"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def call(self, prompt, **kw):
        self.calls.append((prompt, kw))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResult(r, {"output_tokens": 100}, 0.01, False, "fake-1", "fake")


def oracle_ok(src, data):
    return OracleResult(ok=True, exit_code=0, stdout=b"golden")


def vr(passed, total=2, built=True, why="stdout_diff"):
    cases = [CaseResult(f"c{i}", i < passed, "match" if i < passed else why,
                        "" if i < passed else f"diff-{passed}") for i in range(total)]
    return VerifyResult(built=built, build_error=None if built else "boom", cases=cases)


def verifier_seq(*results):
    seq = list(results)
    return lambda go, cases: seq.pop(0)


def run(replies, results, **kw):
    c = FakeClient(replies)
    r = migrate(PROG, c, oracle=oracle_ok, verifier=verifier_seq(*results), log=lambda *_: None, **kw)
    return r, c


def test_first_attempt_passes_is_single_shot_ok():
    r, c = run([GO], [vr(2)])
    assert r["status"] == "verified" and r["single_shot_ok"] and r["repairs_used"] == 0
    assert len(c.calls) == 1 and r["total_cost_usd"] == pytest.approx(0.01)


def test_repair_fixes_it_and_baseline_is_recorded_as_failed():
    r, c = run([GO, GO], [vr(1), vr(2)])
    assert r["status"] == "verified" and not r["single_shot_ok"] and r["repairs_used"] == 1
    assert "diff-1" in c.calls[1][0]                 # failure text reaches the repair prompt
    assert r["total_cost_usd"] == pytest.approx(0.02)


def test_gives_up_after_max_repairs():
    r, c = run([GO] * 4, [vr(0, why="a"), vr(1, why="b"), vr(0, why="c"), vr(1, why="d")], max_repairs=3)
    assert r["status"] == "failed" and len(c.calls) == 4 and r["repairs_used"] == 3


def test_stops_early_when_failure_repeats():
    r, c = run([GO] * 4, [vr(1), vr(1), vr(1), vr(1)], max_repairs=3)
    assert r["status"] == "failed" and "no progress" in r["detail"] and len(c.calls) == 2


def test_build_error_goes_back_to_the_model():
    r, c = run([GO, GO], [vr(0, built=False), vr(2)])
    assert r["status"] == "verified"
    assert "BUILD ERROR" in c.calls[1][0]


def test_reply_without_code_triggers_repair():
    r, c = run(["Sorry, no code", GO], [vr(2)])
    assert r["status"] == "verified" and "NO GO CODE" in c.calls[1][0]


def test_budget_exceeded_is_reported_not_raised():
    r, _ = run([BudgetExceeded("cap")], [])
    assert r["status"] == "budget_exceeded"


def test_unsupported_program_makes_no_llm_calls(tmp_path):
    bad = tmp_path / "bad.cbl"
    bad.write_text(PROG.read_text().replace("STOP RUN.", "EXEC SQL SELECT 1 END-EXEC\n           STOP RUN."))
    c = FakeClient([])
    r = migrate(bad, c, oracle=oracle_ok, verifier=verifier_seq(), log=lambda *_: None)
    assert r["status"] == "unsupported" and c.calls == []


def test_oracle_failure_is_reported():
    c = FakeClient([])
    r = migrate(PROG, c, oracle=lambda s, d: OracleResult(ok=False, compile_error="bad cobol"),
                verifier=verifier_seq(), log=lambda *_: None)
    assert r["status"] == "oracle_failed" and "bad cobol" in r["detail"] and c.calls == []


def test_result_json_and_final_go_are_written(tmp_path):
    r, _ = run([GO], [vr(2)], out_dir=tmp_path)
    assert (tmp_path / "result.json").exists() and (tmp_path / "main.go").read_text().startswith("package main")


def test_sample_is_passed_as_cache_salt():
    r, c = run([GO], [vr(2)], sample=3)
    assert c.calls[0][1]["salt"] == "sample3" and r["sample"] == 3


def test_unwritable_output_dir_fails_before_any_model_call(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("a file where a directory is needed")
    c = FakeClient([GO])
    with pytest.raises(RuntimeError) as e:
        migrate(PROG, c, oracle=oracle_ok, verifier=verifier_seq(vr(2)),
                out_dir=blocker / "sub", log=lambda *_: None)
    assert "cannot write results" in str(e.value) and c.calls == []


def test_truncated_call_cost_is_counted_in_the_result():
    err = LLMTruncated("cut off", {"input_tokens": 1, "cached_tokens": 0, "output_tokens": 1})
    err.cost_usd = 0.05
    r, _ = run([err], [])
    assert r["status"] == "llm_error" and r["total_cost_usd"] == pytest.approx(0.05)
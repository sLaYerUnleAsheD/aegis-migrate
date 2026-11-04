import json
from pathlib import Path
from cobol_adapter.oracle import OracleResult
from core.replay import replay
from core.verify import CaseResult, VerifyResult


def make_run(tmp_path, recorded=(4, 6)):
    d = tmp_path / "demo" / "modal__simple_interest__sample0"
    d.mkdir(parents=True)
    (d / "attempt_0.go").write_text("package main // wrong")
    (d / "attempt_1.go").write_text("package main // right")
    (d / "result.json").write_text(json.dumps({
        "program": "simple_interest", "provider": "modal", "model": "m", "effort": "none",
        "attempts": [{"passed_cases": recorded[0]}, {"passed_cases": recorded[1]}]}))
    return d


def fake_verifier(go, cases):
    good = "right" in go
    n = len(cases)
    cs = [CaseResult(f"c{i}", good or i < n - 2, "match" if good or i < n - 2 else "stdout_diff",
                     "" if good or i < n - 2 else "-X 1.00\n+X 0.00") for i in range(n)]
    return VerifyResult(built=True, cases=cs)


def oracle(src, data):
    return OracleResult(ok=True, exit_code=0, stdout=b"g")


def test_replay_reverifies_each_recorded_attempt_and_matches_the_recording(tmp_path):
    log = []
    r = replay(make_run(tmp_path), oracle=oracle, verifier=fake_verifier, log=log.append)
    assert [a["ok"] for a in r["attempts"]] == [False, True] and r["final_ok"]
    assert r["matches_recording"] and any("why it failed" in l for l in log)


def test_replay_reports_when_it_differs_from_the_recording(tmp_path):
    r = replay(make_run(tmp_path, recorded=(1, 6)), oracle=oracle, verifier=fake_verifier, log=lambda *_: None)
    assert r["final_ok"] and not r["matches_recording"]
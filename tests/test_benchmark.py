import json
from pathlib import Path
import pytest
from cobol_adapter.oracle import OracleResult
from core.benchmark import CachedOracle, discover, job_dir, run_benchmark
from core.llm import LLMResult
from core.verify import CaseResult, VerifyResult

PROGS = [Path("benchmark/programs/tier1/simple_interest.cbl"),
         Path("benchmark/programs/tier2/payroll_report.cbl")]
GO = "```go\npackage main\nfunc main(){}\n```"


class FakeClient:
    def __init__(self, provider):
        self.provider, self.model, self.calls = provider, "fake", 0

    def call(self, prompt, **kw):
        self.calls += 1
        return LLMResult(GO, {"output_tokens": 10}, 0.5, False, "fake", self.provider)


def good(go, cases):
    return VerifyResult(built=True, cases=[CaseResult("c", True, "match")])


def run(tmp_path, **kw):
    clients = {}
    def factory(p):
        clients[p] = FakeClient(p)
        return clients[p]
    oracle_calls = []
    def oracle(src, data):
        oracle_calls.append((str(src), data))
        return OracleResult(ok=True, exit_code=0, stdout=b"g")
    args = dict(programs=PROGS, providers=["meta", "modal"], samples=2, client_factory=factory,
                verifier=good, out_root=tmp_path / "run", oracle=oracle, log=lambda *_: None)
    args.update(kw)
    res = run_benchmark(args.pop("programs"), args.pop("providers"), args.pop("samples"), **args)
    return res, clients, oracle_calls


def test_runs_every_program_provider_sample_and_writes_results(tmp_path):
    res, clients, _ = run(tmp_path)
    assert len(res) == 2 * 2 * 2
    for prov in ("meta", "modal"):
        for prog in PROGS:
            for s in (0, 1):
                assert (job_dir(tmp_path / "run", prov, prog, s) / "result.json").exists()


def test_resume_skips_finished_jobs_and_force_redoes_them(tmp_path):
    run(tmp_path)
    res, clients, _ = run(tmp_path)
    assert res == [] and all(c.calls == 0 for c in clients.values())
    res, _, _ = run(tmp_path, force=True)
    assert len(res) == 8


def test_cost_cap_stops_new_jobs(tmp_path):
    res, _, _ = run(tmp_path, max_cost=1.0)        # each job costs 0.5 -> 2 jobs then stop
    assert len(res) == 2


def test_oracle_runs_once_per_input_not_once_per_sample(tmp_path):
    _, _, calls = run(tmp_path, providers=["meta"], samples=3, programs=[PROGS[0]])
    assert len(calls) == len(set(calls))            # no repeated (program, input)


def test_parallel_workers_give_same_results(tmp_path):
    res, _, _ = run(tmp_path, workers=3)
    assert len(res) == 8


def test_discover_finds_tiers():
    names = {p.name for p in discover()}
    assert {"simple_interest.cbl", "payroll_report.cbl", "overflow_demo.cbl"} <= names
    assert {p.name for p in discover(tier="tier2")} == {"payroll_report.cbl"}
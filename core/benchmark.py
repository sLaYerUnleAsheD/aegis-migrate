"""Benchmark runner: every program x provider x sample, with resume and a cost cap.

    python -m core.benchmark --provider meta --provider modal --samples 3 --tier tier1

Results land in run/<provider>/<program>/sample<N>/result.json (the same place
core.pipeline writes), then core.summarize prints the comparison table.

  * resume: a job whose result.json already exists is skipped (--force to redo)
  * cost cap: stops starting new jobs once this invocation has spent --max-cost
  * the COBOL oracle runs once per (program, input), not once per sample
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cobol_adapter.oracle import run_oracle
from core.llm import LLMClient, load_env
from core.pipeline import migrate
from core.sandbox import verify_in_docker
from core.summarize import format_table, load_results, summarize
from core.verify import verify


def discover(root: str | Path = "benchmark/programs", tier: str | None = None) -> list[Path]:
    base = Path(root)
    paths = sorted(base.rglob("*.cbl"))
    return [p for p in paths if tier is None or p.parent.name == tier]


def job_dir(out_root: Path, provider: str, program: Path, sample: int) -> Path:
    return out_root / provider / program.stem / f"sample{sample}"


class CachedOracle:
    """Golden outputs depend only on (program, input bytes): compute them once."""

    def __init__(self, oracle=run_oracle):
        self._oracle, self._cache, self._lock = oracle, {}, threading.Lock()

    def __call__(self, src, data):
        key = (str(src), data)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = self._oracle(src, data)
            return self._cache[key]


def run_benchmark(programs: list[Path], providers: list[str], samples: int, *, client_factory,
                  verifier, effort="default", max_repairs: int = 3, out_root: Path = Path("run"),
                  workers: int = 1, max_cost: float | None = None, force: bool = False,
                  migrate_fn=migrate, oracle=run_oracle, log=print) -> list[dict]:
    clients = {p: client_factory(p) for p in providers}
    oracle = CachedOracle(oracle)
    jobs = [(prov, prog, s) for prog in programs for prov in providers for s in range(samples)]
    spent, lock, results = [0.0], threading.Lock(), []

    def run_one(job):
        prov, prog, s = job
        out = job_dir(out_root, prov, prog, s)
        if (out / "result.json").exists() and not force:
            log(f"skip   {prov}/{prog.stem}/sample{s} (already done)")
            return None
        with lock:
            if max_cost is not None and spent[0] >= max_cost:
                log(f"stop   {prov}/{prog.stem}/sample{s}: cost cap ${max_cost:.2f} reached")
                return None
        log(f"start  {prov}/{prog.stem}/sample{s}")
        res = migrate_fn(prog, clients[prov], max_repairs=max_repairs, effort=effort, sample=s,
                         oracle=oracle, verifier=verifier, out_dir=out, log=lambda *_: None)
        with lock:
            spent[0] += res["total_cost_usd"]
        log(f"done   {prov}/{prog.stem}/sample{s}: {res['status']} "
            f"single_shot={res['single_shot_ok']} repairs={res['repairs_used']} ${res['total_cost_usd']:.4f}")
        return res

    if workers > 1:
        # compile each COBOL program once up front so threads never race on the binary cache
        for prog in programs:
            try:
                oracle(prog, b"")
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = [r for r in ex.map(run_one, jobs) if r]
    else:
        results = [r for r in map(run_one, jobs) if r]
    log(f"this run spent ${spent[0]:.4f}")
    return results


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run the COBOL->Go benchmark.")
    ap.add_argument("--provider", action="append", default=[], help="repeatable: meta, modal, baseten")
    ap.add_argument("--samples", type=int, default=1, help="samples per program (sample0..N-1)")
    ap.add_argument("--tier", default=None, help="only programs in this folder, e.g. tier2")
    ap.add_argument("--program", action="append", default=[], type=Path, help="specific .cbl files")
    ap.add_argument("--effort", default="default")
    ap.add_argument("--max-repairs", type=int, default=3)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--max-cost", type=float, default=None, help="stop starting jobs after this many USD")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    ap.add_argument("--image", default="cobol-verify")
    ap.add_argument("--unsafe-local-exec", action="store_true")
    args = ap.parse_args(argv[1:])
    if not args.provider:
        print("give at least one --provider", file=sys.stderr)
        return 2
    if args.sandbox == "local" and not args.unsafe_local_exec:
        print("--sandbox local needs --unsafe-local-exec", file=sys.stderr)
        return 2
    load_env()
    verifier = verify if args.sandbox == "local" else (
        lambda go, cases: verify_in_docker(go, cases, image=args.image))
    programs = args.program or discover(tier=args.tier)
    effort = None if args.effort == "none" else args.effort
    run_benchmark(programs, args.provider, args.samples, client_factory=lambda p: LLMClient(p),
                  verifier=verifier, effort=effort, max_repairs=args.max_repairs,
                  workers=args.workers, max_cost=args.max_cost, force=args.force)
    print("\n" + format_table(summarize(load_results("run"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
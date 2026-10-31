"""End-to-end migration of one COBOL program.

    analyze -> generate inputs -> oracle (golden outputs) -> translate
            -> verify -> [repair -> verify] x max_repairs -> result.json

One run yields BOTH numbers you will report:
    single_shot_ok : did the very first translation pass? (the baseline)
    status         : did the verified loop eventually pass?

SECURITY: model-written Go is executed. By default it runs in the Docker
sandbox (core/sandbox.py); local execution needs --sandbox local together
with --unsafe-local-exec.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from cobol_adapter.analyzer import analyze, record_layout
from cobol_adapter.inputgen import generate_cases, load_hints
from cobol_adapter.oracle import run_oracle
from core import translate
from core.llm import BudgetExceeded, LLMClient, LLMError, load_env
from core.sandbox import verify_in_docker
from core.verify import verify


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def migrate(cbl: Path, client, *, max_repairs: int = 3, effort="default", seed: int = 0,
            n_random: int = 10, per_file: int = 8, sample: int = 0, oracle=run_oracle, verifier=verify,
            out_dir: Path | None = None, log=print) -> dict:
    cbl = Path(cbl)
    src = cbl.read_text()
    res: dict = {"program": cbl.stem, "provider": client.provider, "model": client.model,
                 "effort": (client.effective_effort(effort) if hasattr(client, "effective_effort") else str(effort)),
                 "sample": sample, "status": None, "single_shot_ok": False,
                 "repairs_used": 0, "attempts": [], "total_cost_usd": 0.0}

    def finish(status: str, **extra) -> dict:
        res["status"] = status
        res.update(extra)
        failed = res.get("failed_call_cost_usd", 0.0)
        res["total_cost_usd"] = round(sum(a["cost_usd"] for a in res["attempts"]) + failed, 6)
        # list price: stays meaningful when calls were served from the cache
        res["total_list_cost_usd"] = round(sum(a["list_cost_usd"] for a in res["attempts"]) + failed, 6)
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "result.json").write_text(json.dumps(res, indent=2))
        return res

    # Fail fast, BEFORE any paid model call, if results cannot be saved.
    if out_dir:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            probe = out_dir / ".write_test"
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            raise RuntimeError(
                f"cannot write results to '{out_dir}': {e}. A root-owned folder left behind by "
                f"Docker is the usual cause; fix with: sudo chown -R $USER:$USER {out_dir.parent}") from e

    a = analyze(src)
    res["risk_features"], res["warnings"] = a.risk_features, a.warnings
    if a.unsupported:
        return finish("unsupported", detail=a.unsupported)

    # 1. Golden outputs from the real COBOL program.
    cases = []
    for c in generate_cases(record_layout(a), seed=seed, n_random=n_random, per_file=per_file,
                           hints=load_hints(cbl)):
        g = oracle(cbl, c.data)
        if not g.ok:
            return finish("oracle_failed", detail=g.compile_error or g.stderr.decode("utf-8", "replace")[:500])
        cases.append((c.name, c.data, g))
    res["cases"] = len(cases)
    log(f"[{cbl.stem}] {len(cases)} test cases, golden outputs captured")

    # 2. Translate, verify, repair.
    go, failure, prev_failure = "", "", None
    try:
        for n in range(max_repairs + 1):
            kind = "translate" if n == 0 else f"repair{n}"
            prompt = (translate.build_prompt(src, a) if n == 0
                      else translate.build_repair_prompt(src, a, go, failure))
            r = client.call(prompt, system=translate.RULES, effort=effort, tag=f"{cbl.stem}:{kind}",
                            salt=f"sample{sample}" if sample else "")
            att = {"n": n, "kind": kind, "cost_usd": r.cost_usd,
                   "list_cost_usd": r.list_cost_usd or r.cost_usd, "cached": r.cached,
                   "output_tokens": r.usage["output_tokens"], "built": False,
                   "passed_cases": 0, "failure": ""}
            res["attempts"].append(att)
            try:
                go = translate.extract_go(r.text)
            except translate.TranslationError as e:
                failure = f"NO GO CODE: {e}. Reply with one complete Go file in a ```go block."
                att["failure"] = failure
                log(f"  {kind}: no code block in reply")
                continue
            vr = verifier(go, cases)
            att.update(built=vr.built, passed_cases=vr.passed)
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"attempt_{n}.go").write_text(go)
            log(f"  {kind}: built={vr.built} passed {vr.passed}/{len(cases)}  cost=${r.cost_usd:.4f}")
            if n == 0:
                res["single_shot_ok"] = vr.ok
            if vr.ok:
                res["repairs_used"] = n
                if out_dir:
                    (out_dir / "main.go").write_text(go)
                return finish("verified", final_go=go)
            failure = vr.failure_summary()
            att["failure"] = failure[:1500]
            if prev_failure is not None and _digest(failure) == prev_failure:
                res["repairs_used"] = n
                return finish("failed", detail="no progress: identical failure after repair", final_go=go)
            prev_failure = _digest(failure)
    except BudgetExceeded as e:
        return finish("budget_exceeded", detail=str(e), final_go=go)
    except LLMError as e:
        res["failed_call_cost_usd"] = round(getattr(e, "cost_usd", 0.0), 6)
        return finish("llm_error", detail=str(e), final_go=go)

    res["repairs_used"] = max_repairs
    return finish("failed", detail=f"still failing after {max_repairs} repairs", final_go=go)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Migrate one COBOL program to Go and verify it.")
    ap.add_argument("program", type=Path)
    ap.add_argument("--provider", default="meta")
    ap.add_argument("--model", default=None)
    ap.add_argument("--effort", default="default", help="low|medium|high|none|default")
    ap.add_argument("--max-repairs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-random", type=int, default=10)
    ap.add_argument("--sample", type=int, default=0,
                    help="draw a fresh model sample (bypasses the cache); use 1..N for variance runs")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--sandbox", choices=["docker", "local"], default="docker",
                    help="where model-written Go runs (default: docker, no network)")
    ap.add_argument("--image", default="cobol-verify", help="Docker image for --sandbox docker")
    ap.add_argument("--unsafe-local-exec", action="store_true",
                    help="required with --sandbox local: run model-written Go on this machine")
    args = ap.parse_args(argv[1:])
    if args.sandbox == "local" and not args.unsafe_local_exec:
        print("Refusing to execute model-written Go locally. Use --sandbox docker (default) or "
              "add --unsafe-local-exec.", file=sys.stderr)
        return 2
    verifier = verify if args.sandbox == "local" else (
        lambda go, cases: verify_in_docker(go, cases, image=args.image))
    load_env()
    effort = None if args.effort == "none" else args.effort
    client = LLMClient(args.provider, model=args.model)
    # one folder per provider and sample, so runs never overwrite each other
    out = args.out or Path("run") / args.provider / args.program.stem / f"sample{args.sample}"
    res = migrate(args.program, client, max_repairs=args.max_repairs, effort=effort,
                  seed=args.seed, n_random=args.n_random, sample=args.sample, verifier=verifier, out_dir=out)
    print(f"\nstatus={res['status']}  single_shot_ok={res['single_shot_ok']}  "
          f"repairs={res['repairs_used']}  cost=${res['total_cost_usd']:.4f}  "
          f"spent_total=${client.spent():.4f}\nresult: {out / 'result.json'}")
    return 0 if res["status"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
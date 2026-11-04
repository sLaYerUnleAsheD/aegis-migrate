"""Re-verify a RECORDED run with the real COBOL oracle and the real Go toolchain.

    python -m core.replay demo/modal__payroll_report__sample1 --local

Only the model's text is replayed (the attempt_N.go files saved by the pipeline): there is no API
call and no key. Everything else is recomputed on your machine: the COBOL program is compiled and
run for the golden outputs, each recorded attempt is built and run on the same generated inputs,
and the diff that triggered the repair is printed. The result is compared with what was recorded.

Run it inside the Docker image: the container is the sandbox.
    docker run --rm --network none cobol-verify python -m core.replay demo/<run> --local
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from cobol_adapter.analyzer import analyze, record_layout
from cobol_adapter.inputgen import cases_for_program
from cobol_adapter.oracle import run_oracle
from core.verify import verify


def replay(run_dir: Path, *, programs: str = "benchmark/programs", oracle=run_oracle, verifier=verify,
           log=print) -> dict:
    run_dir = Path(run_dir)
    rec = json.loads((run_dir / "result.json").read_text())
    program = rec["program"]
    cbl = next(Path(programs).rglob(f"{program}.cbl"))
    a = analyze(cbl.read_text())
    cases = []
    for c in cases_for_program(cbl, record_layout(a), 0, 10, 8):
        cases.append((c.name, c.data, oracle(cbl, c.data)))
    log(f"{program}: recorded by {rec['provider']} ({rec.get('model')}), effort {rec.get('effort')}")
    log(f"  COBOL compiled and run on {len(cases)} generated input files: golden outputs captured")
    files = sorted(run_dir.glob("attempt_*.go"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    out, same = [], True
    for i, f in enumerate(files):
        vr = verifier(f.read_text(), cases)
        recorded = (rec.get("attempts") or [{}] * (i + 1))[i].get("passed_cases")
        ok = vr.ok
        out.append({"attempt": i, "built": vr.built, "passed": vr.passed, "total": len(cases), "ok": ok})
        same &= recorded is None or recorded == vr.passed
        log(f"  attempt {i} (model output, replayed): built={vr.built} passed {vr.passed}/{len(cases)}"
            + ("" if recorded is None else f"   [recorded: {recorded}]"))
        if not ok:
            log("    why it failed:\n      " + vr.failure_summary(1)[:700].replace("\n", "\n      "))
        else:
            break
    final_ok = bool(out) and out[-1]["ok"]
    log(f"  => {'VERIFIED' if final_ok else 'NOT VERIFIED'}; "
        f"{'matches the recording' if same else 'DIFFERS from the recording'}")
    return {"program": program, "attempts": out, "final_ok": final_ok, "matches_recording": same}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Re-verify a recorded run without any API call.")
    ap.add_argument("run_dir", type=Path, nargs="?")
    ap.add_argument("--local", action="store_true", required=False, help="run Go here (use inside the Docker image)")
    ap.add_argument("--list", action="store_true", help="list recorded runs under demo/")
    a = ap.parse_args(argv[1:])
    if a.list or a.run_dir is None:
        for p in sorted(Path("demo").glob("*/result.json")):
            print(p.parent)
        return 0
    if not a.local:
        print("Model-written Go will run on this machine. Use it inside the Docker image with --local, "
              "e.g. docker run --rm --network none cobol-verify python -m core.replay demo/<run> --local",
              file=sys.stderr)
        return 2
    return 0 if replay(a.run_dir)["final_ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
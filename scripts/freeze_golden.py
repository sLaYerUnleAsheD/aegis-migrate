"""Freeze each program's oracle output on its sample input as a golden fixture.

    python scripts/freeze_golden.py [--force]

For every benchmark/programs/**/<name>.cbl that has a <name>.sample.dat, run the
real COBOL program (3 times, to prove it is deterministic) and save its stdout to
benchmark/golden/<name>.sample.stdout. LOOK at the output before you commit it:
the golden file becomes ground truth for a regression test that runs on every
machine and compiler version (it is what catches host/container cobc drift).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cobol_adapter.oracle import check_determinism, run_oracle   # noqa: E402


def main(argv: list[str]) -> int:
    force = "--force" in argv
    out_dir = Path("benchmark/golden")
    out_dir.mkdir(parents=True, exist_ok=True)
    rc = 0
    for cbl in sorted(Path("benchmark/programs").rglob("*.cbl")):
        sample = cbl.with_name(cbl.stem + ".sample.dat")
        if not sample.exists():
            print(f"skip       {cbl.stem}: no {sample.name}")
            continue
        data = sample.read_bytes()
        res = run_oracle(cbl, data)
        if not res.ok:
            print(f"FAILED     {cbl.stem}: {res.compile_error or res.stderr.decode('utf-8', 'replace')}")
            rc = 1
            continue
        if res.files:
            print(f"skip       {cbl.stem}: writes output files (not supported by this fixture)")
            continue
        if not check_determinism(cbl, data, runs=3):
            print(f"FAILED     {cbl.stem}: output differs between runs")
            rc = 1
            continue
        target = out_dir / f"{cbl.stem}.sample.stdout"
        if target.exists() and target.read_bytes() == res.stdout:
            print(f"unchanged  {target}")
        elif target.exists() and not force:
            print(f"CHANGED    {target}: differs from the frozen file (use --force to overwrite)")
            rc = 1
        else:
            target.write_bytes(res.stdout)
            print(f"wrote      {target}  ({len(res.stdout)} bytes)")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
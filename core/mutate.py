"""Mutation testing for the verifier: how many plausible bugs does it catch?

Take a Go translation that PASSED verification, inject one small bug at a time
(round -> truncate, off-by-one field slice, wrong zero-padding width, dropped
space in a format string, ...) and re-verify each mutant against the real COBOL
output. A mutant is

    caught       the verifier failed it (the bug was detected)
    survived     the verifier passed it (a test gap, or an equivalent mutant)
    build_error  it no longer compiles (not a useful mutant; excluded from the rate)

    catch rate = caught / (caught + survived)

This needs no model calls, so it costs nothing. Survivors are listed so you can
tell test gaps from harmless (equivalent) mutants, and the rate should rise when
you give the verifier more test inputs (--n-random).

    python -m core.mutate run/modal/simple_interest/sample0/main.go \
        benchmark/programs/tier1/simple_interest.cbl --max 40
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from bisect import bisect_right
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable


@dataclass
class Mutant:
    id: int
    operator: str
    line: int
    original: str
    mutated: str
    source: str


@dataclass(frozen=True)
class Op:
    name: str
    pattern: re.Pattern
    repl: Callable[[re.Match], str | None]
    where: str            # "code": outside strings/comments | "string": inside a string literal
                          # | "literal": the match must be an entire string literal


def _spans(src: str) -> list[tuple[int, int, str]]:
    """(start, end, kind) of every comment, string and rune literal."""
    spans, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            spans.append((i, j, "comment")); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            spans.append((i, j, "comment")); i = j
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            spans.append((i, min(j + 1, n), "string")); i = j + 1
        elif c == "`":
            j = src.find("`", i + 1)
            j = n - 1 if j == -1 else j
            spans.append((i, j + 1, "string")); i = j + 1
        elif c == "'":
            j = i + 1
            while j < n and src[j] != "'":
                j += 2 if src[j] == "\\" else 1
            spans.append((i, min(j + 1, n), "char")); i = j + 1
        else:
            i += 1
    return spans


def _re(p: str) -> re.Pattern:
    return re.compile(p)


SLICE = _re(r"\[(\d+):(\d+)\]")
WIDTH = _re(r"%0(\d+)d")
SHIFT = _re(r"\.Shift\((-?\d+)\)")

OPS: list[Op] = [
    Op("round-to-truncate", _re(r"\.Round\("), lambda m: ".Truncate(", "code"),
    Op("truncate-to-round", _re(r"\.Truncate\("), lambda m: ".Round(", "code"),
    Op("shift-plus-one", SHIFT, lambda m: f".Shift({int(m.group(1)) + 1})", "code"),
    Op("shift-minus-one", SHIFT, lambda m: f".Shift({int(m.group(1)) - 1})", "code"),
    Op("slice-end-minus-one", SLICE,
       lambda m: f"[{m.group(1)}:{int(m.group(2)) - 1}]" if int(m.group(2)) - 1 > int(m.group(1)) else None, "code"),
    Op("slice-start-plus-one", SLICE,
       lambda m: f"[{int(m.group(1)) + 1}:{m.group(2)}]" if int(m.group(1)) + 1 < int(m.group(2)) else None, "code"),
    Op("add-to-sub", _re(r"\.Add\("), lambda m: ".Sub(", "code"),
    Op("sub-to-add", _re(r"\.Sub\("), lambda m: ".Add(", "code"),
    Op("mul-to-add", _re(r"\.Mul\("), lambda m: ".Add(", "code"),
    Op("plus-one-to-plus-two", _re(r"\+\s*1\b"), lambda m: "+ 2", "code"),
    Op("gt-to-ge", _re(r"(?<![<>=!])>(?![>=])"), lambda m: ">=", "code"),
    Op("lt-to-le", _re(r"(?<![<>=!-])<(?![<=-])"), lambda m: "<=", "code"),
    Op("eq-to-ne", _re(r"=="), lambda m: "!=", "code"),
    Op("ne-to-eq", _re(r"!="), lambda m: "==", "code"),
    Op("width-minus-one", WIDTH, lambda m: f"%0{int(m.group(1)) - 1}d" if int(m.group(1)) > 1 else None, "string"),
    Op("width-plus-one", WIDTH, lambda m: f"%0{int(m.group(1)) + 1}d", "string"),
    Op("drop-space-in-format", _re(r"%s %s"), lambda m: "%s%s", "string"),
    Op("blank-literal-to-empty", _re(r'" "'), lambda m: '""', "literal"),
]


def generate(source: str, max_mutants: int | None = None, seed: int = 0) -> list[Mutant]:
    """All single-edit mutants of `source` (deterministic order); sampled if over the cap."""
    spans = _spans(source)
    starts = [s for s, _, _ in spans]

    def kind_at(pos: int) -> str | None:
        i = bisect_right(starts, pos) - 1
        return spans[i][2] if i >= 0 and pos < spans[i][1] else None

    muts: list[Mutant] = []
    seen = {source}
    for op in OPS:
        for m in op.pattern.finditer(source):
            k = kind_at(m.start())
            if op.where == "code" and k is not None:
                continue
            if op.where == "string" and k != "string":
                continue
            if op.where == "literal":
                if k != "string" or not any(s == m.start() and e == m.end() for s, e, kk in spans if kk == "string"):
                    continue
            r = op.repl(m)
            if r is None:
                continue
            new = source[: m.start()] + r + source[m.end():]
            if new in seen:
                continue
            seen.add(new)
            line = source.count("\n", 0, m.start()) + 1
            muts.append(Mutant(len(muts), op.name, line, m.group(0), r, new))
    if max_mutants and len(muts) > max_mutants:
        keep = sorted(random.Random(seed).sample(range(len(muts)), max_mutants))
        muts = [muts[i] for i in keep]
    for i, mu in enumerate(muts):
        mu.id = i
    return muts


def run_mutation_test(go_source: str, cases, verifier, *, max_mutants: int | None = None,
                      seed: int = 0, log=print, stress_cases=None) -> dict:
    """cases: (name, input_bytes, golden OracleResult) triples; verifier(go, cases) -> VerifyResult.

    stress_cases (optional): a LARGER set of test cases. Survivors are re-verified against it:
    a survivor it catches was a gap in the small test set; one that still survives is most
    likely an equivalent mutant (a change that cannot alter this program's output)."""
    base = verifier(go_source, cases)
    if not base.ok:
        raise ValueError("the ORIGINAL program does not pass verification; "
                         "mutation-test only translations that verified")
    mutants = generate(go_source, max_mutants, seed)
    by_op: dict[str, dict[str, int]] = {}
    survivors, counts = [], {"caught": 0, "survived": 0, "build_error": 0}
    for mu in mutants:
        vr = verifier(mu.source, cases)
        status = "build_error" if not vr.built else ("survived" if vr.ok else "caught")
        counts[status] += 1
        by_op.setdefault(mu.operator, {"caught": 0, "survived": 0, "build_error": 0})[status] += 1
        if status == "survived":
            survivors.append({"id": mu.id, "operator": mu.operator, "line": mu.line,
                              "original": mu.original, "mutated": mu.mutated})
        log(f"  mutant {mu.id:>3} {mu.operator:<24} line {mu.line:<4} {status}")
    denom = counts["caught"] + counts["survived"]
    stress = None
    if stress_cases and survivors:
        if not verifier(go_source, stress_cases).ok:
            stress = {"baseline_ok": False, "test_cases": len(stress_cases),
                      "note": "the ORIGINAL translation fails the larger test set: a real bug"}
        else:
            by_id = {m.id: m for m in mutants}
            more = 0
            for sv in survivors:
                vr = verifier(by_id[sv["id"]].source, stress_cases)
                sv["with_more_inputs"] = "caught" if (vr.built and not vr.ok) else "still_survives"
                more += sv["with_more_inputs"] == "caught"
                log(f"  stress  mutant {sv['id']:>3} {sv['operator']:<24} {sv['with_more_inputs']}")
            stress = {"baseline_ok": True, "test_cases": len(stress_cases),
                      "caught_with_more_inputs": more, "still_surviving": len(survivors) - more,
                      "catch_rate_with_more_inputs": round((counts["caught"] + more) / denom, 4)}
    return {"original_passes": True, "mutants": len(mutants), **counts,
            "catch_rate": round(counts["caught"] / denom, 4) if denom else None,
            "by_operator": by_op, "survivors": survivors, "test_cases": len(cases), "stress": stress}


def main(argv: list[str]) -> int:
    from cobol_adapter.analyzer import analyze, record_layout
    from cobol_adapter.inputgen import generate_cases, load_hints
    from cobol_adapter.oracle import run_oracle
    from core.sandbox import verify_in_docker
    from core.verify import verify

    ap = argparse.ArgumentParser(description="Mutation-test the verifier on a verified Go translation.")
    ap.add_argument("go_file", type=Path)
    ap.add_argument("program", type=Path, help="the original .cbl")
    ap.add_argument("--max", type=int, default=40, help="max mutants (random sample, seeded)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--input-seed", type=int, default=0)
    ap.add_argument("--n-random", type=int, default=10, help="random test records (more = stronger verifier)")
    ap.add_argument("--stress-n-random", type=int, default=0,
                    help="re-check survivors against a larger test set with this many random records")
    ap.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    ap.add_argument("--image", default="cobol-verify")
    ap.add_argument("--unsafe-local-exec", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv[1:])
    if args.sandbox == "local" and not args.unsafe_local_exec:
        print("--sandbox local needs --unsafe-local-exec", file=sys.stderr)
        return 2
    verifier = verify if args.sandbox == "local" else (lambda go, c: verify_in_docker(go, c, image=args.image))

    a = analyze(args.program.read_text())
    cases = []
    for c in generate_cases(record_layout(a), seed=args.input_seed, n_random=args.n_random, per_file=8,
                            hints=load_hints(args.program)):
        g = run_oracle(args.program, c.data)
        if not g.ok:
            print(f"oracle failed on {c.name}: {g.compile_error or g.stderr!r}", file=sys.stderr)
            return 1
        cases.append((c.name, c.data, g))
    stress_cases = None
    if args.stress_n_random > 0:
        stress_cases = []
        for c in generate_cases(record_layout(a), seed=args.input_seed, n_random=args.stress_n_random,
                                per_file=8, hints=load_hints(args.program)):
            g = run_oracle(args.program, c.data)
            if not g.ok:
                print(f"oracle failed on stress case {c.name}", file=sys.stderr)
                return 1
            stress_cases.append((c.name, c.data, g))
    print(f"{len(cases)} test cases" + (f" (+{len(stress_cases)} stress)" if stress_cases else "")
          + f"; mutating {args.go_file}")
    rep = run_mutation_test(args.go_file.read_text(), cases, verifier,
                            max_mutants=args.max, seed=args.seed, stress_cases=stress_cases)
    print(f"\nmutants={rep['mutants']} caught={rep['caught']} survived={rep['survived']} "
          f"build_errors={rep['build_error']}  catch_rate={rep['catch_rate']}")
    for s in rep["survivors"]:
        extra = f"  [{s['with_more_inputs']}]" if "with_more_inputs" in s else ""
        print(f"  SURVIVED #{s['id']} {s['operator']} line {s['line']}: {s['original']!r} -> {s['mutated']!r}{extra}")
    if rep["stress"]:
        st = rep["stress"]
        if st["baseline_ok"]:
            print(f"with {st['test_cases']} test files: catch_rate={st['catch_rate_with_more_inputs']}  "
                  f"({st['caught_with_more_inputs']} more caught, {st['still_surviving']} likely equivalent)")
        else:
            print("WARNING: " + st["note"])
    out = args.out or Path("run/mutation") / f"{args.program.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
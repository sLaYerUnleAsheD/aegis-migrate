# Aegis Migrate: COBOL → Go migration that proves itself

> Agents can write the Go. Nobody can trust it without evidence. This is the evidence layer.

An agent that migrates legacy COBOL batch programs to Go and **proves equivalence**: it runs the original
COBOL and the Go translation on the same generated inputs and diffs every output byte. When they differ,
the diff goes back to the model, which repairs the code, up to a retry cap.

Built solo for the **Meta Global AI Developer Hackathon** (Indie Developer track, Oct 26 – Nov 4, 2026),
in the *Push the Frontier* category: giving a machine a new capability that can be checked.

## Why this exists

Banks and insurers still run COBOL nobody can fully verify. An LLM will happily translate it, and the result
*looks* right. But COBOL has behaviours that look innocent and are not: implied decimal points, `ROUNDED` versus
truncation, zero-suppressed edited fields, silent high-order truncation, scope terminators that change which
statements belong to a branch. A translation that reads correctly can be wrong on one record in a thousand.
Reading code does not find that. **Running both programs and comparing outputs does.**

## How it works

```
COBOL source
  ├─ analyzer (no LLM)       data layout, PIC clauses, paragraphs, risk features, scope warnings ─┐
  ├─ input generator         boundary + rounding + seeded random fixed-width files, plus          │
  │                          optional per-program hints for the codes a program branches on        │
  ├─ oracle (GnuCOBOL)       runs the REAL program → golden outputs                               ▼
  ├─ translator (Meta models)  whole program + Go struct skeleton → Go                        verifier
  └─ repair loop (max 3)     failing diff goes back to the model ──────────────────────────  Docker sandbox:
                                                                                              build Go, run every case,
                                                                                              byte-for-byte diff vs golden
```

* **Oracle, not opinion.** Ground truth is the output of the original program compiled with GnuCOBOL.
* **Inputs come from the data definitions** (zero, max, max-1, lowest-digit-5 for rounding, random magnitudes).
  A small `<program>.hints.json` adds the values a program branches on (status codes, tier limits), because
  random letters almost never reach `WHEN "S"`.
* **Model-written Go never runs on the host.** It runs in a Docker container with no network, all Linux
  capabilities dropped, a non-root user, and CPU / memory / process limits. API keys are never passed in.
* **Every run is measured:** first-attempt pass (the single-shot baseline), final pass after repairs, repairs
  used, tokens, and cost at list price (also for cache hits).
* **The verifier is itself tested** by mutation: inject small bugs into a *verified* translation and measure how
  many it catches (`core/mutate.py`).

## Meta models used

| Model | Via | Used for |
|---|---|---|
| Muse Spark 1.3 | Meta Model API | translation + repair |
| Muse Spark Open (816B, 42B active) | Modal shared Endpoints | translation + repair, open-weights path |
| Muse Spark Open (`meta-models/muse-spark-open-1026`) | Baseten Model APIs | same weights, different serving stack |

All three go through one client (`core/llm.py`) with a disk cache, a per-provider spend cap and exact cost accounting.

## Results so far (preliminary: 15 runs, 3 programs; the full benchmark replaces this table)

| Provider | Runs | First attempt passed | Passed after repair | Repairs used | Output tokens / run | List cost / run |
|---|---|---|---|---|---|---|
| Meta Spark 1.3 | 6 | 5 / 6 | 6 / 6 | 1 | ~7,100 – 7,900 | ~$0.03 – 0.04 |
| Modal, Spark Open | 8 | 5 / 8 | 8 / 8 | 3 | ~8,800 – 10,100 | ~$0.04 – 0.05 |
| Baseten, Spark Open | 1 | 1 / 1 | 1 / 1 | 0 | ~28,900 | ~$0.12 |

Pooled: the first translation passed in 11 of 15 runs (73%); with verification and at most one repair, 15 of 15.
Programs so far: interest calculation, discount calculation (tier 1) and payroll with a control break (tier 2).

How to read this: the sample is small and the programs are easy, so the *lift* is real but modest and the provider
differences are **not** statistically meaningful. What the data does support is the cost of correctness: roughly
$0.03 – 0.05 per verified program at list price. Baseten's single run used about four times the tokens for the same
task; reasoning effort was not controlled there, so it is not a like-for-like comparison.

## Findings

**1. The first translation is usually right on easy programs and sometimes subtly wrong, and verification fixes it.**
Every run that failed first time was repaired from the failing diff, never needing more than one repair.

**2. A bug that boundary tests missed and random records caught.** One first attempt parsed the 2-digit `YEARS`
field with `fmt.Sscan`. Go reads a leading `0` as an octal prefix, so `"08"` and `"09"` parse as 0 and the interest
comes out as `0.00`. The boundary-focused test files all passed; the two files with random records failed. The
model repaired it from the diff alone with `strconv.ParseInt(s, 10, 64)`.
The two attempts and their diff are kept in [`docs/examples/octal-parse/`](docs/examples/octal-parse/).

**3. You cannot verify COBOL by reading it, and I proved that on myself.** My own tier-3 program had a nested
`ADD … ON SIZE ERROR ADD 1 TO X END-ADD`. The inner `ADD` takes the `END-ADD`, so the rest of the paragraph silently
became part of the `ON SIZE ERROR` branch. The program re-ran each record, adding to a total hundreds of times until
it overflowed, and printed plausible-looking numbers (`99,500.00`) that no reading of the source predicts. Only
running the real compiler showed the behaviour. The fixed program uses an out-of-line `PERFORM` and only behaviour
the COBOL standard defines. This is why the oracle is a compiler, not a model.

**4. Compiler versions matter.** The same program compiled on GnuCOBOL 3.2.0 and failed on 3.1.2 because `OVERFLOW`
is a reserved word there. Every benchmark program has a frozen golden output, and the test suite re-checks it both on
the development host (3.2.0) and inside the Docker image (3.1.2). A static check also flags code that runs past
column 72, where fixed-format COBOL silently discards text.

## How strong is the verifier? (mutation testing)

66 single-edit mutants of one verified translation (Muse Spark 1.3, interest program): rounding to truncation,
off-by-one field slices, wrong zero-padding widths, dropped spaces, flipped comparisons. **41 were caught.** The 25
survivors were triaged by hand against the source:

| Survivors | Count | Meaning |
|---|---|---|
| Equivalent mutants | 14 | cannot change output (e.g. `<` vs `<=` on string lengths where equal lengths give the same string) |
| Outside the input domain | 10 | sign / space handling in numeric parsing, padding of short records, dead branches: the supported inputs are full-width and unsigned |
| Needs ≥ 100,000 records | 1 | a counter-wrap check |

Re-checking every survivor against a larger test set (30 test files) caught none of them, which agrees with that
triage. Triage is manual and the sample is one translation; treat 41/66 as the raw figure and the table as the
interpretation.

## Quick start

Requirements: Python 3.11+, Docker, GnuCOBOL on the host for the oracle (`sudo apt install gnucobol`).

```bash
cp .env.example .env            # add your keys (never commit .env)
docker build -t cobol-verify .  # Go toolchain + GnuCOBOL + warm Go build cache
docker run --rm cobol-verify    # full test suite

# migrate one program (model call + sandboxed verification)
python -m core.pipeline benchmark/programs/tier1/simple_interest.cbl --provider meta

# the benchmark: every program x provider x sample, resumable, with a cost cap
python -m core.benchmark --provider meta --provider modal --samples 5 --max-cost 25
python -m core.summarize        # comparison table
python -m core.taxonomy --show  # every first-attempt failure, with the repair diff
python -m core.build_viewer     # viewer/index.html: a self-contained page for run/

# how strong is the verifier? (no model cost)
python -m core.mutate run/meta/simple_interest/sample0/main.go \
    benchmark/programs/tier1/simple_interest.cbl --max 0 --stress-n-random 200
```

Decimal arithmetic in generated Go uses `shopspring/decimal`, vendored in `go_harness/` so sandboxed builds work offline.

## Repository layout

| Path | Purpose |
|---|---|
| `cobol_adapter/` | the only COBOL-aware code: `analyzer.py`, `inputgen.py`, `oracle.py` |
| `core/` | language-agnostic: `llm`, `translate`, `verify`, `sandbox`, `pipeline`, `benchmark`, `summarize`, `taxonomy`, `mutate`, `build_viewer` |
| `benchmark/programs/` | COBOL programs by tier, each with a `.sample.dat` and optional `.hints.json` |
| `benchmark/golden/` | frozen oracle output per program (regression-tests the compiler version) |
| `benchmark/reference_go/` | a hand-written Go translation used to test the verifier |
| `go_harness/` | Go module template with vendored dependencies |
| `docs/` | worked examples and the failure table |
| `scripts/` | `freeze_golden.py`, `vendor_decimal.sh`, Docker warm-up |
| `viewer/` | generated results page |

## Supported COBOL subset (stated honestly)

Batch programs, fixed-format source, one input file read as `LINE SEQUENTIAL`, unsigned `DISPLAY` input fields,
alphanumerics, numeric-edited output, signed working-storage fields, `OCCURS` tables, `PERFORM` (paragraph and
inline), `IF` / `EVALUATE`, `STRING` / `INSPECT`, `COMPUTE … ROUNDED`, `ON SIZE ERROR`. The analyzer **warns** about
anything outside this (copybooks, free format, `GO TO`, sections, `OCCURS DEPENDING ON`, several FDs, code past
column 72) and **refuses** `EXEC SQL/CICS`, `SORT`, `CALL`. The input generator does not yet produce signed
(overpunch), `COMP` or `COMP-3` *input* fields, nor short or malformed records.

"Verified" means *output-equivalent on the generated test inputs*, not formally proven. The mutation test measures
how sensitive those checks are, and its blind spots are the input-domain limits above.

## Provenance

All code in this repository was written during the hackathon (first commit after the Oct 26 kickoff). A prior
personal project (a CI test-failure triage service) inspired the use of caching, circuit-breaker style spend caps and
worker patterns; **no code from it was reused**. COBOL benchmark programs were written for this project. Third-party
software: GnuCOBOL (oracle), Go and `shopspring/decimal` (MIT) for generated code.

## License

MIT, see `LICENSE`.
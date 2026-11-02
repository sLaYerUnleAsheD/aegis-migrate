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

## Results (12 programs, 5 samples per program per provider; every number from `python -m core.summarize`)

| Provider | Runs | First attempt passed | Passed after repair | Repairs used | Output tokens / run | List cost / verified program |
|---|---|---|---|---|---|---|
| Meta Spark 1.3 (reasoning effort low) | 60 | 52/60 (87%) | 60/60 | 10 | ~6,672 | $0.031 |
| Muse Spark Open on Modal (default effort) | 60 | 34/60 (57%) | 60/60 | 30 | ~9,162 | $0.044 |
| Muse Spark Open on Baseten (partial, see below) | 24 | 12/13 completed | 13/13 completed | 1 | ~20,100 | ~$0.22 |

* **Verification closes the gap.** Both models end at 100% verified; the first attempt alone passes 87% (Meta) and
  57% (Modal). No program needed more than two repairs.
* **Meta's first attempts are better than Modal's** (Fisher exact p = 0.0005), but these are different models served at
  different reasoning settings, and runs of the same program are correlated, so read the p-value as indicative.
* **What predicts difficulty is numeric-edited output, not control flow.** The two programs with no numeric-edited
  output (`label_builder`, `date_validate`, the latter a "tier 3" leap-year validator) passed first time in
  20/20 runs on both providers. On the ten programs with edited output (`Z,ZZ9.99`-style pictures,
  `ROUNDED`), first-attempt pass rates are 42/50 (84%) for Meta and 24/50 (48%) for Modal
  (p = 0.0003). Tiers describe COBOL features; they do not track what LLMs find hard.
* **Baseten is not comparable yet.** 11 of its 24 runs produced nothing: the reply hit the 32,000-token output cap (each
  billed about $0.137, consistent with the cap), including all six runs of `bank_ledger`, `order_check` and `overflow_demo`.
  Its 13 completed runs used about twice Modal's tokens for the same weights, and because the hardest programs are the ones
  that failed to finish, its completed-run pass rate is flattered. Rerun with a lower reasoning effort before comparing.

## What first attempts get wrong (35 first-attempt failures, labelled by hand)

| Label | Count |
|---|---|
| compile: unused variable | 12 |
| compile: hallucinated or misused library API | 7 |
| library semantics: fmt.Sscan reads a leading zero as octal | 4 |
| compile: integer or struct type mismatch | 3 |
| COBOL formatting: numeric-edited or zoned output | 3 |
| runtime: index out of range in edited-picture formatter | 3 |
| compile: syntax error | 1 |
| I/O: input reading dropped records | 1 |
| library semantics: decimal.New exponent sign | 1 |

Go and its libraries account for 28 of 35: 23 did not compile (unused variables, methods that do not exist on
`decimal.Decimal` or that return two values, integer type mismatches) and 5 compiled but misused a library (`fmt.Sscan`
reading `08` as octal; `decimal.New(15, 1)` meaning 150, not 1.5). The COBOL-specific failures are all about **numeric-edited
formatting** (plus one case of input reading stopping early): 3 printed the wrong text and 3 crashed inside the model's own edited-picture formatter. No
failure was a wrong reading of COBOL arithmetic such as rounding or truncation. The full table is in
[`docs/failure_labels.csv`](docs/failure_labels.csv).

## Findings

**1. The first translation is often right, sometimes subtly wrong, and verification fixes every case.** All 120
Meta and Modal runs ended verified, from the failing diff or compiler message alone, with no more than two repairs.

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

**5. First attempts fail on Go and on edited-picture formatting, not on COBOL arithmetic.** See the failure table
above. The models reimplement COBOL's `Z,ZZ9.99` editing from scratch in every translation, and that reimplementation is
where both the formatting errors and the crashes live; an obvious improvement is to hand them a tested formatter
(not done yet). The sandbox build catches the compile errors in seconds.

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
python -m core.summarize        # per-program table; add --overall --markdown for the README table
python -m core.taxonomy --show  # every first-attempt failure, with the repair diff
python -m core.build_viewer     # viewer/index.html: a self-contained page for run/
python -m http.server 8000 --directory viewer   # then open http://localhost:8000

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
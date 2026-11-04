#!/usr/bin/env bash
# Copy selected recorded runs into demo/ so judges can replay them without any key.
# Edit the list, run it from the repo root, commit demo/.
set -euo pipefail
PICKS=(
  "modal/payroll_report/sample1"    # decimal.New(15, 1) is 150, not 1.5: overtime 100x too large
  "modal/simple_interest/sample0"   # fmt.Sscan reads 08 and 09 as octal
  "meta/bank_ledger/sample1"        # edited field lost its decimal point
  "modal/bank_ledger/sample1"       # crash inside the model's own edited-picture formatter
  "modal/tax_calc/sample0"          # compile error: decimal.NewFromString returns two values
)
for p in "${PICKS[@]}"; do
  src="run/$p"; dst="demo/${p//\//__}"
  mkdir -p "$dst"; cp "$src"/result.json "$src"/attempt_*.go "$dst"/
  echo "copied $src -> $dst"
done
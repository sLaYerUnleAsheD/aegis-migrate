#!/usr/bin/env bash
# One-time setup (needs network): vendor shopspring/decimal into go_harness/
# so generated Go code builds offline, e.g. inside a --network none container.
set -euo pipefail
cd "$(dirname "$0")/../go_harness"

cat > deps.go <<'GO'
package main

import _ "github.com/shopspring/decimal"
GO

go get github.com/shopspring/decimal@v1.4.0   # if this version is not found, drop the @version
go mod vendor

# Smoke test: confirm rounding matches COBOL ROUNDED and see Div's default precision.
tmp="$(mktemp -d)"
cp -r . "$tmp/src"
cat > "$tmp/src/main.go" <<'GO'
package main

import (
	"fmt"

	"github.com/shopspring/decimal"
)

func main() {
	fmt.Println(decimal.RequireFromString("0.005").Round(2))  // want 0.01
	fmt.Println(decimal.RequireFromString("-0.005").Round(2)) // want -0.01 (half away from zero)
	fmt.Println(decimal.NewFromInt(1).Div(decimal.NewFromInt(3)))
}
GO
(cd "$tmp/src" && go run -mod=vendor .)
echo "vendored OK. Commit go_harness/go.mod, go.sum, deps.go and vendor/."
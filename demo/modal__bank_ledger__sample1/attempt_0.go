package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/shopspring/decimal"
)

type LedgerRec struct { // 01 LEDGER-REC, 14 bytes
	BrBranch string          // PIC X(2) @0 len=2
	BrAcct   string          // PIC X(4) @2 len=4
	BrType   string          // PIC X(1) @6 len=1
	BrAmt    decimal.Decimal // PIC 9(5)V99 @7 len=7
}

// Standalone working-storage items (VALUE shown after '=')
var WsEofFlag string = "N" // PIC X len=1 = "N"
var WsFirstFlag string = "Y" // PIC X len=1 = "Y"
var WsPrevBranch string = "  " // PIC X(2) len=2 = SPACES
var WsPrevAcct string = "    " // PIC X(4) len=4 = SPACES
var WsBal decimal.Decimal = decimal.NewFromInt(0)       // PIC S9(7)V99 len=9 = 0
var WsBranchTot decimal.Decimal = decimal.NewFromInt(0) // PIC S9(9)V99 len=11 = 0
var WsGrandTot decimal.Decimal = decimal.NewFromInt(0)  // PIC S9(9)V99 len=11 = 0
var WsSkipped int64 = 0                                 // PIC 99 len=2 = 0
var WsAmtEd string // PIC ZZ,ZZ9.99 len=9
var WsBalEd string // PIC -Z,ZZZ,ZZ9.99 len=13
var WsTotEd string // PIC -ZZZ,ZZZ,ZZ9.99 len=15

var curRec LedgerRec
var ledgerLines []string
var ledgerIdx int

func isInputDone() bool { return WsEofFlag == "Y" }
func isFirstRecord() bool { return WsFirstFlag == "Y" }

func pow10(n int) int64 {
	var r int64 = 1
	for i := 0; i < n; i++ {
		r *= 10
	}
	return r
}

// formatPic formats val according to COBOL numeric-edited picture.
// pic may start with '-' for signed.
func formatPic(val decimal.Decimal, pic string) string {
	signed := false
	if len(pic) > 0 && pic[0] == '-' {
		signed = true
		pic = pic[1:]
	}
	// sign char
	signChar := ' '
	if signed {
		if val.IsNegative() && !val.IsZero() {
			signChar = '-'
		} else {
			signChar = ' '
		}
	}
	absVal := val.Abs()
	// Determine capacity and scale
	// capacity = count of Z and 9 before '.'
	// scale = count of 9 after '.'
	dotPos := strings.Index(pic, ".")
	var intPicPart, fracPicPart string
	if dotPos >= 0 {
		intPicPart = pic[:dotPos]
		fracPicPart = pic[dotPos+1:]
	} else {
		intPicPart = pic
		fracPicPart = ""
	}
	capacity := 0
	for _, ch := range intPicPart {
		if ch == 'Z' || ch == '9' {
			capacity++
		}
	}
	scale := 0
	for _, ch := range fracPicPart {
		if ch == '9' {
			scale++
		}
	}
	// total cents with truncation toward zero
	shifted := absVal.Shift(int32(scale)).Truncate(0)
	totalCents := shifted.IntPart() // abs value in minor units
	// integer part
	var intPart int64
	var fracPart int64
	if scale > 0 {
		p10 := pow10(scale)
		intPart = totalCents / p10
		fracPart = totalCents % p10
		if fracPart < 0 {
			fracPart = -fracPart
		}
	} else {
		intPart = totalCents
		fracPart = 0
	}
	// low-order truncation
	if capacity > 0 {
		mod := pow10(capacity)
		intPart = intPart % mod
	}
	// digits for integer part, zero padded to capacity
	digits := ""
	if capacity > 0 {
		fmtStr := fmt.Sprintf("%%0%dd", capacity)
		digits = fmt.Sprintf(fmtStr, intPart)
	}
	// placeholders in order for integer part
	var placeholders []rune
	for _, ch := range intPicPart {
		if ch == 'Z' || ch == '9' {
			placeholders = append(placeholders, ch)
		}
	}
	// determine suppression per digit position
	suppressed := make([]bool, capacity)
	inSuppress := true
	for i := 0; i < capacity; i++ {
		if inSuppress {
			if placeholders[i] == '9' {
				inSuppress = false
				suppressed[i] = false
			} else { // Z
				if digits[i] != '0' {
					inSuppress = false
					suppressed[i] = false
				} else {
					suppressed[i] = true
					// stay in suppress
				}
			}
		} else {
			suppressed[i] = false
		}
	}
	// Build core edited string (without sign)
	var coreBuilder strings.Builder
	digitIdx := 0
	// suppression flag for commas: true if still suppressing
	// This is equivalent to inSuppress before first non-suppressed digit.
	// We can track whether we have emitted a significant digit.
	significantStarted := false
	// We need to know for each digit if it will be significant; we have suppressed array.
	// For comma we decide based on whether significantStarted already.
	for _, ch := range pic {
		switch ch {
		case 'Z', '9':
			if suppressed[digitIdx] {
				coreBuilder.WriteByte(' ')
			} else {
				coreBuilder.WriteByte(digits[digitIdx])
				significantStarted = true
			}
			digitIdx++
			// after processing digit, significantStarted may be true; but if digit was suppressed we stay false
			// However digits after first non-suppressed are all significant even if zero, we already updated.
			if !suppressed[digitIdx-1] {
				significantStarted = true
			}
		case ',':
			if significantStarted {
				coreBuilder.WriteByte(',')
			} else {
				coreBuilder.WriteByte(' ')
			}
		case '.':
			coreBuilder.WriteByte('.')
		default:
			coreBuilder.WriteByte(byte(ch))
		}
	}
	// Handle fractional part: exactly scale digits, zero padded
	if scale > 0 {
		// coreBuilder already contains '.'? Actually we wrote '.' above.
		// After dot, pic contains scale '9's; we haven't written them yet because loop already handled pic after dot?
		// Our loop iterated over entire pic including after dot. For chars after dot, they are '9's. But we consumed digitIdx only for integer part.
		// We incorrectly treated fractional '9's as integer digits. Need separate handling.
		// Fix: we should not have included fractional part in the loop above.
		// Let's rebuild correctly: loop only over intPicPart + '.' + frac part handling.
	}
	// The above logic mixed integer and fractional. Re-implement properly:
	// Rebuild if scale>0 with correct separation.
	if scale > 0 {
		coreBuilder.Reset()
		digitIdx = 0
		significantStarted = false
		// integer part picture
		for _, ch := range intPicPart {
			switch ch {
			case 'Z', '9':
				if suppressed[digitIdx] {
					coreBuilder.WriteByte(' ')
				} else {
					coreBuilder.WriteByte(digits[digitIdx])
				}
				if !suppressed[digitIdx] {
					significantStarted = true
				}
				digitIdx++
			case ',':
				if significantStarted {
					coreBuilder.WriteByte(',')
				} else {
					coreBuilder.WriteByte(' ')
				}
			}
		}
		coreBuilder.WriteByte('.')
		// fractional digits
		fracStr := fmt.Sprintf("%0*d", scale, fracPart)
		coreBuilder.WriteString(fracStr)
	}
	if capacity == 0 && scale == 0 {
		// nothing?
	}
	coreStr := coreBuilder.String()
	if signed {
		return string(signChar) + coreStr
	}
	return coreStr
}

func moveAmtEd(v decimal.Decimal) {
	WsAmtEd = formatPic(v, "ZZ,ZZ9.99")
}
func moveBalEd(v decimal.Decimal) {
	WsBalEd = formatPic(v, "-Z,ZZZ,ZZ9.99")
}
func moveTotEd(v decimal.Decimal) {
	WsTotEd = formatPic(v, "-ZZZ,ZZZ,ZZ9.99")
}

func formatSkipped(v int64) string {
	return fmt.Sprintf("%02d", v)
}

// File handling
func padRight(s string, n int) string {
	if len(s) >= n {
		return s[:n]
	}
	return s + strings.Repeat(" ", n-len(s))
}

func parseAmt(s string) decimal.Decimal {
	s = strings.TrimSpace(s)
	if s == "" {
		return decimal.NewFromInt(0)
	}
	// s contains digits only, implied 2 decimals
	// may contain spaces? treat non-digit as 0?
	var n int64
	for _, ch := range s {
		if ch >= '0' && ch <= '9' {
			n = n*10 + int64(ch-'0')
		}
	}
	return decimal.New(n, -2)
}

func MAIN_PARA() {
	// OPEN
	// read file input.dat
	f, err := os.Open("input.dat")
	if err != nil {
		// if file not exists, treat as empty
		ledgerLines = []string{}
	} else {
		scanner := bufio.NewScanner(f)
		for scanner.Scan() {
			line := scanner.Text()
			// Scanner strips newline, we keep as is
			ledgerLines = append(ledgerLines, line)
		}
		f.Close()
	}
	ledgerIdx = 0
	READ_PARA()
	for !isInputDone() {
		PROCESS_PARA()
	}
	if !isFirstRecord() {
		ACCT_BREAK_PARA()
		BRANCH_BREAK_PARA()
	}
	// CLOSE - nothing
	GRAND_PARA()
}

func READ_PARA() {
	if ledgerIdx >= len(ledgerLines) {
		WsEofFlag = "Y"
		return
	}
	raw := ledgerLines[ledgerIdx]
	ledgerIdx++
	// pad to 14
	recStr := padRight(raw, 14)
	// parse
	curRec.BrBranch = recStr[0:2]
	curRec.BrAcct = recStr[2:6]
	curRec.BrType = recStr[6:7]
	amtStr := recStr[7:14]
	curRec.BrAmt = parseAmt(amtStr)
}

func PROCESS_PARA() {
	if isFirstRecord() {
		WsPrevBranch = curRec.BrBranch
		WsPrevAcct = curRec.BrAcct
		WsFirstFlag = "N"
	} else {
		if curRec.BrBranch != WsPrevBranch {
			ACCT_BREAK_PARA()
			BRANCH_BREAK_PARA()
			WsPrevBranch = curRec.BrBranch
			WsPrevAcct = curRec.BrAcct
		} else {
			if curRec.BrAcct != WsPrevAcct {
				ACCT_BREAK_PARA()
				WsPrevAcct = curRec.BrAcct
			}
		}
	}
	POST_PARA()
	READ_PARA()
}

func POST_PARA() {
	moveAmtEd(curRec.BrAmt)
	switch curRec.BrType {
	case "D":
		WsBal = WsBal.Add(curRec.BrAmt)
		fmt.Println(curRec.BrAcct + " D " + WsAmtEd)
	case "C":
		WsBal = WsBal.Sub(curRec.BrAmt)
		fmt.Println(curRec.BrAcct + " C " + WsAmtEd)
	default:
		WsSkipped++
		fmt.Println(curRec.BrAcct + " ? SKIPPED")
	}
}

func ACCT_BREAK_PARA() {
	moveBalEd(WsBal)
	fmt.Println("  ACCOUNT " + WsPrevAcct + " BALANCE:" + WsBalEd)
	WsBranchTot = WsBranchTot.Add(WsBal)
	WsBal = decimal.NewFromInt(0)
}

func BRANCH_BREAK_PARA() {
	moveTotEd(WsBranchTot)
	fmt.Println(" BRANCH " + WsPrevBranch + " TOTAL:" + WsTotEd)
	WsGrandTot = WsGrandTot.Add(WsBranchTot)
	WsBranchTot = decimal.NewFromInt(0)
}

func GRAND_PARA() {
	moveTotEd(WsGrandTot)
	fmt.Println("GRAND TOTAL:" + WsTotEd)
	fmt.Println("SKIPPED: " + formatSkipped(WsSkipped))
}

func main() {
	MAIN_PARA()
}

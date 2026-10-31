package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/shopspring/decimal"
)

type LoanRec struct { // 01 LOAN-REC, 21 bytes
	LrAcct      string          // PIC X(6) @0 len=6
	LrPrincipal decimal.Decimal // PIC 9(7)V99 @6 len=9
	LrRate      decimal.Decimal // PIC 9(2)V99 @15 len=4
	LrYears     int64           // PIC 9(2) @19 len=2
}

// Standalone working-storage items (VALUE shown after '=')
var WsEofFlag string = "N"                  // PIC X len=1 = "N"
var WsInterest decimal.Decimal = decimal.New(0, 0) // PIC 9(9)V99 len=11 = 0
var WsTotal decimal.Decimal = decimal.New(0, 0)    // PIC 9(11)V99 len=13 = 0
var WsCount int64 = 0                       // PIC 9(5) len=5 = 0
var WsPrinEd string // PIC Z,ZZZ,ZZ9.99 len=12
var WsIntEd string  // PIC ZZZ,ZZZ,ZZ9.99 len=14
var WsTotalEd string // PIC ZZ,ZZZ,ZZZ,ZZ9.99 len=17

var loanRec LoanRec

// file handling for LOAN-FILE
var loanLines []string
var loanIdx int
var currentLine string

func isInputDone() bool {
	return WsEofFlag == "Y"
}

func storeDecimal(val decimal.Decimal, intDigits int, scale int32) decimal.Decimal {
	// Truncate toward zero to scale first (COBOL store truncates without rounding unless ROUNDED)
	// val is already at correct scale for our uses, but enforce
	t := val.Truncate(scale)
	// scaled integer = t * 10^scale
	scaled := t.Shift(scale) // exact
	// modulus = 10^(intDigits+scale)
	mod := decimal.New(1, int32(intDigits)+scale)
	// quotient truncated toward zero
	// scaled / mod truncated
	q := scaled.Div(mod).Truncate(0)
	modded := scaled.Sub(q.Mul(mod))
	// handle negative remainder: q trunc toward zero gives correct low-order digits with sign
	result := modded.Shift(-scale)
	// Ensure scale exactly scale (for zero it may be 0)
	result = result.Truncate(scale)
	return result
}

func storeInt(val int64, digits int) int64 {
	mod := int64(1)
	for i := 0; i < digits; i++ {
		mod *= 10
	}
	r := val % mod
	if r < 0 {
		r += mod // not needed for positive, but keep
		// For COBOL positive overflow, negative not expected
	}
	return r
}

func parseDigitsToDecimal(s string, scale int32) decimal.Decimal {
	// s is exactly width digits field, may contain spaces
	s = strings.TrimSpace(s)
	if s == "" {
		return decimal.New(0, 0)
	}
	// remove any non-digit (should be digits only)
	// Use filter digits and sign?
	var b strings.Builder
	for _, c := range s {
		if c >= '0' && c <= '9' {
			b.WriteRune(c)
		} else if c == '-' {
			b.WriteRune(c)
		}
	}
	t := b.String()
	if t == "" || t == "-" {
		return decimal.New(0, 0)
	}
	neg := false
	if t[0] == '-' {
		neg = true
		t = t[1:]
	}
	// parse as integer
	d, err := decimal.NewFromString(t)
	if err != nil {
		return decimal.New(0, 0)
	}
	d = d.Shift(-scale)
	if neg {
		d = d.Neg()
	}
	return d
}

func parseDigitsToInt(s string) int64 {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0
	}
	var b strings.Builder
	for _, c := range s {
		if c >= '0' && c <= '9' {
			b.WriteRune(c)
		} else if c == '-' {
			b.WriteRune(c)
		}
	}
	t := b.String()
	if t == "" || t == "-" {
		return 0
	}
	var n int64
	fmt.Sscan(t, &n)
	return n
}

func formatEdited(pic string, val decimal.Decimal) string {
	// pic contains Z , 9 . characters
	dotIdx := strings.Index(pic, ".")
	var intPic, fracPic string
	if dotIdx >= 0 {
		intPic = pic[:dotIdx]
		fracPic = pic[dotIdx+1:]
	} else {
		intPic = pic
		fracPic = ""
	}
	fracDigits := 0
	for _, c := range fracPic {
		if c == 'Z' || c == '9' {
			fracDigits++
		}
	}
	intDigits := 0
	for _, c := range intPic {
		if c == 'Z' || c == '9' {
			intDigits++
		}
	}

	// absolute value for formatting (no sign handling needed)
	absVal := val.Abs()
	// Build string with exactly fracDigits fractional digits
	// Use StringFixed which rounds, but we want exact truncated value; val already truncated to scale
	// Ensure we get exact representation
	sFixed := absVal.StringFixed(int32(fracDigits)) // may round but val already exactly scaled
	// Split integer and fractional
	var intStr, fracStr string
	if fracDigits > 0 {
		parts := strings.SplitN(sFixed, ".", 2)
		intStr = parts[0]
		if len(parts) > 1 {
			fracStr = parts[1]
		} else {
			fracStr = strings.Repeat("0", fracDigits)
		}
		// pad fracStr to fracDigits
		if len(fracStr) < fracDigits {
			fracStr = fracStr + strings.Repeat("0", fracDigits-len(fracStr))
		} else if len(fracStr) > fracDigits {
			fracStr = fracStr[:fracDigits]
		}
	} else {
		intStr = sFixed
		fracStr = ""
	}
	// handle overflow: drop high-order digits
	if len(intStr) > intDigits {
		intStr = intStr[len(intStr)-intDigits:]
	}
	// pad intStr left with zeros to intDigits
	if len(intStr) < intDigits {
		intStr = strings.Repeat("0", intDigits-len(intStr)) + intStr
	}
	digits := []rune(intStr) // length intDigits

	// Build integer part output
	// Walk through intPic characters and map digits
	var outInt strings.Builder
	dIdx := 0
	seenNonZero := false
	// For suppression, we need to know if any non-zero digit has been encountered up to current digit
	// We'll iterate and for each digit position decide
	for _, c := range intPic {
		if c == ',' {
			if seenNonZero {
				outInt.WriteRune(',')
			} else {
				outInt.WriteRune(' ')
			}
		} else if c == 'Z' || c == '9' {
			d := digits[dIdx]
			dIdx++
			if c == 'Z' {
				if d != '0' {
					seenNonZero = true
				}
				if !seenNonZero {
					// still leading zero suppressed; check if all remaining digits are zero? No, suppression until first non-zero
					// For zero value, all Z become spaces
					outInt.WriteRune(' ')
				} else {
					outInt.WriteRune(d)
				}
			} else { // '9'
				// 9 always prints, and if it's non-zero it also ends suppression for following (but 9 is usually last)
				// Still need to mark seenNonZero if this digit is non-zero? Not needed after last, but for completeness
				if d != '0' {
					seenNonZero = true
				} else {
					// if value is zero, 9 will be '0'
					// if we never saw non-zero, we still print 0 for the 9
				}
				outInt.WriteRune(d)
			}
		} else {
			outInt.WriteRune(c)
		}
	}
	result := outInt.String()
	if fracDigits > 0 {
		result += "."
		// fracPic defines formatting, but for these pics it's all 9s
		// Just append fracStr digits aligned to pic
		// If fracPic contains Z's would need suppression but not here
		fIdx := 0
		for _, c := range fracPic {
			if c == 'Z' || c == '9' {
				if fIdx < len(fracStr) {
					result += string(fracStr[fIdx])
					fIdx++
				} else {
					result += "0"
				}
			} else {
				result += string(c)
			}
		}
	}
	// Ensure length equals len(pic); should be
	if len(result) < len(pic) {
		result = strings.Repeat(" ", len(pic)-len(result)) + result
	}
	return result
}

func formatCount() string {
	return fmt.Sprintf("%05d", WsCount)
}

// Paragraph functions

func readPara() {
	if loanIdx >= len(loanLines) {
		WsEofFlag = "Y"
		return
	}
	line := loanLines[loanIdx]
	loanIdx++
	// Pad to 21 with spaces if shorter
	if len(line) < 21 {
		line += strings.Repeat(" ", 21-len(line))
	} else if len(line) > 21 {
		line = line[:21]
	}
	currentLine = line
	// Parse into loanRec
	loanRec.LrAcct = line[0:6]
	loanRec.LrPrincipal = parseDigitsToDecimal(line[6:15], 2)
	loanRec.LrRate = parseDigitsToDecimal(line[15:19], 2)
	loanRec.LrYears = parseDigitsToInt(line[19:21])
}

func processPara() {
	// COMPUTE WS-INTEREST ROUNDED = LR-PRINCIPAL * LR-RATE * LR-YEARS / 100
	// Use decimal arithmetic
	tmp := loanRec.LrPrincipal.Mul(loanRec.LrRate).Mul(decimal.New(loanRec.LrYears, 0))
	tmp = tmp.Shift(-2) // divide by 100
	rounded := tmp.Round(2) // half away from zero
	WsInterest = storeDecimal(rounded, 9, 2)

	// ADD WS-INTEREST TO WS-TOTAL
	WsTotal = WsTotal.Add(WsInterest)
	WsTotal = storeDecimal(WsTotal, 11, 2)

	// ADD 1 TO WS-COUNT
	WsCount = WsCount + 1
	WsCount = storeInt(WsCount, 5)

	// MOVE fields to edited
	WsPrinEd = formatEdited("Z,ZZZ,ZZ9.99", loanRec.LrPrincipal)
	WsIntEd = formatEdited("ZZZ,ZZZ,ZZ9.99", WsInterest)

	fmt.Printf("%s %s %s\n", loanRec.LrAcct, WsPrinEd, WsIntEd)

	performReadPara()
}

func performReadPara() {
	readPara()
}

func summaryPara() {
	WsTotalEd = formatEdited("ZZ,ZZZ,ZZZ,ZZ9.99", WsTotal)
	fmt.Printf("RECORDS: %s\n", formatCount())
	fmt.Printf("TOTAL INTEREST: %s\n", WsTotalEd)
}

func mainPara() {
	// OPEN INPUT LOAN-FILE
	// Already loaded
	performReadPara()
	for !isInputDone() {
		processPara()
	}
	// CLOSE LOAN-FILE (no action)
	summaryPara()
}

func main() {
	// Load input.dat line sequential
	data, err := os.ReadFile("input.dat")
	if err != nil {
		if os.IsNotExist(err) {
			loanLines = []string{}
		} else {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	} else {
		// Use scanner to preserve spaces: split on newline manually
		// We need to handle both \n and \r\n
		// Use bufio scanner with custom split preserving empty lines?
		// Simple manual split:
		content := string(data)
		// Normalize \r\n to \n
		// Use scanner to correctly handle lines without losing trailing spaces before newline (spaces are preserved)
		// We'll use bufio.Scanner to split lines: it strips \r
		sc := bufio.NewScanner(strings.NewReader(content))
		// Increase buffer for long lines
		buf := make([]byte, 0, 64*1024)
		sc.Buffer(buf, 10*1024*1024)
		var lines []string
		for sc.Scan() {
			line := sc.Text()
			// Scanner already stripped \n and \r, keep line as is (including trailing spaces? Scanner strips only newline, not spaces)
			// However Scanner's Text returns line without line break, preserving spaces
			lines = append(lines, line)
		}
		if err := sc.Err(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		// Special case: if file was empty, lines is nil -> treat as empty
		// If file ends with newline, scanner does not add extra empty line; COBOL LINE SEQUENTIAL would not have extra record. So fine.
		loanLines = lines
		loanIdx = 0
	}
	WsEofFlag = "N"
	WsInterest = decimal.New(0, 0)
	WsTotal = decimal.New(0, 0)
	WsCount = 0
	mainPara()
}

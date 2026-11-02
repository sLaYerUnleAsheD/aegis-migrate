package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
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
var WsEofFlag string = "N"                         // PIC X len=1 = "N"
var WsInterest decimal.Decimal = decimal.New(0, 0) // PIC 9(9)V99 len=11 = 0
var WsTotal decimal.Decimal = decimal.New(0, 0)    // PIC 9(11)V99 len=13 = 0
var WsCount int64 = 0                              // PIC 9(5) len=5 = 0
var WsPrinEd string                                // PIC Z,ZZZ,ZZ9.99 len=12
var WsIntEd string                                 // PIC ZZZ,ZZZ,ZZ9.99 len=14
var WsTotalEd string                               // PIC ZZ,ZZZ,ZZZ,ZZ9.99 len=17

var loanRec LoanRec

// file handling for LOAN-FILE
var loanLines []string
var loanIdx int
var currentLine string

func isInputDone() bool {
	return WsEofFlag == "Y"
}

func storeDecimal(val decimal.Decimal, intDigits int, scale int32) decimal.Decimal {
	t := val.Truncate(scale)
	scaled := t.Shift(scale)
	mod := decimal.New(1, int32(intDigits)+scale)
	q := scaled.Div(mod).Truncate(0)
	modded := scaled.Sub(q.Mul(mod))
	result := modded.Shift(-scale)
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
		r += mod
	}
	return r
}

func parseDigitsToDecimal(s string, scale int32) decimal.Decimal {
	s = strings.TrimSpace(s)
	if s == "" {
		return decimal.New(0, 0)
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
		return decimal.New(0, 0)
	}
	neg := false
	if t[0] == '-' {
		neg = true
		t = t[1:]
	}
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
	neg := false
	if t[0] == '-' {
		neg = true
		t = t[1:]
	}
	// base 10 parse, leading zeros must be treated as decimal
	n, err := strconv.ParseInt(t, 10, 64)
	if err != nil {
		return 0
	}
	if neg {
		n = -n
	}
	return n
}

func formatEdited(pic string, val decimal.Decimal) string {
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
	absVal := val.Abs()
	sFixed := absVal.StringFixed(int32(fracDigits))
	var intStr, fracStr string
	if fracDigits > 0 {
		parts := strings.SplitN(sFixed, ".", 2)
		intStr = parts[0]
		if len(parts) > 1 {
			fracStr = parts[1]
		} else {
			fracStr = strings.Repeat("0", fracDigits)
		}
		if len(fracStr) < fracDigits {
			fracStr = fracStr + strings.Repeat("0", fracDigits-len(fracStr))
		} else if len(fracStr) > fracDigits {
			fracStr = fracStr[:fracDigits]
		}
	} else {
		intStr = sFixed
		fracStr = ""
	}
	if len(intStr) > intDigits {
		intStr = intStr[len(intStr)-intDigits:]
	}
	if len(intStr) < intDigits {
		intStr = strings.Repeat("0", intDigits-len(intStr)) + intStr
	}
	digits := []rune(intStr)
	var outInt strings.Builder
	dIdx := 0
	seenNonZero := false
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
					outInt.WriteRune(' ')
				} else {
					outInt.WriteRune(d)
				}
			} else {
				if d != '0' {
					seenNonZero = true
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
	if len(result) < len(pic) {
		result = strings.Repeat(" ", len(pic)-len(result)) + result
	}
	return result
}

func formatCount() string {
	return fmt.Sprintf("%05d", WsCount)
}

func readPara() {
	if loanIdx >= len(loanLines) {
		WsEofFlag = "Y"
		return
	}
	line := loanLines[loanIdx]
	loanIdx++
	if len(line) < 21 {
		line += strings.Repeat(" ", 21-len(line))
	} else if len(line) > 21 {
		line = line[:21]
	}
	currentLine = line
	loanRec.LrAcct = line[0:6]
	loanRec.LrPrincipal = parseDigitsToDecimal(line[6:15], 2)
	loanRec.LrRate = parseDigitsToDecimal(line[15:19], 2)
	loanRec.LrYears = parseDigitsToInt(line[19:21])
}

func processPara() {
	tmp := loanRec.LrPrincipal.Mul(loanRec.LrRate).Mul(decimal.New(loanRec.LrYears, 0))
	tmp = tmp.Shift(-2)
	rounded := tmp.Round(2)
	WsInterest = storeDecimal(rounded, 9, 2)
	WsTotal = WsTotal.Add(WsInterest)
	WsTotal = storeDecimal(WsTotal, 11, 2)
	WsCount = WsCount + 1
	WsCount = storeInt(WsCount, 5)
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
	performReadPara()
	for !isInputDone() {
		processPara()
	}
	summaryPara()
}

func main() {
	data, err := os.ReadFile("input.dat")
	if err != nil {
		if os.IsNotExist(err) {
			loanLines = []string{}
		} else {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	} else {
		content := string(data)
		sc := bufio.NewScanner(strings.NewReader(content))
		buf := make([]byte, 0, 64*1024)
		sc.Buffer(buf, 10*1024*1024)
		var lines []string
		for sc.Scan() {
			line := sc.Text()
			lines = append(lines, line)
		}
		if err := sc.Err(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		loanLines = lines
		loanIdx = 0
	}
	WsEofFlag = "N"
	WsInterest = decimal.New(0, 0)
	WsTotal = decimal.New(0, 0)
	WsCount = 0
	mainPara()
}

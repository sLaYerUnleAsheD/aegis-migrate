package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/shopspring/decimal"
)

type TaxRec struct {
	TrId     string
	TrIncome decimal.Decimal
}

var WsEofFlag string = "N"
var WsTax decimal.Decimal = decimal.NewFromInt(0)
var WsNet decimal.Decimal = decimal.NewFromInt(0)
var WsTotalTax decimal.Decimal = decimal.NewFromInt(0)
var WsCount int64 = 0
var WsIncEd string
var WsTaxEd string
var WsNetEd string
var WsTotalEd string

var taxRec TaxRec

// file handling for LINE SEQUENTIAL
var taxFileLines []string
var taxFileIdx int

func isInputDone() bool {
	return WsEofFlag == "Y"
}

func padRight(s string, n int) string {
	if len(s) >= n {
		return s[:n]
	}
	return s + strings.Repeat(" ", n-len(s))
}

func parseIncome(field string) decimal.Decimal {
	// field length 8, digits only, implied V99
	t := strings.TrimSpace(field)
	if t == "" {
		return decimal.NewFromInt(0)
	}
	var digits string
	for _, ch := range t {
		if ch >= '0' && ch <= '9' {
			digits += string(ch)
		}
	}
	if digits == "" {
		return decimal.NewFromInt(0)
	}
	d, err := decimal.NewFromString(digits)
	if err != nil {
		return decimal.NewFromInt(0)
	}
	return d.Shift(-2)
}

// generic numeric-edited formatting
func formatEdited(picture string, val decimal.Decimal) string {
	dotPos := strings.Index(picture, ".")
	var intPic, fracPic string
	if dotPos >= 0 {
		intPic = picture[:dotPos]
		fracPic = picture[dotPos+1:]
	} else {
		intPic = picture
		fracPic = ""
	}
	scale := len(fracPic)
	intDigits := 0
	for _, ch := range intPic {
		if ch == 'Z' || ch == '9' {
			intDigits++
		}
	}
	pow10 := int64(1)
	for i := 0; i < scale; i++ {
		pow10 *= 10
	}
	absVal := val.Abs()
	var scaledInt int64
	if scale > 0 {
		shifted := absVal.Shift(int32(scale))
		shifted = shifted.Truncate(0)
		scaledInt = shifted.IntPart()
	} else {
		scaledInt = absVal.Truncate(0).IntPart()
	}
	var intPartInt int64
	var fracInt int64
	if scale > 0 {
		intPartInt = scaledInt / pow10
		fracInt = scaledInt % pow10
		if fracInt < 0 {
			fracInt = -fracInt
		}
		if intPartInt < 0 {
			intPartInt = -intPartInt
		}
	} else {
		intPartInt = scaledInt
		fracInt = 0
	}
	intStr := fmt.Sprintf("%d", intPartInt)
	if len(intStr) > intDigits {
		intStr = intStr[len(intStr)-intDigits:]
	}
	if len(intStr) < intDigits {
		intStr = strings.Repeat("0", intDigits-len(intStr)) + intStr
	}
	intEdited := make([]rune, len(intPic))
	digitIdx := 0
	stillSup := true
	for i, ch := range intPic {
		if ch == ',' {
			if stillSup {
				intEdited[i] = ' '
			} else {
				intEdited[i] = ','
			}
		} else if ch == 'Z' || ch == '9' {
			d := intStr[digitIdx]
			digitIdx++
			if ch == 'Z' && stillSup {
				if d == '0' {
					intEdited[i] = ' '
				} else {
					intEdited[i] = rune(d)
					stillSup = false
				}
			} else {
				intEdited[i] = rune(d)
				stillSup = false
			}
		} else {
			intEdited[i] = ch
		}
	}
	result := string(intEdited)
	if dotPos >= 0 {
		fracStr := fmt.Sprintf("%0*d", scale, fracInt)
		result = result + "." + fracStr
	}
	if len(result) < len(picture) {
		result = strings.Repeat(" ", len(picture)-len(result)) + result
	}
	if len(result) > len(picture) {
		result = result[len(result)-len(picture):]
	}
	return result
}

func formatPIC9(n int64, digits int) string {
	s := fmt.Sprintf("%d", n)
	if len(s) > digits {
		s = s[len(s)-digits:]
	}
	if len(s) < digits {
		s = strings.Repeat("0", digits-len(s)) + s
	}
	return s
}

// paragraphs

func READPARA() {
	if taxFileIdx >= len(taxFileLines) {
		WsEofFlag = "Y"
		return
	}
	line := taxFileLines[taxFileIdx]
	taxFileIdx++
	if len(line) < 13 {
		line = line + strings.Repeat(" ", 13-len(line))
	}
	if len(line) > 13 {
		line = line[:13]
	}
	trId := line[0:5]
	trIncomeField := line[5:13]
	taxRec.TrId = trId
	taxRec.TrIncome = parseIncome(trIncomeField)
}

func PROCESSPARA() {
	limit10000 := decimal.NewFromInt(10000)
	limit40000 := decimal.NewFromInt(40000)
	rate10 := decimal.RequireFromString("0.10")
	rate20 := decimal.RequireFromString("0.20")
	rate30 := decimal.RequireFromString("0.30")
	c1000 := decimal.NewFromInt(1000)
	c7000 := decimal.NewFromInt(7000)
	c10000 := decimal.NewFromInt(10000)
	c40000 := decimal.NewFromInt(40000)

	if taxRec.TrIncome.Cmp(limit10000) <= 0 {
		v := taxRec.TrIncome.Mul(rate10)
		WsTax = v.Round(2)
	} else {
		if taxRec.TrIncome.Cmp(limit40000) <= 0 {
			v := c1000.Add(taxRec.TrIncome.Sub(c10000).Mul(rate20))
			WsTax = v.Round(2)
		} else {
			v := c7000.Add(taxRec.TrIncome.Sub(c40000).Mul(rate30))
			WsTax = v.Round(2)
		}
	}
	WsNet = taxRec.TrIncome.Sub(WsTax).Truncate(2)
	WsNet = WsNet.Truncate(2)
	WsTax = WsTax.Truncate(2)

	WsTotalTax = WsTotalTax.Add(WsTax).Truncate(2)
	WsCount = WsCount + 1

	WsIncEd = formatEdited("ZZZ,ZZ9.99", taxRec.TrIncome)
	WsTaxEd = formatEdited("ZZZ,ZZ9.99", WsTax)
	WsNetEd = formatEdited("ZZZ,ZZ9.99", WsNet)

	fmt.Printf("%s %s %s %s\n", taxRec.TrId, WsIncEd, WsTaxEd, WsNetEd)

	READPARA()
}

func MAINPARA() {
	f, err := os.Open("input.dat")
	if err != nil {
		taxFileLines = []string{}
	} else {
		sc := bufio.NewScanner(f)
		buf := make([]byte, 0, 64*1024)
		sc.Buffer(buf, 10*1024*1024)
		for sc.Scan() {
			line := sc.Text()
			taxFileLines = append(taxFileLines, line)
		}
		f.Close()
	}
	taxFileIdx = 0
	READPARA()
	for !isInputDone() {
		PROCESSPARA()
	}
	WsTotalEd = formatEdited("ZZ,ZZZ,ZZ9.99", WsTotalTax)
	countStr := formatPIC9(WsCount, 3)
	fmt.Printf("TAXPAYERS: %s TOTAL TAX: %s\n", countStr, WsTotalEd)
}

func main() {
	MAINPARA()
}

package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/shopspring/decimal"
)

type EmpRec struct {
	ErId    string
	ErDept  string
	ErHours decimal.Decimal
	ErRate  decimal.Decimal
}

var WsEofFlag string = "N"
var WsFirstFlag string = "Y"
var WsPrevDept string = "   "
var WsRegHours decimal.Decimal = decimal.New(0, 0)
var WsOtHours decimal.Decimal = decimal.New(0, 0)
var WsGross decimal.Decimal = decimal.New(0, 0)
var WsDeptTotal decimal.Decimal = decimal.New(0, 0)
var WsDeptCount int64 = 0
var WsGrandTotal decimal.Decimal = decimal.New(0, 0)
var WsGrandCount int64 = 0
var WsHoursEd string
var WsRateEd string
var WsGrossEd string
var WsDeptEd string
var WsGrandEd string

var empFile *os.File
var empScanner *bufio.Scanner
var empRec EmpRec

func parsePIC9(field string, scale int) decimal.Decimal {
	s := strings.TrimSpace(field)
	if s == "" {
		return decimal.New(0, 0)
	}
	neg := false
	if len(s) > 0 && s[0] == '-' {
		neg = true
		s = s[1:]
	} else if len(s) > 0 && s[0] == '+' {
		s = s[1:]
	}
	digits := ""
	for _, ch := range s {
		if ch >= '0' && ch <= '9' {
			digits += string(ch)
		}
	}
	if digits == "" {
		return decimal.New(0, 0)
	}
	var v int64 = 0
	for _, ch := range digits {
		v = v*10 + int64(ch-'0')
	}
	d := decimal.New(v, int32(-scale))
	if neg {
		d = d.Neg()
	}
	return d
}

func storeField(val decimal.Decimal, intDigits int, scale int) decimal.Decimal {
	t := val.Truncate(int32(scale))
	shifted := t.Shift(int32(scale))
	iv := shifted.IntPart()
	total := intDigits + scale
	pow := int64(1)
	for i := 0; i < total; i++ {
		pow *= 10
	}
	rem := iv % pow
	return decimal.New(rem, int32(-scale))
}

func formatEdited(val decimal.Decimal, picture string) string {
	dotIdx := strings.Index(picture, ".")
	var intPic, decPic string
	if dotIdx >= 0 {
		intPic = picture[:dotIdx]
		decPic = picture[dotIdx+1:]
	} else {
		intPic = picture
		decPic = ""
	}
	intPlaceCount := 0
	for _, ch := range intPic {
		if ch == 'Z' || ch == '9' {
			intPlaceCount++
		}
	}
	decPlaceCount := 0
	for _, ch := range decPic {
		if ch == 'Z' || ch == '9' {
			decPlaceCount++
		}
	}
	neg := val.Sign() < 0
	absVal := val.Abs()
	intPartDec := absVal.Truncate(int32(decPlaceCount))
	intPart := intPartDec.IntPart()
	if intPlaceCount > 0 {
		pow := int64(1)
		for i := 0; i < intPlaceCount; i++ {
			pow *= 10
		}
		intPart = intPart % pow
		if intPart < 0 {
			intPart = -intPart
		}
	}
	var fracStr string
	if decPlaceCount > 0 {
		scaled := absVal.Truncate(int32(decPlaceCount)).Shift(int32(decPlaceCount))
		scaledInt := scaled.IntPart()
		pow := int64(1)
		for i := 0; i < decPlaceCount; i++ {
			pow *= 10
		}
		frac := scaledInt % pow
		if frac < 0 {
			frac = -frac
		}
		fracStr = fmt.Sprintf("%0*d", decPlaceCount, frac)
	}
	intDigitsStr := fmt.Sprintf("%0*d", intPlaceCount, intPart)
	firstNonZero := intPlaceCount
	for i, ch := range intDigitsStr {
		if ch != '0' {
			firstNonZero = i
			break
		}
	}
	outInt := make([]rune, len(intPic))
	placeIdx := 0
	for i, ch := range intPic {
		switch ch {
		case 'Z', '9':
			digit := rune(intDigitsStr[placeIdx])
			if ch == 'Z' && placeIdx < firstNonZero {
				outInt[i] = ' '
			} else {
				outInt[i] = digit
			}
			placeIdx++
		case ',':
			leftPlaceCount := placeIdx
			if leftPlaceCount <= firstNonZero && firstNonZero != 0 {
				outInt[i] = ' '
			} else {
				outInt[i] = ','
			}
		default:
			outInt[i] = ch
		}
	}
	if decPlaceCount == 0 {
		s := string(outInt)
		if neg {
			s = "-" + s[1:]
		}
		return s
	}
	outDec := make([]rune, len(decPic))
	fIdx := 0
	for i, ch := range decPic {
		if ch == 'Z' || ch == '9' {
			outDec[i] = rune(fracStr[fIdx])
			fIdx++
		} else {
			outDec[i] = ch
		}
	}
	result := string(outInt) + "." + string(outDec)
	if neg {
		for i, c := range result {
			if c == ' ' {
				continue
			}
			if c != ',' && c != '.' {
				r := []rune(result)
				for j := i - 1; j >= 0; j-- {
					if r[j] == ' ' {
						r[j] = '-'
						break
					}
				}
				if r[0] != '-' {
					r[0] = '-'
				}
				result = string(r)
				break
			}
		}
	}
	return result
}

func moveToHoursEd(v decimal.Decimal) {
	WsHoursEd = formatEdited(v, "ZZ9.9")
}
func moveToRateEd(v decimal.Decimal) {
	WsRateEd = formatEdited(v, "ZZ9.99")
}
func moveToGrossEd(v decimal.Decimal) {
	WsGrossEd = formatEdited(v, "Z,ZZZ,ZZ9.99")
}
func moveToDeptEd(v decimal.Decimal) {
	WsDeptEd = formatEdited(v, "ZZZ,ZZZ,ZZ9.99")
}
func moveToGrandEd(v decimal.Decimal) {
	WsGrandEd = formatEdited(v, "ZZ,ZZZ,ZZZ,ZZ9.99")
}

func formatUneditedInt(v int64, width int) string {
	neg := v < 0
	if neg {
		v = -v
	}
	pow := int64(1)
	for i := 0; i < width; i++ {
		pow *= 10
	}
	v = v % pow
	s := fmt.Sprintf("%0*d", width, v)
	if neg {
		s = "-" + s[1:]
	}
	return s
}

func readPara() {
	if empScanner.Scan() {
		line := empScanner.Text()
		if len(line) < 17 {
			line = line + strings.Repeat(" ", 17-len(line))
		} else if len(line) > 17 {
			line = line[:17]
		}
		erId := line[0:5]
		erDept := line[5:8]
		erHoursStr := line[8:12]
		erRateStr := line[12:17]
		empRec.ErId = erId
		empRec.ErDept = erDept
		empRec.ErHours = parsePIC9(erHoursStr, 1)
		empRec.ErRate = parsePIC9(erRateStr, 2)
	} else {
		WsEofFlag = "Y"
	}
}

func processPara() {
	if WsFirstFlag == "Y" {
		WsPrevDept = empRec.ErDept
		WsFirstFlag = "N"
	} else {
		if empRec.ErDept != WsPrevDept {
			deptBreakPara()
			WsPrevDept = empRec.ErDept
		}
	}
	payPara()
	readPara()
}

func payPara() {
	if empRec.ErHours.GreaterThan(decimal.New(40, 0)) {
		WsRegHours = storeField(decimal.New(40, 0), 3, 1)
		WsOtHours = storeField(empRec.ErHours.Sub(decimal.New(40, 0)), 3, 1)
	} else {
		WsRegHours = storeField(empRec.ErHours, 3, 1)
		WsOtHours = storeField(decimal.New(0, 0), 3, 1)
	}
	onePointFive := decimal.New(15, -1)
	calc := WsRegHours.Mul(empRec.ErRate).Add(WsOtHours.Mul(empRec.ErRate).Mul(onePointFive))
	rounded := calc.Round(2)
	WsGross = storeField(rounded, 7, 2)

	WsDeptTotal = WsDeptTotal.Add(WsGross)
	WsDeptTotal = storeField(WsDeptTotal, 9, 2)
	WsDeptCount++
	if WsDeptCount > 999 {
		WsDeptCount = WsDeptCount % 1000
	}
	WsGrandTotal = WsGrandTotal.Add(WsGross)
	WsGrandTotal = storeField(WsGrandTotal, 11, 2)
	WsGrandCount++
	if WsGrandCount > 99999 {
		WsGrandCount = WsGrandCount % 100000
	}

	moveToHoursEd(empRec.ErHours)
	moveToRateEd(empRec.ErRate)
	moveToGrossEd(WsGross)
	fmt.Printf("%s %s %s %s %s\n", empRec.ErId, empRec.ErDept, WsHoursEd, WsRateEd, WsGrossEd)
}

func deptBreakPara() {
	moveToDeptEd(WsDeptTotal)
	cntStr := formatUneditedInt(WsDeptCount, 3)
	fmt.Printf("  DEPT %s EMPLOYEES: %s TOTAL: %s\n", WsPrevDept, cntStr, WsDeptEd)
	WsDeptTotal = storeField(decimal.New(0, 0), 9, 2)
	WsDeptCount = 0
}

func grandPara() {
	moveToGrandEd(WsGrandTotal)
	cntStr := formatUneditedInt(WsGrandCount, 5)
	fmt.Printf("GRAND TOTAL (%s): %s\n", cntStr, WsGrandEd)
}

func main() {
	var err error
	empFile, err = os.Open("input.dat")
	if err != nil {
		fmt.Fprintf(os.Stderr, "open input.dat: %v\n", err)
		os.Exit(1)
	}
	defer empFile.Close()
	empScanner = bufio.NewScanner(empFile)
	buf := make([]byte, 0, 64*1024)
	empScanner.Buffer(buf, 1024*1024)

	WsPrevDept = strings.Repeat(" ", 3)

	readPara()
	for WsEofFlag != "Y" {
		processPara()
	}
	if WsFirstFlag != "Y" {
		deptBreakPara()
	}
	grandPara()
}

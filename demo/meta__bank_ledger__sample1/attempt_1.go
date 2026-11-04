package main

import (
	"bufio"
	"fmt"
	"os"

	"github.com/shopspring/decimal"
)

type LedgerRec struct {
	BrBranch string
	BrAcct   string
	BrType   string
	BrAmt    decimal.Decimal
}

var WsEofFlag string = "N"
var WsFirstFlag string = "Y"
var WsPrevBranch string = "  "
var WsPrevAcct string = "    "
var WsBal decimal.Decimal = decimal.Zero
var WsBranchTot decimal.Decimal = decimal.Zero
var WsGrandTot decimal.Decimal = decimal.Zero
var WsSkipped int64 = 0
var WsAmtEd string
var WsBalEd string
var WsTotEd string

var curRec LedgerRec
var inputLines []string
var inputIdx int
var inputExhausted bool

func isInputDone() bool { return WsEofFlag == "Y" }
func isFirstRecord() bool { return WsFirstFlag == "Y" }

func padRight(s string, n int) string {
	if len(s) >= n {
		return s[:n]
	}
	for len(s) < n {
		s += " "
	}
	return s
}

func parseAmt(s string) decimal.Decimal {
	var n int64 = 0
	for i := 0; i < len(s); i++ {
		c := s[i]
		var d int64
		if c >= '0' && c <= '9' {
			d = int64(c - '0')
		} else if c == ' ' {
			d = 0
		} else if c == 0 {
			d = 0
		} else {
			d = 0
		}
		n = n*10 + d
	}
	return decimal.New(n, -2)
}

func storeBal(v decimal.Decimal) decimal.Decimal {
	t := v.Truncate(2)
	if t.IsZero() {
		return decimal.Zero
	}
	signNeg := t.Sign() < 0
	abs := t.Abs()
	ip := abs.Truncate(0)
	frac := abs.Sub(ip)
	base := decimal.New(1, 7)
	ipMod := ip.Mod(base)
	res := ipMod.Add(frac)
	if signNeg {
		res = res.Neg()
	}
	return res
}

func storeTot(v decimal.Decimal) decimal.Decimal {
	t := v.Truncate(2)
	if t.IsZero() {
		return decimal.Zero
	}
	signNeg := t.Sign() < 0
	abs := t.Abs()
	ip := abs.Truncate(0)
	frac := abs.Sub(ip)
	base := decimal.New(1, 9)
	ipMod := ip.Mod(base)
	res := ipMod.Add(frac)
	if signNeg {
		res = res.Neg()
	}
	return res
}

func intDigitsN(abs decimal.Decimal, n int) []int {
	ip := abs.Truncate(0)
	base := decimal.New(1, int32(n))
	m := ip.Mod(base)
	v := m.IntPart()
	d := make([]int, n)
	for i := n - 1; i >= 0; i-- {
		d[i] = int(v % 10)
		v /= 10
	}
	return d
}

func fracDigits(abs decimal.Decimal) (int, int) {
	t := abs.Truncate(2)
	total := t.Shift(2).Truncate(0)
	m := total.Mod(decimal.NewFromInt(100))
	v := m.IntPart()
	if v < 0 {
		v = -v
	}
	return int((v / 10) % 10), int(v % 10)
}

func formatWithPic(abs decimal.Decimal, pic string, n int) string {
	digits := intDigitsN(abs, n)
	f1, f2 := fracDigits(abs)
	type ph struct {
		kind byte
		dig  int
	}
	var placeholders []ph
	di := 0
	for i := 0; i < len(pic); i++ {
		c := pic[i]
		if c == 'Z' || c == '9' {
			placeholders = append(placeholders, ph{kind: c, dig: di})
			di++
		} else if c == ',' || c == '.' {
			placeholders = append(placeholders, ph{kind: c, dig: -1})
		}
	}
	firstNZ := -1
	for i, d := range digits {
		if d != 0 {
			firstNZ = i
			break
		}
	}
	out := make([]byte, 0, len(pic)+3)
	suppressed := true
	digPos := 0
	for _, p := range placeholders {
		switch p.kind {
		case 'Z':
			d := digits[digPos]
			digPos++
			if d != 0 {
				suppressed = false
				out = append(out, byte('0'+d))
			} else {
				if suppressed {
					out = append(out, ' ')
				} else {
					out = append(out, '0')
				}
			}
		case '9':
			d := digits[digPos]
			digPos++
			out = append(out, byte('0'+d))
			_ = firstNZ
		case ',':
			if suppressed {
				out = append(out, ' ')
			} else {
				out = append(out, ',')
			}
		case '.':
			out = append(out, '.')
		}
	}
	out = append(out, '.', byte('0'+f1), byte('0'+f2))
	return string(out)
}

func formatAmtEd(v decimal.Decimal) string {
	abs := v.Abs().Truncate(2)
	return formatWithPic(abs, "ZZ,ZZ9", 5)
}

func formatBalEd(v decimal.Decimal) string {
	t := v.Truncate(2)
	neg := t.Sign() < 0
	abs := t.Abs()
	rest := formatWithPic(abs, "Z,ZZZ,ZZ9", 7)
	sign := " "
	if neg {
		sign = "-"
	}
	return sign + rest
}

func formatTotEd(v decimal.Decimal) string {
	t := v.Truncate(2)
	neg := t.Sign() < 0
	abs := t.Abs()
	rest := formatWithPic(abs, "ZZZ,ZZZ,ZZ9", 9)
	sign := " "
	if neg {
		sign = "-"
	}
	return sign + rest
}

func displayLine(s string) {
	fmt.Fprintln(os.Stdout, s)
}

func ReadPara() {
	if inputIdx >= len(inputLines) {
		WsEofFlag = "Y"
		return
	}
	line := inputLines[inputIdx]
	inputIdx++
	if len(line) < 14 {
		for len(line) < 14 {
			line += " "
		}
	} else if len(line) > 14 {
		line = line[:14]
	}
	curRec.BrBranch = line[0:2]
	curRec.BrAcct = line[2:6]
	curRec.BrType = line[6:7]
	curRec.BrAmt = parseAmt(line[7:14])
}

func ProcessPara() {
	if isFirstRecord() {
		WsPrevBranch = curRec.BrBranch
		WsPrevAcct = curRec.BrAcct
		WsFirstFlag = "N"
	} else {
		if curRec.BrBranch != WsPrevBranch {
			AcctBreakPara()
			BranchBreakPara()
			WsPrevBranch = curRec.BrBranch
			WsPrevAcct = curRec.BrAcct
		} else {
			if curRec.BrAcct != WsPrevAcct {
				AcctBreakPara()
				WsPrevAcct = curRec.BrAcct
			}
		}
	}
	PostPara()
	ReadPara()
}

func PostPara() {
	WsAmtEd = formatAmtEd(curRec.BrAmt)
	switch curRec.BrType {
	case "D":
		WsBal = storeBal(WsBal.Add(curRec.BrAmt))
		displayLine(curRec.BrAcct + " D " + WsAmtEd)
	case "C":
		WsBal = storeBal(WsBal.Sub(curRec.BrAmt))
		displayLine(curRec.BrAcct + " C " + WsAmtEd)
	default:
		WsSkipped = (WsSkipped + 1) % 100
		displayLine(curRec.BrAcct + " ? SKIPPED")
	}
}

func AcctBreakPara() {
	WsBalEd = formatBalEd(WsBal)
	displayLine("  ACCOUNT " + WsPrevAcct + " BALANCE:" + WsBalEd)
	WsBranchTot = storeTot(WsBranchTot.Add(WsBal))
	WsBal = decimal.Zero
}

func BranchBreakPara() {
	WsTotEd = formatTotEd(WsBranchTot)
	displayLine(" BRANCH " + WsPrevBranch + " TOTAL:" + WsTotEd)
	WsGrandTot = storeTot(WsGrandTot.Add(WsBranchTot))
	WsBranchTot = decimal.Zero
}

func GrandPara() {
	WsTotEd = formatTotEd(WsGrandTot)
	displayLine("GRAND TOTAL:" + WsTotEd)
	displayLine("SKIPPED: " + fmt.Sprintf("%02d", WsSkipped))
}

func MainPara() {
	ReadPara()
	for !isInputDone() {
		ProcessPara()
	}
	if !isFirstRecord() {
		AcctBreakPara()
		BranchBreakPara()
	}
	GrandPara()
}

func main() {
	WsBal = decimal.Zero
	WsBranchTot = decimal.Zero
	WsGrandTot = decimal.Zero
	f, err := os.Open("input.dat")
	if err != nil {
		inputLines = []string{}
		MainPara()
		return
	}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1024*1024), 1024*1024)
	for sc.Scan() {
		line := sc.Text()
		if len(line) > 0 && line[len(line)-1] == '\r' {
			line = line[:len(line)-1]
		}
		inputLines = append(inputLines, line)
	}
	f.Close()
	if err := sc.Err(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	MainPara()
}

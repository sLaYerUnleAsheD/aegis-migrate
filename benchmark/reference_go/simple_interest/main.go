// Hand-written reference translation of simple_interest.cbl.
// Used ONLY to test the verifier end to end (not an LLM output).
// Integer cents arithmetic: no floats, no external dependencies.
package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// editMoney mimics a COBOL numeric-edited field such as Z,ZZZ,ZZ9.99:
// zero-suppressed integer part with commas, two decimals, right-aligned.
func editMoney(cents int64, width int) string {
	whole, frac := cents/100, cents%100
	s := strconv.FormatInt(whole, 10)
	var b strings.Builder
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(c)
	}
	out := fmt.Sprintf("%s.%02d", b.String(), frac)
	if len(out) > width { // COBOL silently drops high-order digits
		out = out[len(out)-width:]
	}
	return strings.Repeat(" ", width-len(out)) + out
}

func atoi(s string) int64 {
	n, _ := strconv.ParseInt(s, 10, 64)
	return n
}

func main() {
	f, err := os.Open("input.dat")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer f.Close()

	var total int64
	var count int64
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := sc.Text()
		for len(line) < 21 {
			line += " "
		}
		acct := line[0:6]
		principal := atoi(line[6:15]) // cents (implied 2 decimals)
		rate := atoi(line[15:19])     // hundredths of a percent
		years := atoi(line[19:21])

		// interest(cents) = principal * rate * years / 10000, rounded half up
		interest := (principal*rate*years + 5000) / 10000

		total += interest
		count++
		fmt.Printf("%s %s %s\n", acct, editMoney(principal, 12), editMoney(interest, 14))
	}
	fmt.Printf("RECORDS: %05d\n", count)
	fmt.Printf("TOTAL INTEREST: %s\n", editMoney(total, 17))
}
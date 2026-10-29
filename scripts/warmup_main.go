// Used only at image-build time to pre-compile the packages generated programs
// are likely to import, so sandboxed builds hit a warm Go build cache.
package main

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"math"
	"math/big"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/shopspring/decimal"
)

func main() {
	_ = bufio.NewReader(os.Stdin)
	_ = bytes.NewBuffer(nil)
	_ = errors.New("x")
	_ = io.EOF
	_ = math.Pi
	_ = big.NewInt(1)
	_ = regexp.MustCompile("x")
	sort.Ints(nil)
	_ = strconv.Itoa(1)
	_ = strings.ToUpper("x")
	_ = time.Now()
	_ = unicode.IsDigit('1')
	fmt.Println(decimal.NewFromInt(1))
}
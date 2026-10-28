"""Prompt construction for COBOL -> Go translation and repair.

Design notes
  * RULES is static and sent first (as the system/instructions text) so the
    provider's prompt cache can serve it at the cheaper cached-input rate.
  * For tier 1-2 programs the whole program is sent in one call. At this size
    that costs a fraction of a cent, and it avoids stitching per-paragraph
    translations together. Paragraph-level repair can come later for big programs.
  * Facts that the analyzer already knows (field types, offsets, widths) are
    handed to the model instead of making it re-derive them.
"""
from __future__ import annotations

import re

from cobol_adapter.analyzer import Analysis, record_layout


class TranslationError(Exception):
    pass


RULES = """You translate COBOL batch programs into Go. The result is checked by running both \
programs on the same input files and comparing every output byte, so exact behaviour matters \
more than style.

OUTPUT FORMAT
- Reply with ONE complete Go source file inside a single ```go fenced block. No other code blocks.
- `package main`. Imports: Go standard library and github.com/shopspring/decimal only.

I/O
- The program reads its input from the file "input.dat" in the current directory. It is a COBOL \
LINE SEQUENTIAL file: one record per line. If a line is shorter than the record length, pad it \
with spaces on the right. Any other COBOL file that is WRITTEN goes to the file named in its \
SELECT ... ASSIGN clause, in the current directory.
- DISPLAY writes its operands concatenated, followed by a newline, to stdout. Print nothing else \
(no logging, no debug output). Errors go to stderr with a non-zero exit code.
- Reproduce stdout exactly, including every space.

NUMBERS
- Never use float32/float64. Use decimal.Decimal for every numeric field that has decimals and \
for arithmetic intermediates; use int64 for integer fields.
- DISPLAY numeric fields in files store digits only, with an IMPLIED decimal point (no '.' in the \
data). PIC 9(7)V99 holding "000100000" means 1000.00: parse the digits as an integer, then build \
the value with decimal.New(n, -2).
- COMPUTE ... ROUNDED rounds half away from zero to the scale of the target field: use Round(scale). \
Without ROUNDED the result is TRUNCATED toward zero to the target scale: use Truncate(scale).
- Storing a value into a numeric field keeps only the low-order digits that fit (high-order \
digits are silently dropped) unless ON SIZE ERROR is given.
- Avoid Div (it stops at 16 digits). To divide by 100 use Shift(-2). Multiply before dividing.
- ADD x TO y means y = y + x. MOVE of a number to a numeric-edited field formats it (below).

FORMATTING
- Numeric-edited fields (pictures with Z , . 9) print right-aligned in exactly the width of the \
picture. Z replaces a leading zero with a space (commas inside the suppressed zone also become \
spaces); 9 always prints a digit; '.' is a literal decimal point. If the value has more integer \
digits than the picture, the HIGH-ORDER digits are dropped.
- An unedited numeric DISPLAY item such as PIC 9(5) prints zero-padded to its digit count.
- PIC X(n) fields are exactly n characters, padded with spaces on the right.

STRUCTURE
- One Go function per COBOL paragraph, called where the COBOL PERFORMs it. PERFORM ... UNTIL \
tests the condition BEFORE each iteration. Keep working-storage as package-level variables.
"""


def _layout_table(a: Analysis) -> str:
    try:
        lay = record_layout(a)
    except ValueError:
        return "(no file record)"
    rows = ["name | offset | width | pic"]
    rows += [f"{f['name']} | {f['offset']} | {f['size']} | {f['pic']}" for f in lay]
    total = max(f["offset"] + f["size"] for f in lay)
    return "\n".join(rows) + f"\nrecord length: {total} bytes"


def build_prompt(cobol_source: str, a: Analysis) -> str:
    files = ", ".join(f"{k} -> {v}" for k, v in a.files.items()) or "(none)"
    return (
        "## COBOL program\n```cobol\n" + cobol_source.rstrip() + "\n```\n\n"
        f"## Files (SELECT name -> external file name)\n{files}\n\n"
        "## Input record layout (bytes, 0-based offsets)\n" + _layout_table(a) + "\n\n"
        "## Go declarations derived from the DATA DIVISION (use these names and types)\n"
        "```go\n" + a.go_types.rstrip() + "\n```\n\n"
        "## Task\nTranslate the whole program to Go following the rules."
    )


def build_repair_prompt(cobol_source: str, a: Analysis, go_source: str, failure: str) -> str:
    return (
        build_prompt(cobol_source, a)
        + "\n\n## Your previous Go translation\n```go\n" + go_source.rstrip() + "\n```\n\n"
        "## It failed verification against the real COBOL program's output\n"
        "In diffs, '\u00b7' marks a space. Lines starting with '-' are what COBOL printed "
        "(expected); lines starting with '+' are what your Go printed.\n"
        "```\n" + failure.strip() + "\n```\n\n"
        "## Task\nFix the cause of the difference. Reply with the complete corrected Go file."
    )


_FENCE = re.compile(r"```(?:go|golang)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_go(reply: str) -> str:
    m = _FENCE.search(reply)
    if m:
        return m.group(1).strip() + "\n"
    i = reply.find("package main")
    if i != -1 and "```" not in reply:
        return reply[i:].strip() + "\n"
    raise TranslationError("no Go code block found in the model reply")
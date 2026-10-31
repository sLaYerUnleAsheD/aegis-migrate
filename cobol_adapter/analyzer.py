"""Analyzer: turn COBOL source into a deterministic IR (no LLM).

What it extracts:
  * data items (level, name, PIC, USAGE, OCCURS, REDEFINES, VALUE) with sizes
  * the record layout of each FD (offsets and widths, used by inputgen)
  * PROCEDURE DIVISION paragraphs and the PERFORM call graph
  * risk features (COMP-3, REDEFINES, ROUNDED, SIZE ERROR ...) for the
    failure taxonomy, and unsupported constructs (EXEC SQL/CICS, SORT ...)

Supported input: fixed-format source (columns 8-72), the subset described in
the README. Anything outside it is flagged, never silently guessed.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

UNSUPPORTED_VERBS = {"SORT", "MERGE", "CALL", "ALTER", "ENTRY", "INVOKE", "GENERATE", "INITIATE"}
NOT_PARAGRAPHS = {"EXIT", "GOBACK", "CONTINUE", "STOP", "END-IF", "END-READ", "END-PERFORM"}
PERFORM_STOPWORDS = {"UNTIL", "VARYING", "WITH", "TEST", "FOREVER", "THRU", "THROUGH"}
EDIT_CHARS = set("Z*B0/,.+-$")


# ---------------------------------------------------------------- source ---
def normalize_source(text: str) -> str:
    """Fixed format: drop sequence area (1-6), comment lines, and cols > 72."""
    out = []
    for line in text.splitlines():
        line = line.expandtabs(8)
        if len(line) < 7:
            continue
        if line[6] in "*/":          # comment (or page eject)
            continue
        out.append(line[7:72])
    return "\n".join(out)


_LIT = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")


def upper_outside_literals(text: str) -> str:
    """Uppercase code but leave string literals exactly as written."""
    out, last = [], 0
    for m in _LIT.finditer(text):
        out.append(text[last:m.start()].upper())
        out.append(m.group(0))
        last = m.end()
    out.append(text[last:].upper())
    return "".join(out)


def strip_literals(text: str) -> str:
    """Replace literals with "" so keyword scans cannot match inside them."""
    return _LIT.sub('""', text)


def split_sentences(text: str) -> list[str]:
    """A sentence ends at a period followed by whitespace or end of text.
    PIC strings (Z,ZZZ,ZZ9.99) and string literals ("A. B") contain periods
    and spaces that must survive, so literals are masked while splitting."""
    masked = _LIT.sub(lambda m: m.group(0).replace(".", "\x00").replace(" ", "\x01"), text)
    parts = re.split(r"\.(?=\s|$)", masked)
    out = []
    for part in parts:
        if part.strip():
            clean = re.sub(r"\s+", " ", part).strip()
            out.append(clean.replace("\x00", ".").replace("\x01", " "))
    return out


# ------------------------------------------------------------------- PIC ---
@dataclass
class Pic:
    raw: str
    category: str          # numeric | alphanumeric | edited
    size: int              # bytes in DISPLAY form (before USAGE adjustments)
    digits: int = 0        # total digit positions (numeric)
    scale: int = 0         # digits after implied decimal point
    signed: bool = False


def expand_pic(raw: str) -> str:
    """9(7)V99 -> 999999999V99 style expansion (keeps other symbols)."""
    s = raw.upper()
    return re.sub(r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), s)


def parse_pic(raw: str) -> Pic:
    e = expand_pic(raw)
    signed = e.startswith("S")
    body = e[1:] if signed else e
    if any(c in EDIT_CHARS for c in body) and not set(body) <= set("9VP"):
        # Edited: every character of the picture is one output byte (V takes none).
        return Pic(raw, "edited", len(body.replace("V", "")))
    if set(body) <= set("9VP"):
        if "V" in body:
            ip, fp = body.split("V", 1)
        else:
            ip, fp = body, ""
        digits = ip.count("9") + fp.count("9")
        return Pic(raw, "numeric", digits, digits, fp.count("9"), signed)
    return Pic(raw, "alphanumeric", len(body))


# ------------------------------------------------------------ data items ---
@dataclass
class DataItem:
    level: int
    name: str
    pic: Pic | None = None
    usage: str = "DISPLAY"
    occurs: int | None = None
    redefines: str | None = None
    value: str | None = None
    section: str = ""             # FILE | WORKING-STORAGE
    fd: str | None = None         # owning FD name for file records
    size: int = 0                 # bytes of one occurrence (groups: sum of children)
    offset: int = 0               # offset inside its 01 record
    children: list["DataItem"] = field(default_factory=list)

    @property
    def is_group(self) -> bool:
        return self.pic is None and self.level not in (88, 66, 77)


def storage_size(pic: Pic, usage: str) -> int:
    u = usage.upper()
    if pic.category == "numeric":
        if u in ("COMP-3", "PACKED-DECIMAL"):
            return pic.digits // 2 + 1
        if u in ("COMP", "COMP-4", "COMP-5", "BINARY"):
            return 2 if pic.digits <= 4 else 4 if pic.digits <= 9 else 8
        return pic.size + (0)          # DISPLAY: one byte per digit
    return pic.size


def parse_item(sentence: str, section: str, fd: str | None) -> DataItem | None:
    tok = sentence.split(" ")
    if not tok or not tok[0].isdigit():
        return None
    level = int(tok[0])
    name = tok[1] if len(tok) > 1 and tok[1] not in ("PIC", "PICTURE", "OCCURS", "REDEFINES") else "FILLER"
    item = DataItem(level=level, name=name, section=section, fd=fd)
    if level == 88:
        item.value = sentence
        return item
    m = re.search(r"\bPIC(?:TURE)?(?: IS)? (\S+)", sentence)
    if m:
        item.pic = parse_pic(m.group(1))
    m = re.search(r"\b(COMP-3|COMP-4|COMP-5|COMP|BINARY|PACKED-DECIMAL)\b", sentence)
    if m:
        item.usage = m.group(1)
    m = re.search(r"\bOCCURS (\d+)", sentence)
    if m:
        item.occurs = int(m.group(1))
    m = re.search(r"\bREDEFINES (\S+)", sentence)
    if m:
        item.redefines = m.group(1)
    m = re.search(r"\bVALUE(?: IS)? (\"[^\"]*\"|'[^']*'|\S+)", sentence)
    if m:
        item.value = m.group(1)
    return item


def build_tree(items: list[DataItem]) -> list[DataItem]:
    """Nest items by level number; compute sizes and offsets per 01 record."""
    roots: list[DataItem] = []
    stack: list[DataItem] = []
    for it in items:
        if it.level in (88, 66):
            if stack:
                stack[-1].children.append(it)
            continue
        while stack and stack[-1].level >= it.level:
            stack.pop()
        if stack:
            stack[-1].children.append(it)
        else:
            roots.append(it)
        stack.append(it)

    def size_of(it: DataItem) -> int:
        if it.is_group:
            kids = [c for c in it.children if c.level not in (88, 66)]
            # REDEFINES shares storage with the item it redefines: not additive.
            total = sum(size_of(c) for c in kids if c.redefines is None)
            it.size = total
        else:
            it.size = storage_size(it.pic, it.usage) if it.pic else 0
        return it.size * (it.occurs or 1)

    def assign_offsets(it: DataItem, base: int) -> None:
        it.offset = base
        cur = base
        prev_start: dict[str, int] = {}
        for c in it.children:
            if c.level in (88, 66):
                continue
            if c.redefines and c.redefines in prev_start:
                assign_offsets(c, prev_start[c.redefines])
                continue
            prev_start[c.name] = cur
            assign_offsets(c, cur)
            cur += c.size * (c.occurs or 1)

    for r in roots:
        size_of(r)
        assign_offsets(r, 0)
    return roots


# ------------------------------------------------------------- procedure ---
@dataclass
class Paragraph:
    name: str
    body: str
    performs: list[str] = field(default_factory=list)


def parse_procedure(sentences: list[str]) -> list[Paragraph]:
    paras: list[Paragraph] = []
    cur: Paragraph | None = None
    for s in sentences:
        if re.fullmatch(r"[A-Z0-9][A-Z0-9-]*", s) and s not in NOT_PARAGRAPHS:
            cur = Paragraph(s, "")
            paras.append(cur)
        else:
            if cur is None:               # statements before any paragraph name
                cur = Paragraph("(main)", "")
                paras.append(cur)
            cur.body += (" " if cur.body else "") + s
    names = {p.name for p in paras}
    for p in paras:
        for m in re.finditer(r"\bPERFORM ([A-Z0-9][A-Z0-9-]*)", p.body):
            t = m.group(1)
            if t in names and t not in PERFORM_STOPWORDS and t not in p.performs:
                p.performs.append(t)
    return paras


# -------------------------------------------------------------- analysis ---
@dataclass
class Analysis:
    program_id: str
    files: dict[str, str]                  # SELECT name -> external file name
    records: list[DataItem]                # 01-level records (file + working)
    paragraphs: list[Paragraph]
    risk_features: list[str]
    unsupported: list[str]
    go_types: str = ""
    warnings: list[str] = field(default_factory=list)   # in-scope but possibly mis-parsed

    def to_json(self) -> dict:
        return asdict(self)


def find_risks(src_upper: str, items: list[DataItem]) -> list[str]:
    risks = set()
    if re.search(r"\bCOMP-3\b|\bPACKED-DECIMAL\b", src_upper):
        risks.add("COMP-3")
    if re.search(r"\bCOMP(-[45])?\b|\bBINARY\b", src_upper):
        risks.add("COMP/BINARY")
    if "REDEFINES" in src_upper:
        risks.add("REDEFINES")
    if re.search(r"\bOCCURS\b", src_upper):
        risks.add("OCCURS")
    if re.search(r"\bROUNDED\b", src_upper):
        risks.add("ROUNDED")
    if "SIZE ERROR" in src_upper:
        risks.add("SIZE-ERROR")
    if re.search(r"\bSTRING\b|\bUNSTRING\b", src_upper):
        risks.add("STRING/UNSTRING")
    if re.search(r"\bEVALUATE\b", src_upper):
        risks.add("EVALUATE")

    def walk(it: DataItem):
        if it.pic and it.pic.category == "numeric" and it.pic.signed:
            risks.add("SIGNED")
        if it.pic and it.pic.category == "edited":
            risks.add("EDITED-OUTPUT")
        for c in it.children:
            walk(c)
    for it in items:
        walk(it)
    return sorted(risks)


def scope_warnings(raw: str, code: str, proc_sents: list[str], fds: set) -> list[str]:
    """Things the analyzer does NOT handle. Loud warnings beat silent wrong layouts."""
    w: list[str] = []
    free = cont = False
    long_lines: list[int] = []
    for n, line in enumerate(raw.splitlines(), 1):
        line = line.expandtabs(8)
        if len(line) < 7 or not line.strip() or line[6] in "*/":
            continue
        if len(line.rstrip()) > 72:
            long_lines.append(n)
        seq = line[:6].strip()
        if seq and not seq.isdigit():
            free = True
        if line[6] == "-":
            cont = True
    if long_lines:
        w.append(f"code runs past column 72 and the excess is IGNORED by cobc: lines "
                 f"{', '.join(map(str, long_lines[:5]))}")
    if free:
        w.append("looks like FREE-format source; analyzer needs fixed format (cols 8-72)")
    if cont:
        w.append("continuation lines (col 7 '-') are not joined")
    if re.search(r"\bCOPY\s+[A-Z0-9-]+", code):
        w.append("COPY statements are not expanded; copybook fields will be missing")
    if any(re.fullmatch(r"[A-Z0-9-]+ SECTION", s) for s in proc_sents):
        w.append("PROCEDURE DIVISION SECTIONs are treated as plain statements")
    if re.search(r"\bGO TO\b", code):
        w.append("GO TO control flow is not modelled in the PERFORM graph")
    if re.search(r"\bDEPENDING ON\b", code):
        w.append("OCCURS DEPENDING ON: table size treated as the maximum")
    if len(fds) > 1:
        w.append(f"{len(fds)} FDs found; record_layout() uses the first unless fd_name is given")
    return w


def analyze(source: str) -> Analysis:
    text = normalize_source(source)
    up = upper_outside_literals(text)
    code = strip_literals(up)
    sents = split_sentences(up)

    program_id, files = "UNKNOWN", {}
    section, fd = "", None
    items: list[DataItem] = []
    proc_sents: list[str] = []
    in_proc = False
    unsupported: list[str] = []

    # PROGRAM-ID's period is followed by the name, so sentence splitting
    # would separate them; read it with a regex on the whole text instead.
    m = re.search(r"PROGRAM-ID\.?\s+([A-Z0-9-]+)", up)
    if m:
        program_id = m.group(1)
    # SELECT ... ASSIGN may span sentence text; handle with regex on whole text.
    for m in re.finditer(r"SELECT (\S+) ASSIGN TO \"?([^\" ]+)\"?", up):
        files[m.group(1)] = m.group(2)      # keep case: Linux file names are case-sensitive

    for s in sents:
        if in_proc:
            proc_sents.append(s)
            continue
        if s.startswith("PROCEDURE DIVISION"):
            in_proc = True
        elif s.startswith("FILE SECTION"):
            section = "FILE"
        elif s.startswith("WORKING-STORAGE SECTION"):
            section = "WORKING-STORAGE"
        elif s.startswith("FD "):
            fd = s.split()[1]
        elif section and s[:1].isdigit():
            it = parse_item(s, section, fd if section == "FILE" else None)
            if it:
                items.append(it)

    records = build_tree(items)
    paragraphs = parse_procedure(proc_sents)

    for m in re.finditer(r"\bEXEC (SQL|CICS)\b", code):
        unsupported.append(f"EXEC {m.group(1)}")
    body_up = strip_literals(" ".join(p.body for p in paragraphs))
    for v in UNSUPPORTED_VERBS:
        if re.search(rf"\b{v}\b", body_up):
            unsupported.append(v)

    a = Analysis(program_id, files, records, paragraphs, find_risks(code, records),
                 sorted(set(unsupported)))
    a.warnings = scope_warnings(source, code, proc_sents, {i.fd for i in items if i.fd})
    a.go_types = emit_go_structs(a)
    return a


# ----------------------------------------------------------- Go structs ----
def go_field_name(cobol_name: str) -> str:
    return "".join(p.capitalize() for p in cobol_name.lower().split("-"))


def go_type(it: DataItem) -> str:
    p = it.pic
    if p is None:
        return "struct"
    if p.category == "numeric":
        t = "decimal.Decimal" if p.scale > 0 else "int64"
    else:
        t = "string"
    return f"[{it.occurs}]{t}" if it.occurs else t


def emit_go_structs(a: Analysis) -> str:
    """Go struct definitions for every 01 record. Numeric fields with a scale
    use decimal.Decimal; NEVER float64 (that is the classic migration bug)."""
    lines: list[str] = []

    def emit(it: DataItem, indent: str) -> None:
        for c in it.children:
            if c.level in (88, 66):
                continue
            fname = go_field_name(c.name)
            note = f"PIC {c.pic.raw}" if c.pic else "group"
            if c.usage != "DISPLAY":
                note += f" {c.usage}"
            if c.redefines:
                note += f" REDEFINES {c.redefines} (NEEDS SPECIAL HANDLING)"
            note += f" @{c.offset} len={c.size}"
            if c.is_group:
                lines.append(f"{indent}{fname} struct {{  // {note}")
                emit(c, indent + "\t")
                lines.append(f"{indent}}}")
            else:
                lines.append(f"{indent}{fname} {go_type(c)} // {note}")

    scalars: list[str] = []
    for r in a.records:
        if not r.is_group:   # standalone 01/77 item: a plain variable, not a struct
            note = f"PIC {r.pic.raw}" + (f" {r.usage}" if r.usage != "DISPLAY" else "")
            init = f" = {r.value}" if r.value else ""
            scalars.append(f"var {go_field_name(r.name)} {go_type(r)} // {note} len={r.size}{init}")
            continue
        lines.append(f"type {go_field_name(r.name)} struct {{ // 01 {r.name}, {r.size} bytes")
        emit(r, "\t")
        lines.append("}\n")
    if scalars:
        lines.append("// Standalone working-storage items (VALUE shown after '=')")
        lines.extend(scalars)
    return "\n".join(lines)


# ------------------------------------------------------------ layouts ------
def record_layout(a: Analysis, fd_name: str | None = None) -> list[dict]:
    """Flat list of elementary fields of the (first) FILE record, with absolute
    offsets and widths. This is what inputgen consumes."""
    for r in a.records:
        if r.section == "FILE" and (fd_name is None or r.fd == fd_name):
            out: list[dict] = []

            def walk(it: DataItem):
                for c in it.children:
                    if c.level in (88, 66):
                        continue
                    if c.is_group:
                        walk(c)
                    else:
                        out.append({"name": c.name, "offset": c.offset, "size": c.size,
                                    "category": c.pic.category, "digits": c.pic.digits,
                                    "scale": c.pic.scale, "signed": c.pic.signed,
                                    "usage": c.usage, "occurs": c.occurs, "pic": c.pic.raw})
            walk(r)
            return out
    raise ValueError("no FILE record found")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m cobol_adapter.analyzer prog.cbl [--go]")
        return 2
    a = analyze(Path(argv[1]).read_text())
    for w in a.warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    for u in a.unsupported:
        print(f"UNSUPPORTED: {u}", file=sys.stderr)
    if "--go" in argv:
        print(a.go_types)
    else:
        print(json.dumps(a.to_json(), indent=2, default=str))
    return 1 if a.unsupported else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
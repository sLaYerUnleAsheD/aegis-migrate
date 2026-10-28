"""Input generator: build fixed-width test inputs from the record layout.

Why generate instead of hand-writing: boundaries come systematically from the
PIC definitions (zero, smallest unit, rounding-sensitive digits, max, max-1),
so the verifier does not depend on whatever the model or I thought of.

v1 limits (flagged, never guessed): unsigned DISPLAY numerics and plain
alphanumerics only. Signed (overpunch), COMP and COMP-3 fields raise
UnsupportedLayout; they arrive with the tier-3 work.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


class UnsupportedLayout(Exception):
    pass


@dataclass
class Case:
    name: str
    data: bytes          # contents of input.dat
    records: int


# ---------------------------------------------------------------- values ---
def numeric_candidates(digits: int) -> list[int]:
    """Unscaled integer values worth testing for an unsigned field."""
    mx = 10**digits - 1
    cands = {0, 1, mx, max(mx - 1, 0)}
    cands.add(5)                                   # lowest digit 5: rounding half cases
    cands.add(10 ** (digits - 1) if digits > 1 else 1)   # leading 1, rest zeros
    cands.add(5 * 10 ** (digits - 1))              # leading 5, rest zeros
    cands.add(int("5" * digits))                   # 55...5
    cands.add(int("15" + "0" * max(digits - 2, 0)) if digits >= 2 else 1)
    return sorted(c for c in cands if 0 <= c <= mx)


def alnum_candidates(size: int) -> list[str]:
    base = ["A" * size, "Z" * size, ("AB12CD34EF56" * 4)[:size], "X" + " " * (size - 1)]
    if size >= 3:
        base.append(("A1" * size)[:size])
    seen, out = set(), []
    for b in base:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def typical_numeric(digits: int) -> int:
    return 10 ** (digits // 2) if digits >= 2 else 5


def typical_alnum(size: int, i: int = 1) -> str:
    return (f"ACC{i:03d}" + "ABCDEFGHIJKLMNOP" * 8)[:size]


# --------------------------------------------------------------- layout ----
def expand_fields(layout: list[dict]) -> list[dict]:
    """Validate fields and expand OCCURS into separate positional fields."""
    out = []
    for f in layout:
        if f["category"] == "numeric":
            if f["signed"]:
                raise UnsupportedLayout(f"{f['name']}: signed numeric not supported yet")
            if f["usage"] != "DISPLAY":
                raise UnsupportedLayout(f"{f['name']}: USAGE {f['usage']} not supported yet")
        elif f["category"] == "edited":
            raise UnsupportedLayout(f"{f['name']}: edited field in an input record")
        n = f["occurs"] or 1
        for i in range(n):
            g = dict(f)
            g["offset"] = f["offset"] + i * f["size"]
            g["name"] = f["name"] if n == 1 else f"{f['name']}({i + 1})"
            out.append(g)
    return out


def record_length(fields: list[dict]) -> int:
    return max(f["offset"] + f["size"] for f in fields)


def format_record(fields: list[dict], values: dict[str, object]) -> bytes:
    """Place values into a space-filled record; numerics are zero-padded."""
    buf = bytearray(b" " * record_length(fields))
    for f in fields:
        v = values.get(f["name"])
        if v is None:
            continue
        if f["category"] == "numeric":
            text = str(int(v)).zfill(f["digits"])
            assert len(text) == f["size"], (f["name"], text)
        else:
            text = str(v).ljust(f["size"])[: f["size"]]
        buf[f["offset"]: f["offset"] + f["size"]] = text.encode("ascii")
    return bytes(buf)


# ---------------------------------------------------------------- cases ----
def generate_records(layout: list[dict], seed: int = 0, n_random: int = 20) -> list[tuple[str, bytes]]:
    """Return (label, record bytes). Order is deterministic for a given seed."""
    fields = expand_fields(layout)
    rng = random.Random(seed)

    def typical(i: int = 1) -> dict:
        return {f["name"]: (typical_numeric(f["digits"]) if f["category"] == "numeric"
                            else typical_alnum(f["size"], i)) for f in fields}

    def cands(f):
        return numeric_candidates(f["digits"]) if f["category"] == "numeric" else alnum_candidates(f["size"])

    recs: list[tuple[str, bytes]] = []
    # One-factor-at-a-time: vary a single field across its boundary values.
    for f in fields:
        for c in cands(f):
            vals = typical(len(recs) + 1)
            vals[f["name"]] = c
            recs.append((f"{f['name']}={c!r}", format_record(fields, vals)))
    # Extremes across all fields at once.
    recs.append(("all-zero", format_record(fields, {
        f["name"]: (0 if f["category"] == "numeric" else typical_alnum(f["size"])) for f in fields})))
    recs.append(("all-max", format_record(fields, {
        f["name"]: (10 ** f["digits"] - 1 if f["category"] == "numeric" else "Z" * f["size"]) for f in fields})))
    # Seeded random records.
    for k in range(n_random):
        vals = {}
        for f in fields:
            if f["category"] == "numeric":
                # mix magnitudes so small and large values both appear
                mag = rng.randint(1, f["digits"])
                vals[f["name"]] = rng.randint(0, 10**mag - 1)
            else:
                vals[f["name"]] = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789")
                                          for _ in range(f["size"]))
        recs.append((f"random-{k}", format_record(fields, vals)))
    return recs


def generate_cases(layout: list[dict], seed: int = 0, n_random: int = 20, per_file: int = 8) -> list[Case]:
    """Chunk records into input files. Small files keep failing diffs readable
    and let the repair loop see which records break."""
    recs = generate_records(layout, seed, n_random)
    cases = []
    for i in range(0, len(recs), per_file):
        chunk = recs[i: i + per_file]
        data = b"\n".join(r for _, r in chunk) + b"\n"
        cases.append(Case(f"case-{i // per_file + 1:02d}", data, len(chunk)))
    return cases
"""Failure taxonomy: every first-attempt failure, with an automatic HINT tag and the repair diff.

    python -m core.taxonomy [--run-dir run] [--csv docs/failures.csv] [--show]

The auto tag is a first guess from the diff text. Read the repair diff (what the model
changed to fix it) and fill the `label` column of the CSV by hand: that label is the
finding, the auto tag only saves typing.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

NUM = re.compile(r"\d[\d,]*\.?\d*")


def _f(s: str) -> float | None:
    try:
        return float(s.replace(",", "").rstrip("."))
    except ValueError:
        return None


def auto_tag(failure: str) -> str:
    text = (failure or "").strip()
    if text.startswith("BUILD ERROR"):
        return "compile_error"
    if text.startswith("NO GO CODE"):
        return "no_code"
    blocks = [b for b in text.split("\n\n") if b.strip()]
    reasons = [m.group(1) for b in blocks if (m := re.match(r"\[.+?\] (\w+)", b))]
    if "timeout" in reasons:
        return "timeout"
    if "crash" in reasons:
        return "runtime_crash"
    first = blocks[0].replace("\u00b7", " ") if blocks else ""
    exp = [l[1:] for l in first.splitlines() if l.startswith("-")]
    act = [l[1:] for l in first.splitlines() if l.startswith("+")]
    if not exp and not act:
        return "byte_difference"
    if len(exp) != len(act):
        return "missing_or_extra_lines"
    pairs = [(e, a) for e, a in zip(exp, act) if e != a]
    if all(e.split() == a.split() for e, a in pairs):
        return "alignment_or_whitespace"
    diffs = []
    for e, a in pairs:
        ne, na = NUM.findall(e), NUM.findall(a)
        shape = lambda x: re.sub(r"\s+", " ", re.sub(NUM, "#", x)).strip()    # ignore alignment
        if len(ne) != len(na) or shape(e) != shape(a):
            return "text_mismatch"
        diffs += [(_f(x), _f(y), e) for x, y in zip(ne, na) if x != y]
    if any(y == 0 and x not in (0, None) for x, y, _ in diffs):
        return "zero_result"
    if diffs and all(x is not None and y is not None and abs(x - y) <= 0.0101 for x, y, _ in diffs):
        return "cent_off_by_rounding"
    if diffs and all(re.search(r"TOTAL|GRAND", ln) for _, _, ln in diffs):
        return "total_mismatch"
    return "value_mismatch"


def repair_diff(run: Path, limit: int = 40) -> str:
    a0 = run / "attempt_0.go"
    final = run / "main.go"
    if not final.exists():
        later = sorted(run.glob("attempt_*.go"))[1:]
        final = later[-1] if later else None
    if not a0.exists() or final is None:
        return ""
    lines = list(difflib.unified_diff(a0.read_text().splitlines(), final.read_text().splitlines(),
                                      "first attempt", "final", lineterm="", n=1))
    more = len(lines) - limit
    return "\n".join(lines[:limit] + ([f"... {more} more diff lines"] if more > 0 else []))


def collect_failures(run_dir: str | Path = "run") -> list[dict]:
    out = []
    for p in sorted(Path(run_dir).rglob("result.json")):
        try:
            r = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        atts = r.get("attempts") or []
        if r.get("single_shot_ok") or not atts or not atts[0].get("failure"):
            continue
        out.append({"run": f"{r.get('provider')}/{r.get('program')}/sample{r.get('sample')}",
                    "provider": r.get("provider"), "program": r.get("program"), "sample": r.get("sample"),
                    "status": r.get("status"), "repairs_used": r.get("repairs_used"),
                    "auto_tag": auto_tag(atts[0]["failure"]), "label": "", "notes": "",
                    "first_failure": atts[0]["failure"], "repair_diff": repair_diff(p.parent)})
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["run", "status", "repairs_used", "auto_tag", "label", "notes", "first_failure", "repair_diff"]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="run")
    ap.add_argument("--csv", type=Path, default=Path("docs/failures.csv"))
    ap.add_argument("--show", action="store_true", help="print each failure and its repair diff")
    a = ap.parse_args(argv[1:])
    rows = collect_failures(a.run_dir)
    for r in rows:
        print(f"{r['run']:<40} {r['auto_tag']:<24} status={r['status']} repairs={r['repairs_used']}")
        if a.show:
            print("  " + "\n  ".join(r["first_failure"].splitlines()[:10]))
            print("  --- repair diff ---\n  " + "\n  ".join(r["repair_diff"].splitlines()) + "\n")
    print("\nby auto tag:", dict(Counter(r["auto_tag"] for r in rows)) or "(no first-attempt failures)")
    write_csv(rows, a.csv)
    print(f"wrote {a.csv}: fill the `label` column by hand")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
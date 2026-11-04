"""Summarise result.json files under run/ into one comparison table.

    python -m core.summarize [run_dir]

Groups by provider + model + effort + program and reports how many runs
passed on the first translation (the single-shot baseline), how many ended
verified, repairs used, output tokens and cost. avg_list_cost_usd is the price at list rates (meaningful even when calls
were served from the cache); total_cost_usd is what was actually spent. `errors`
counts runs that ended for infrastructure reasons (API errors, budget stop...), not
translation failures. Run it after a batch of
`--sample N` runs.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def load_results(run_dir: str | Path = "run") -> list[dict]:
    out = []
    for p in sorted(Path(run_dir).rglob("result.json")):
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return out


EFFORT_ORDER = {"default": 0, "low": 1, "medium": 2, "high": 3}


def effort_label(r: dict) -> str:
    """'none' (no effort sent) and the old 'default' label are the same thing: the model's own default."""
    e = str(r.get("effort") or "none")
    return "default" if e in ("none", "default") else e


def _done(rs):
    return [r for r in rs if r.get("status") in ("verified", "failed")]       # not API/budget errors


def summarize(results: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        groups[(r.get("provider"), r.get("model"), r.get("effort"), r.get("program"))].append(r)
    rows = []
    for (prov, model, effort, prog), rs in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0]))):
        n, done = len(rs), _done(rs)
        c = len(done)
        verified = [r for r in done if r.get("status") == "verified"]
        tokens = [sum(a.get("output_tokens", 0) for a in r.get("attempts", [])) for r in done]
        rows.append({
            "provider": prov, "model": model, "effort": effort, "program": prog, "runs": n, "completed": c,
            "single_shot": f"{sum(bool(r.get('single_shot_ok')) for r in done)}/{c}",
            "verified": f"{len(verified)}/{c}", "errors": n - c,
            "avg_repairs": round(sum(r.get("repairs_used", 0) for r in verified) / len(verified), 2) if verified else None,
            "avg_out_tokens": round(sum(tokens) / c) if c else None,
            "avg_list_cost_usd": round(sum(r.get("total_list_cost_usd", r.get("total_cost_usd", 0.0)) for r in rs) / n, 4),
            "total_cost_usd": round(sum(r.get("total_cost_usd", 0.0) for r in rs), 4),
        })
    return rows


def overall(results: list[dict]) -> list[dict]:
    """Pooled per provider. Rates use COMPLETED runs; API errors (e.g. a reply cut off at the
    token cap) are reported separately and their cost is included in cost_per_verified."""
    by: dict = defaultdict(list)
    for r in results:
        by[r.get("provider")].append(r)
    out = []
    for prov, rs in sorted(by.items(), key=lambda kv: str(kv[0])):
        done = _done(rs)
        ver = [r for r in done if r["status"] == "verified"]
        c, ss = len(done), sum(bool(r.get("single_shot_ok")) for r in done)
        toks = [sum(a.get("output_tokens", 0) for a in r.get("attempts", [])) for r in done]
        lc = sum(r.get("total_list_cost_usd", r.get("total_cost_usd", 0.0)) for r in rs)
        out.append({"provider": prov, "runs": len(rs), "completed": c, "errors": len(rs) - c,
                    "first_try": f"{ss}/{c}", "first_try_rate": round(ss / c, 3) if c else None,
                    "verified": f"{len(ver)}/{c}", "verified_rate": round(len(ver) / c, 3) if c else None,
                    "repairs": sum(r.get("repairs_used", 0) for r in ver),
                    "avg_out_tokens": round(sum(toks) / c) if c else None, "list_cost_usd": round(lc, 2),
                    "cost_per_verified_usd": round(lc / len(ver), 4) if ver else None})
    return out


def matrix(results: list[dict]) -> list[dict]:
    """Provider x model x reasoning effort, pooled over programs. Rates use completed runs."""
    g: dict = defaultdict(list)
    for r in results:
        g[(r.get("provider"), r.get("model"), effort_label(r))].append(r)
    rows = []
    for (prov, model, eff), rs in g.items():
        done = _done(rs)
        c = len(done)
        ver = [r for r in done if r["status"] == "verified"]
        ss = sum(bool(r.get("single_shot_ok")) for r in done)
        lc = sum(r.get("total_list_cost_usd", r.get("total_cost_usd", 0.0)) for r in rs)
        toks = [sum(a.get("output_tokens", 0) for a in r.get("attempts", [])) for r in done]
        rows.append({"provider": prov, "model": model, "effort": eff, "runs": len(rs), "completed": c,
                     "errors": len(rs) - c, "first_try": f"{ss}/{c}",
                     "first_try_pct": round(100 * ss / c) if c else None,
                     "verified": f"{len(ver)}/{c}", "verified_pct": round(100 * len(ver) / c) if c else None,
                     "repairs_per_run": round(sum(r.get("repairs_used", 0) for r in done) / c, 2) if c else None,
                     "avg_out_tokens": round(sum(toks) / c) if c else None,
                     "cost_per_verified_usd": round(lc / len(ver), 4) if ver else None})
    rows.sort(key=lambda r: (str(r["provider"]), str(r["model"]), EFFORT_ORDER.get(r["effort"], 9)))
    return rows


MATRIX_COLS = ["provider", "effort", "runs", "completed", "errors", "first_try", "first_try_pct", "verified",
               "verified_pct", "repairs_per_run", "avg_out_tokens", "cost_per_verified_usd"]
COLS = ["provider", "program", "effort", "runs", "completed", "single_shot", "verified", "errors",
        "avg_repairs", "avg_out_tokens", "avg_list_cost_usd", "total_cost_usd"]
OVERALL_COLS = ["provider", "runs", "completed", "errors", "first_try", "verified", "repairs",
                "avg_out_tokens", "list_cost_usd", "cost_per_verified_usd"]


def to_markdown(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols)
    return head + "\n" + "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows)


def format_table(rows: list[dict], cols: list[str] | None = None) -> str:
    if not rows:
        return "(no result.json files found)"
    cols = cols or COLS
    data = [[str(r[c]) for c in cols] for r in rows]
    widths = [max(len(c), *(len(d[i]) for d in data)) for i, c in enumerate(cols)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths))
    return "\n".join([line(cols), line(["-" * w for w in widths])] + [line(d) for d in data])


if __name__ == "__main__":
    a = sys.argv[1:]
    res = load_results(next((x for x in a if not x.startswith("--")), "run"))
    rows, cols = ((matrix(res), MATRIX_COLS) if "--matrix" in a else
                  (overall(res), OVERALL_COLS) if "--overall" in a else (summarize(res), COLS))
    print(to_markdown(rows, cols) if "--markdown" in a else format_table(rows, cols))
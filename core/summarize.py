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


def summarize(results: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        groups[(r.get("provider"), r.get("model"), r.get("effort"), r.get("program"))].append(r)
    rows = []
    for (prov, model, effort, prog), rs in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0]))):
        n = len(rs)
        verified = [r for r in rs if r.get("status") == "verified"]
        errors = sum(r.get("status") not in ("verified", "failed") for r in rs)   # infra, not translation
        tokens = [sum(a.get("output_tokens", 0) for a in r.get("attempts", [])) for r in rs]
        rows.append({
            "provider": prov, "model": model, "effort": effort, "program": prog, "runs": n,
            "single_shot": f"{sum(bool(r.get('single_shot_ok')) for r in rs)}/{n}",
            "verified": f"{len(verified)}/{n}",
            "avg_repairs": round(sum(r.get("repairs_used", 0) for r in verified) / len(verified), 2) if verified else None,
            "avg_out_tokens": round(sum(tokens) / n),
            "errors": errors,
            "avg_list_cost_usd": round(sum(r.get("total_list_cost_usd", r.get("total_cost_usd", 0.0))
                                           for r in rs) / n, 4),
            "total_cost_usd": round(sum(r.get("total_cost_usd", 0.0) for r in rs), 4),
        })
    return rows


def format_table(rows: list[dict]) -> str:
    if not rows:
        return "(no result.json files found)"
    cols = ["provider", "program", "effort", "runs", "single_shot", "verified", "errors",
            "avg_repairs", "avg_out_tokens", "avg_list_cost_usd", "total_cost_usd"]
    data = [[str(r[c]) for c in cols] for r in rows]
    widths = [max(len(c), *(len(d[i]) for d in data)) for i, c in enumerate(cols)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths))
    return "\n".join([line(cols), line(["-" * w for w in widths])] + [line(d) for d in data])


if __name__ == "__main__":
    print(format_table(summarize(load_results(sys.argv[1] if len(sys.argv) > 1 else "run"))))
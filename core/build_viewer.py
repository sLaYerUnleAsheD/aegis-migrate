"""Emit viewer/data/*.json for the static results app.

    python -m core.build_viewer [--run-dir run] [--data-dir viewer/data]

The HTML/JS in viewer/ is hand-written. This command only writes JSON that
the app fetches lazily (index first, then one program and one run at a time).
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from cobol_adapter.analyzer import analyze, record_layout
from core.summarize import overall, summarize
from core.taxonomy import auto_tag, load_labels

HEAVY = ("cobol", "attempt_go", "final_go")


def run_id(r: dict) -> str:
    effort = str(r.get("effort") or "default").replace(" ", "-")
    return f"{r.get('provider')}__{r.get('program')}__effort-{effort}__s{r.get('sample')}"


def mutation(run_dir) -> list[dict]:
    out = []
    for p in sorted((Path(run_dir) / "mutation").glob("*.json")):
        try:
            j = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        st = j.get("stress") or {}
        out.append({"program": p.stem, "mutants": j.get("mutants"), "caught": j.get("caught"),
                    "survived": j.get("survived"), "catch_rate": j.get("catch_rate"),
                    "with_more_inputs": st.get("catch_rate_with_more_inputs")})
    return out


def _done(rs):
    return [r for r in rs if r.get("status") in ("verified", "failed")]


def matrix(results: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        groups[(r.get("provider"), r.get("effort"))].append(r)
    rows = []
    for (prov, effort), rs in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0]))):
        done = _done(rs)
        ver = [r for r in done if r.get("status") == "verified"]
        c, ss = len(done), sum(bool(r.get("single_shot_ok")) for r in done)
        toks = [sum(a.get("output_tokens", 0) for a in r.get("attempts", [])) for r in done]
        lc = sum(r.get("total_list_cost_usd", r.get("total_cost_usd", 0.0)) or 0.0 for r in rs)
        repairs = [r.get("repairs_used", 0) for r in done]
        rows.append({
            "provider": prov, "effort": effort,
            "first_try_pct": round(100 * ss / c) if c else None,
            "verified_pct": round(100 * len(ver) / c) if c else None,
            "first_try": f"{ss}/{c}" if c else "0/0",
            "verified": f"{len(ver)}/{c}" if c else "0/0",
            "repairs_per_run": round(sum(repairs) / c, 2) if c else None,
            "avg_out_tokens": round(sum(toks) / c) if c else None,
            "cost_per_verified_usd": round(lc / len(ver), 4) if ver else None,
            "runs": len(rs),
        })
    return rows


def _label_for(r: dict, labels: dict) -> tuple[str, str, str]:
    key = f"{r.get('provider')}/{r.get('program')}/sample{r.get('sample')}"
    hand = labels.get(key) or {}
    if hand.get("label"):
        return hand["label"], "hand", hand.get("notes") or ""
    atts = r.get("attempts") or []
    fail = atts[0].get("failure") if atts else ""
    if fail:
        return auto_tag(fail), "auto", ""
    return "", "auto", ""


def _out_tokens(r: dict) -> int:
    return sum(a.get("output_tokens", 0) or 0 for a in r.get("attempts", []))


def _list_cost(r: dict) -> float:
    v = r.get("total_list_cost_usd")
    if v is None:
        v = r.get("total_cost_usd", 0.0)
    return round(float(v or 0.0), 6)


def _slim_attempt(a: dict) -> dict:
    return {
        "n": a.get("n"), "kind": a.get("kind"), "built": a.get("built"),
        "passed_cases": a.get("passed_cases"), "output_tokens": a.get("output_tokens"),
        "list_cost_usd": a.get("list_cost_usd") if a.get("list_cost_usd") is not None else a.get("cost_usd"),
        "cost_usd": a.get("cost_usd"), "cached": a.get("cached"),
        "failure": a.get("failure") or "",
    }


def _sample_bits(cbl: Path) -> tuple[str, str]:
    dat = cbl.with_name(cbl.stem + ".sample.dat")
    gold = cbl.with_name(cbl.stem + ".sample.golden")
    sample = dat.read_text() if dat.exists() else ""
    golden = ""
    if gold.exists():
        text = gold.read_text()
        try:
            j = json.loads(text)
            golden = j.get("stdout") or ""
        except ValueError:
            golden = text
    return sample, golden


def program_payload(cbl: Path, tier: str) -> dict:
    src = cbl.read_text() if cbl.exists() else ""
    risks, layout, paras, go_types = [], [], [], ""
    try:
        a = analyze(src) if src else None
    except Exception:
        a = None
    if a is not None:
        risks = list(a.risk_features or [])
        go_types = a.go_types or ""
        paras = [{"name": p.name, "performs": list(p.performs)} for p in a.paragraphs]
        try:
            layout = record_layout(a)
        except ValueError:
            layout = []
    sample, golden = _sample_bits(cbl) if cbl.exists() else ("", "")
    return {"name": cbl.stem, "cobol": src, "tier": tier, "risks": risks, "layout": layout,
            "paragraphs": paras, "go_types": go_types, "sample_input": sample,
            "golden_stdout": golden}


def discover_programs(programs: str | Path) -> dict[str, Path]:
    out = {}
    for p in sorted(Path(programs).rglob("*.cbl")):
        out[p.stem] = p
    return out


def collect(run_dir="run", programs="benchmark/programs", labels_csv="docs/failure_labels.csv") -> dict:
    labels = load_labels(labels_csv)
    prog_files = discover_programs(programs)
    runs = []
    for p in sorted(Path(run_dir).rglob("result.json")):
        try:
            r = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        r["attempt_go"] = {a.name: a.read_text() for a in sorted(p.parent.glob("attempt_*.go"))}
        if r.get("final_go") in r["attempt_go"].values():
            r.pop("final_go")
        cbl = prog_files.get(r.get("program", ""))
        r["cobol"] = cbl.read_text() if cbl else ""
        r.setdefault("attempts", [])
        lab, src, notes = _label_for(r, labels)
        r["id"] = run_id(r)
        r["label"], r["label_source"], r["label_notes"] = lab, src, notes
        r["tier"] = cbl.parent.name if cbl else ""
        runs.append(r)
    plain = [{k: v for k, v in r.items() if k not in HEAVY} for r in runs]
    fail_counts = Counter()
    for r in runs:
        if r.get("label_source") != "hand" or not r.get("label"):
            continue
        fail_counts[r["label"]] += 1
    programs_meta = []
    seen = set()
    for name, cbl in prog_files.items():
        programs_meta.append({"name": name, "tier": cbl.parent.name})
        seen.add(name)
    for r in runs:
        if r.get("program") not in seen:
            programs_meta.append({"name": r.get("program"), "tier": r.get("tier") or ""})
            seen.add(r.get("program"))
    programs_meta.sort(key=lambda x: (str(x.get("tier")), str(x.get("name"))))
    return {"runs": runs, "summary": summarize(plain), "overall": overall(plain),
            "labels": labels, "mutation": mutation(run_dir), "matrix": matrix(plain),
            "failure_counts": dict(fail_counts), "programs": programs_meta}


def index_payload(data: dict) -> dict:
    runs = []
    for r in data["runs"]:
        runs.append({
            "id": r["id"], "provider": r.get("provider"), "model": r.get("model"),
            "effort": r.get("effort"), "program": r.get("program"), "tier": r.get("tier"),
            "sample": r.get("sample"), "status": r.get("status"),
            "first_try": bool(r.get("single_shot_ok")),
            "repairs": r.get("repairs_used") or 0,
            "cost_list_usd": _list_cost(r), "out_tokens": _out_tokens(r),
            "label": r.get("label") or "",
        })
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "programs": data["programs"], "runs": runs, "summary": data["summary"],
        "overall": data["overall"], "matrix": data["matrix"],
        "mutation": data["mutation"], "failure_counts": data["failure_counts"],
    }


def run_payload(r: dict) -> dict:
    return {
        "id": r["id"], "program": r.get("program"), "provider": r.get("provider"),
        "model": r.get("model"), "effort": r.get("effort"), "sample": r.get("sample"),
        "tier": r.get("tier"), "status": r.get("status"),
        "single_shot_ok": bool(r.get("single_shot_ok")),
        "repairs_used": r.get("repairs_used") or 0, "cases": r.get("cases"),
        "attempts": [_slim_attempt(a) for a in r.get("attempts") or []],
        "attempt_go": r.get("attempt_go") or {},
        "label": r.get("label") or "", "label_source": r.get("label_source") or "auto",
        "label_notes": r.get("label_notes") or "",
        "total_list_cost_usd": _list_cost(r),
        "total_cost_usd": r.get("total_cost_usd"),
        "detail": r.get("detail") or "",
        "risk_features": r.get("risk_features") or [],
        "warnings": r.get("warnings") or [],
    }


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def build(run_dir="run", out="viewer/index.html", programs="benchmark/programs",
          labels_csv="docs/failure_labels.csv", data_dir=None) -> Path:
    """Write data JSON. `out` is kept so older callers that passed an HTML path
    still work: JSON lands in <parent>/data (the HTML itself is not generated)."""
    if data_dir is None:
        outp = Path(out)
        data_dir = outp if outp.suffix == "" else outp.parent / "data"
    data_dir = Path(data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data = collect(run_dir, programs, labels_csv)
    _dump(data_dir / "index.json", index_payload(data))
    prog_files = discover_programs(programs)
    written = set()
    for name, cbl in prog_files.items():
        _dump(data_dir / "programs" / f"{name}.json", program_payload(cbl, cbl.parent.name))
        written.add(name)
    for r in data["runs"]:
        name = r.get("program")
        if name and name not in written:
            cbl = Path(programs) / f"{name}.cbl"
            _dump(data_dir / "programs" / f"{name}.json",
                  program_payload(cbl if cbl.exists() else Path(name), r.get("tier") or ""))
            written.add(name)
        _dump(data_dir / "runs" / f"{r['id']}.json", run_payload(r))
    return data_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="run")
    ap.add_argument("--out", default=None, help="legacy: writes JSON next to this HTML path")
    ap.add_argument("--data-dir", default="viewer/data")
    a = ap.parse_args()
    dest = a.data_dir if a.out is None else None
    out = a.out or "viewer/index.html"
    print(f"wrote {build(a.run_dir, out, data_dir=dest)}")

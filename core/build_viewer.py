"""Build viewer/index.html: ONE self-contained page (data embedded) for every result in run/.

    python -m core.build_viewer [--run-dir run] [--out viewer/index.html]

Works from file:// and on any static host: no server, no fetch.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from core.summarize import effort_label, matrix, overall, summarize
from core.taxonomy import collect_failures, load_labels

HEAVY = ("cobol", "attempt_go", "final_go")


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


def collect(run_dir="run", programs="benchmark/programs", labels_csv="docs/failure_labels.csv") -> dict:
    runs = []
    for p in sorted(Path(run_dir).rglob("result.json")):
        try:
            r = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        r["attempt_go"] = {a.name: a.read_text() for a in sorted(p.parent.glob("attempt_*.go"))}
        if r.get("final_go") in r["attempt_go"].values():
            r.pop("final_go")                               # already present as an attempt file
        cbl = next(Path(programs).rglob(f"{r.get('program', '')}.cbl"), None)
        r["cobol"] = cbl.read_text() if cbl else ""
        r.setdefault("attempts", [])
        runs.append(r)
    plain = [{k: v for k, v in r.items() if k not in HEAVY} for r in runs]
    return {"runs": runs, "summary": summarize(plain), "overall": overall(plain),
            "labels": load_labels(labels_csv), "mutation": mutation(run_dir)}


def build(run_dir="run", out="viewer/index.html", programs="benchmark/programs",
          labels_csv="docs/failure_labels.csv") -> Path:
    data = json.dumps(collect(run_dir, programs, labels_csv)).replace("</", "<\\/")     # never closes the script tag
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.replace("__DATA__", data))
    return out


def export_data(run_dir="run", out_dir="viewer/data", programs="benchmark/programs",
                labels_csv="docs/failure_labels.csv", golden="benchmark/golden") -> Path:
    """Split JSON for the app-style frontend: index.json (small), programs/<name>.json, runs/<id>.json
    (loaded lazily). Contract documented in docs/FRONTEND_SPEC.md."""
    import shutil
    from cobol_adapter.analyzer import analyze, record_layout
    out = Path(out_dir)
    runs_dir = out / "runs"
    progs_dir = out / "programs"
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
    if progs_dir.exists():
        shutil.rmtree(progs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    progs_dir.mkdir(parents=True, exist_ok=True)
    labels = load_labels(labels_csv)
    fails = {f["run"]: f for f in collect_failures(run_dir, labels)}
    tiers, plist = {}, []
    for cbl in sorted(Path(programs).rglob("*.cbl")):
        src, tier = cbl.read_text(), cbl.parent.name
        a = analyze(src)
        try:
            layout = record_layout(a)
        except ValueError:
            layout = []
        sample, gold = cbl.with_name(cbl.stem + ".sample.dat"), Path(golden) / f"{cbl.stem}.sample.stdout"
        (out / "programs" / f"{cbl.stem}.json").write_text(json.dumps({
            "name": cbl.stem, "tier": tier, "cobol": src, "risks": a.risk_features, "layout": layout,
            "paragraphs": [{"name": q.name, "performs": q.performs} for q in a.paragraphs], "go_types": a.go_types,
            "sample_input": sample.read_text() if sample.exists() else "",
            "golden_stdout": gold.read_text() if gold.exists() else ""}))
        tiers[cbl.stem] = tier
        plist.append({"name": cbl.stem, "tier": tier})
    runs, plain = [], []
    for p in sorted(Path(run_dir).rglob("result.json")):
        try:
            r = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        eff = effort_label(r)
        rid = f"{r.get('provider')}__{r.get('program')}__{eff}__s{r.get('sample')}"
        key = f"{r.get('provider')}/{r.get('program')}/sample{r.get('sample')}"
        go = {a.name: a.read_text() for a in sorted(p.parent.glob("attempt_*.go"))}
        if r.get("final_go") in go.values():
            r.pop("final_go")
        fl = fails.get(key, {})
        (out / "runs" / f"{rid}.json").write_text(json.dumps({**r, "id": rid, "effort": eff,
            "tier": tiers.get(r.get("program"), ""), "attempt_go": go,
            "label": fl.get("label", ""), "label_source": fl.get("label_source", ""), "label_notes": fl.get("notes", "")}))
        plain.append({k: v for k, v in r.items() if k not in HEAVY})
        cost_val = r.get("total_list_cost_usd")
        if cost_val is None:
            cost_val = r.get("total_cost_usd", 0.0)
        runs.append({"id": rid, "provider": r.get("provider"), "model": r.get("model"), "effort": eff,
                     "program": r.get("program"), "tier": tiers.get(r.get("program"), ""), "sample": r.get("sample"),
                     "status": r.get("status"), "first_try": bool(r.get("single_shot_ok")),
                     "repairs": r.get("repairs_used", 0) or 0,
                     "cost_list_usd": float(cost_val or 0.0),
                     "out_tokens": sum((a.get("output_tokens", 0) or 0) for a in r.get("attempts", [])),
                     "label": fl.get("label", "")})
    (out / "index.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "programs": plist, "runs": runs,
        "summary": summarize(plain), "overall": overall(plain), "matrix": matrix(plain), "mutation": mutation(run_dir),
        "failure_counts": dict(Counter(f["label"] for f in fails.values())), "labels": labels}))
    return out / "index.json"


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Aegis Migrate: runs</title>
<style>
:root{--bg:#fff;--fg:#1c1c1e;--mut:#6b6b70;--line:#e2e2e6;--ok:#1a7f37;--bad:#c62828;--pre:#f6f6f8}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececf0;--mut:#9a9aa2;--line:#2c2c31;--ok:#4cc26a;--bad:#ff6b6b;--pre:#1d1d21}}
body{margin:0;padding:1rem 1.25rem;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
h1{font-size:1.2rem;margin:.2rem 0 1rem}h2{font-size:1rem;margin:1.4rem 0 .5rem}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.3rem .6rem;border-bottom:1px solid var(--line);white-space:nowrap}
.wrap{overflow-x:auto}button{margin:0 .4rem .4rem 0;padding:.25rem .6rem;border:1px solid var(--line);background:none;color:var(--fg);border-radius:6px;cursor:pointer}
button.on{border-color:var(--fg);font-weight:600}.ok{color:var(--ok)}.bad{color:var(--bad)}.mut{color:var(--mut);margin:.2rem 0}
.del{color:var(--bad)}.add{color:var(--ok)}.chip{border:1px solid var(--line);border-radius:10px;padding:.05rem .5rem;margin-left:.5rem;font-weight:400;font-size:.8rem}
.row{display:flex;align-items:center;gap:.6rem;margin:.15rem 0}.lbl{width:6.5rem;color:var(--mut)}.barbg{background:var(--line);border-radius:3px;width:14rem;height:.7rem}.bar{height:.7rem;border-radius:3px;background:var(--ok)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}@media(max-width:800px){.cols{grid-template-columns:1fr}}
pre{background:var(--pre);padding:.7rem;border-radius:6px;overflow:auto;max-height:28rem;font:12px/1.4 ui-monospace,monospace;margin:0}
</style></head><body>
<h1>Aegis Migrate: COBOL → Go verification runs</h1>
<h2>Pooled by provider</h2><div id="ov" class="wrap"></div><div id="bars"></div>
<h2>Verifier strength (mutation testing)</h2><div id="mut" class="wrap"></div>
<h2>By program</h2><div id="sum" class="wrap"></div><h2>Runs</h2><div id="runs"></div><div id="detail"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const el=(t,c,...k)=>{const e=document.createElement(t);if(c)e.className=c;k.forEach(x=>e.append(x));return e};
const fmt=v=>Number(v??0).toFixed(4);
function table(rows,keys){const t=el('table'),h=el('tr');keys.forEach(k=>h.append(el('th','',k)));t.append(h);
 rows.forEach(r=>{const tr=el('tr');keys.forEach(k=>tr.append(el('td','',String(r[k]??''))));t.append(tr)});return t}
document.getElementById('sum').append(table(D.summary,['provider','program','effort','runs','single_shot','verified','errors','avg_repairs','avg_out_tokens','avg_list_cost_usd','total_cost_usd']));
document.getElementById('ov').append(table(D.overall,['provider','runs','completed','errors','first_try','verified','repairs','avg_out_tokens','list_cost_usd','cost_per_verified_usd']));
const bar=(l,v,c)=>{const b=el('div','bar');b.style.width=(100*(v||0))+'%';if(c)b.style.background=c;return el('div','row',el('span','lbl',l),el('div','barbg',b),el('span','mut',((v||0)*100).toFixed(0)+'%'))};
D.overall.forEach(o=>document.getElementById('bars').append(el('p','mut',`${o.provider}: ${o.completed} completed runs`),bar('first try',o.first_try_rate,'var(--bad)'),bar('after repair',o.verified_rate)));
document.getElementById('mut').append(D.mutation.length?table(D.mutation,['program','mutants','caught','survived','catch_rate','with_more_inputs']):'Run python -m core.mutate (see README) to fill this in.');
const diffPre=t=>{const p=el('pre');t.split('\n').forEach(l=>p.append(el('span',l[0]==='-'?'del':l[0]==='+'?'add':'',l+'\n')));return p};
const runsDiv=document.getElementById('runs');
function show(i){[...runsDiv.children].forEach((b,j)=>b.classList.toggle('on',i===j));
 const r=D.runs[i],d=document.getElementById('detail');d.replaceChildren();
 d.append(el('h2','',`${r.provider} · ${r.program} · sample ${r.sample}`));
 d.append(el('p','',el('b',r.status==='verified'?'ok':'bad',String(r.status)),` · first attempt ${r.single_shot_ok?'passed':'failed'} · repairs ${r.repairs_used} · list cost $${fmt(r.total_list_cost_usd??r.total_cost_usd)} · ${r.model}`));
 const rows=r.attempts.map(a=>({attempt:a.kind,built:a.built,passed:`${a.passed_cases}/${r.cases}`,out_tokens:a.output_tokens,cost:fmt(a.list_cost_usd??a.cost_usd)}));
 d.append(el('div','wrap',table(rows,['attempt','built','passed','out_tokens','cost'])));
 const lab=D.labels[`${r.provider}/${r.program}/sample${r.sample}`];
 r.attempts.filter(a=>a.failure).forEach((a,i)=>d.append(el('h2','',`Why ${a.kind} failed`,...(i===0&&lab?[el('span','chip',lab.label+(lab.notes?': '+lab.notes:''))]:[])),diffPre(a.failure)));
 const names=Object.keys(r.attempt_go),sel=el('select'),go=el('pre');
 names.forEach(n=>sel.append(new Option(n,n)));
 const setGo=()=>{go.textContent=r.attempt_go[sel.value]??r.final_go??''};
 if(names.length)sel.value=names[names.length-1];sel.onchange=setGo;setGo();
 d.append(el('h2','','Source and translation'),el('div','cols',el('div','',el('p','mut','COBOL (original)'),el('pre','',r.cobol)),el('div','',el('p','mut','Go: ',sel),go)))}
D.runs.forEach((r,i)=>{const b=el('button','',`${r.provider}/${r.program}/s${r.sample}`+(r.status==='verified'?'':' ✗'));b.onclick=()=>show(i);runsDiv.append(b)});
D.runs.length?show(0):document.getElementById('detail').append('No results found in run/.');
</script></body></html>"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="run")
    ap.add_argument("--out", default=None, help="write legacy single-page HTML report")
    ap.add_argument("--data-dir", default=None, help="also write split JSON for the app-style frontend")
    a = ap.parse_args()
    if a.out:
        print(f"wrote {build(a.run_dir, a.out)}")
    if a.data_dir:
        print(f"wrote {export_data(a.run_dir, a.data_dir)}")
    if not a.out and not a.data_dir:
        print(f"wrote {export_data(a.run_dir, 'viewer/data')}")

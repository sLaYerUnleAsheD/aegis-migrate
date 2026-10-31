"""Build viewer/index.html: ONE self-contained page (data embedded) for every result in run/.

    python -m core.build_viewer [--run-dir run] [--out viewer/index.html]

Works from file:// and on any static host: no server, no fetch.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.summarize import summarize

HEAVY = ("cobol", "attempt_go", "final_go")


def collect(run_dir="run", programs="benchmark/programs") -> dict:
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
    rows = summarize([{k: v for k, v in r.items() if k not in HEAVY} for r in runs])
    return {"runs": runs, "summary": rows}


def build(run_dir="run", out="viewer/index.html", programs="benchmark/programs") -> Path:
    data = json.dumps(collect(run_dir, programs)).replace("</", "<\\/")     # never closes the script tag
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.replace("__DATA__", data))
    return out


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
.cols{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}@media(max-width:800px){.cols{grid-template-columns:1fr}}
pre{background:var(--pre);padding:.7rem;border-radius:6px;overflow:auto;max-height:28rem;font:12px/1.4 ui-monospace,monospace;margin:0}
</style></head><body>
<h1>Aegis Migrate: COBOL → Go verification runs</h1>
<div id="sum" class="wrap"></div><h2>Runs</h2><div id="runs"></div><div id="detail"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const el=(t,c,...k)=>{const e=document.createElement(t);if(c)e.className=c;k.forEach(x=>e.append(x));return e};
const fmt=v=>Number(v??0).toFixed(4);
function table(rows,keys){const t=el('table'),h=el('tr');keys.forEach(k=>h.append(el('th','',k)));t.append(h);
 rows.forEach(r=>{const tr=el('tr');keys.forEach(k=>tr.append(el('td','',String(r[k]??''))));t.append(tr)});return t}
document.getElementById('sum').append(table(D.summary,['provider','program','effort','runs','single_shot','verified','errors','avg_repairs','avg_out_tokens','avg_list_cost_usd','total_cost_usd']));
const runsDiv=document.getElementById('runs');
function show(i){[...runsDiv.children].forEach((b,j)=>b.classList.toggle('on',i===j));
 const r=D.runs[i],d=document.getElementById('detail');d.replaceChildren();
 d.append(el('h2','',`${r.provider} · ${r.program} · sample ${r.sample}`));
 d.append(el('p','',el('b',r.status==='verified'?'ok':'bad',String(r.status)),` · first attempt ${r.single_shot_ok?'passed':'failed'} · repairs ${r.repairs_used} · list cost $${fmt(r.total_list_cost_usd??r.total_cost_usd)} · ${r.model}`));
 const rows=r.attempts.map(a=>({attempt:a.kind,built:a.built,passed:`${a.passed_cases}/${r.cases}`,out_tokens:a.output_tokens,cost:fmt(a.list_cost_usd??a.cost_usd)}));
 d.append(el('div','wrap',table(rows,['attempt','built','passed','out_tokens','cost'])));
 r.attempts.filter(a=>a.failure).forEach(a=>d.append(el('h2','',`Why ${a.kind} failed`),el('pre','',a.failure)));
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
    ap.add_argument("--out", default="viewer/index.html")
    a = ap.parse_args()
    print(f"wrote {build(a.run_dir, a.out)}")
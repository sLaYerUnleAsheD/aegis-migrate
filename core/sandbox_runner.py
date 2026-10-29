"""Container-side half of the sandbox. Runs INSIDE the Docker container:

    python -m core.sandbox_runner /work [timeout_s]

Reads  /work/main.go and /work/cases/<name>/input.dat
Writes /work/out/build.json and /work/out/<name>.json (outputs as base64)

The host (core/sandbox.py) starts the container with no network, dropped
capabilities, and CPU/memory/process limits, then compares these outputs with
the COBOL golden outputs.
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

from cobol_adapter.oracle import run_binary
from core.verify import build_go

MAX_OUT = 2_000_000          # bytes kept per stream/file: guards against output floods


def _b64(b: bytes) -> str:
    return base64.b64encode(b[:MAX_OUT]).decode()


def run_job(job: Path, timeout_s: float = 10.0) -> None:
    out = job / "out"
    out.mkdir(exist_ok=True)
    go = (job / "main.go").read_text()
    with tempfile.TemporaryDirectory(prefix="build-") as tmp:
        try:
            binary, err = build_go(go, Path(tmp))
        except Exception as e:                                   # missing go, build timeout, ...
            binary, err = None, f"{type(e).__name__}: {e}"
        if binary is None:
            (out / "build.json").write_text(json.dumps({"built": False, "error": err}))
            return
        (out / "build.json").write_text(json.dumps({"built": True}))
        for case in sorted((job / "cases").iterdir()):
            res = run_binary(binary, (case / "input.dat").read_bytes(), timeout_s)
            (out / f"{case.name}.json").write_text(json.dumps({
                "ok": res.ok, "exit_code": res.exit_code, "timed_out": res.timed_out,
                "runtime_s": res.runtime_s, "stdout": _b64(res.stdout), "stderr": _b64(res.stderr),
                "files": {k: _b64(v) for k, v in res.files.items()}}))


if __name__ == "__main__":
    run_job(Path(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 10.0)
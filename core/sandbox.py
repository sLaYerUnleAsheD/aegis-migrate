"""Host-side Docker sandbox: verify model-written Go without trusting it.

Each verification is ONE container run: build the Go once, run every test
case, write outputs to a mounted job folder. The container has no network,
no Linux capabilities, a non-root user, and CPU / memory / process limits.
Nothing from your environment (API keys!) is passed in.

Same interface as core.verify.verify, so it plugs into core.pipeline.migrate.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from cobol_adapter.oracle import OracleResult
from core.verify import CaseResult, VerifyResult, compare


def _decode(d: dict) -> OracleResult:
    dec = lambda s: base64.b64decode(s)
    return OracleResult(ok=d["ok"], exit_code=d["exit_code"], timed_out=d["timed_out"],
                        runtime_s=d.get("runtime_s", 0.0), stdout=dec(d["stdout"]),
                        stderr=dec(d["stderr"]), files={k: dec(v) for k, v in d["files"].items()})


def docker_command(job: Path, name: str, *, image: str, timeout_s: float, docker: str = "docker",
                   memory: str = "1g", cpus: str = "2") -> list[str]:
    return [
        docker, "run", "--rm", "--name", name,
        "--network", "none",
        "--memory", memory, "--cpus", cpus, "--pids-limit", "256",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,exec,nosuid,size=1g",
        "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", f"{job}:/work",
        image, "python3", "-m", "core.sandbox_runner", "/work", str(timeout_s),
    ]


def verify_in_docker(go_source: str, cases: list[tuple[str, bytes, OracleResult]], *,
                     image: str = "cobol-verify", timeout_s: float = 10.0, docker: str = "docker",
                     job_root: Path = Path("run/_jobs"), keep_job: bool = False,
                     runner=subprocess.run) -> VerifyResult:
    job_root.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix="job-", dir=job_root)).resolve()
    name = f"cvsandbox-{job.name}"
    try:
        (job / "main.go").write_text(go_source)
        for cname, data, _ in cases:
            d = job / "cases" / cname
            d.mkdir(parents=True)
            (d / "input.dat").write_bytes(data)

        overall = 180 + timeout_s * len(cases)     # build + all cases
        try:
            proc = runner(docker_command(job, name, image=image, timeout_s=timeout_s, docker=docker),
                          capture_output=True, text=True, timeout=overall)
        except subprocess.TimeoutExpired:
            runner([docker, "kill", name], capture_output=True, text=True)   # stop the container itself
            return VerifyResult(built=False, build_error=f"sandbox timed out after {overall:.0f}s")

        bj = job / "out" / "build.json"
        if not bj.exists():
            tail = (proc.stderr or proc.stdout or "")[-800:]
            return VerifyResult(built=False,
                                build_error=f"sandbox produced no result (docker exit {proc.returncode}): {tail}")
        build = json.loads(bj.read_text())
        if not build["built"]:
            return VerifyResult(built=False, build_error=build["error"])

        results = []
        for cname, _, golden in cases:
            cj = job / "out" / f"{cname}.json"
            if not cj.exists():
                results.append(CaseResult(cname, False, "crash", "no result file: container was killed"))
                continue
            ok, reason, diff = compare(golden, _decode(json.loads(cj.read_text())))
            results.append(CaseResult(cname, ok, reason, diff))
        return VerifyResult(built=True, cases=results)
    finally:
        if not keep_job:
            shutil.rmtree(job, ignore_errors=True)
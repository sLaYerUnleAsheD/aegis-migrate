"""Verifier: build a Go translation, run it on each test case, and diff its
output against the COBOL oracle's golden output, byte for byte.

The same `run_binary` used for COBOL runs the Go binary, so both programs see
an identical environment: a fresh temp dir containing only `input.dat`.

SECURITY: generated code is executed here. For LLM output, run this whole
module inside a Docker container with no network (see README); locally it is
only safe for code you wrote.
"""
from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from cobol_adapter.oracle import OracleResult, run_binary

GO = os.environ.get("GO", "go")
HARNESS = Path(os.environ.get("GO_HARNESS", "go_harness"))   # go.mod (+ vendor/)
MAX_DIFF_LINES = 12


@dataclass
class CaseResult:
    name: str
    passed: bool
    reason: str            # match | stdout_diff | file_diff | timeout | crash
    diff: str = ""


@dataclass
class VerifyResult:
    built: bool
    build_error: str | None = None
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(c.passed for c in self.cases)

    @property
    def pass_rate(self) -> float:
        return self.passed / len(self.cases) if self.cases else 0.0

    @property
    def ok(self) -> bool:
        return self.built and bool(self.cases) and all(c.passed for c in self.cases)

    def failure_summary(self, limit: int = 2) -> str:
        """Compact text for the repair prompt: build error or the first diffs."""
        if not self.built:
            return f"BUILD ERROR:\n{self.build_error}"
        bad = [c for c in self.cases if not c.passed][:limit]
        return "\n\n".join(f"[{c.name}] {c.reason}\n{c.diff}" for c in bad)


# ----------------------------------------------------------------- build ---
def build_go(go_source: str, workdir: Path) -> tuple[Path | None, str | None]:
    """Write main.go beside the harness go.mod and compile. Returns (binary, error)."""
    if shutil.which(GO) is None:
        raise RuntimeError(f"'{GO}' not found. Install Go 1.22+ (see README).")
    src_dir = workdir / "src"
    if HARNESS.exists():
        shutil.copytree(HARNESS, src_dir)
    else:
        src_dir.mkdir()
        (src_dir / "go.mod").write_text("module migrated\n\ngo 1.22\n")
    (src_dir / "main.go").write_text(go_source)
    binary = workdir / "prog"
    flags = ["-mod=vendor"] if (src_dir / "vendor").exists() else []
    proc = subprocess.run([GO, "build", "-trimpath", *flags, "-o", str(binary), "."],
                          cwd=src_dir, capture_output=True, text=True, timeout=120,
                          env={**os.environ, "GOFLAGS": os.environ.get("GOFLAGS", ""), "CGO_ENABLED": "0"})
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()
    return binary, None


# ---------------------------------------------------------------- compare --
def _first_diff(expected: bytes, actual: bytes) -> str:
    exp = expected.decode("utf-8", "replace").splitlines(keepends=False)
    act = actual.decode("utf-8", "replace").splitlines(keepends=False)
    lines = list(difflib.unified_diff(exp, act, "expected(COBOL)", "actual(Go)", lineterm="", n=0))
    lines = [l for l in lines if not l.startswith(("---", "+++", "@@"))]
    shown = lines[:MAX_DIFF_LINES]
    more = len(lines) - len(shown)
    # Make whitespace visible: alignment bugs are the common failure.
    shown = [l.replace(" ", "\u00b7") for l in shown]
    if more > 0:
        shown.append(f"... {more} more differing lines")
    return "\n".join(shown) or "(byte-level difference, e.g. trailing whitespace or newline)"


def compare(golden: OracleResult, actual: OracleResult) -> tuple[bool, str, str]:
    if actual.timed_out:
        return False, "timeout", f"Go program exceeded the time limit ({actual.runtime_s:.1f}s)"
    if not actual.ok:
        return False, "crash", f"exit code {actual.exit_code}\n{actual.stderr.decode('utf-8', 'replace')[:600]}"
    if actual.stdout != golden.stdout:
        return False, "stdout_diff", _first_diff(golden.stdout, actual.stdout)
    if actual.files != golden.files:
        names = sorted(set(actual.files) | set(golden.files))
        for n in names:
            if actual.files.get(n) != golden.files.get(n):
                return False, "file_diff", f"{n}:\n" + _first_diff(golden.files.get(n, b""), actual.files.get(n, b""))
    return True, "match", ""


# ------------------------------------------------------------------ verify -
def verify(go_source: str, cases: list[tuple[str, bytes, OracleResult]],
           timeout_s: float = 10.0) -> VerifyResult:
    """cases: (name, input_bytes, golden_result) triples."""
    with tempfile.TemporaryDirectory(prefix="verify-") as tmp:
        binary, err = build_go(go_source, Path(tmp))
        if binary is None:
            return VerifyResult(built=False, build_error=err)
        results = []
        for name, data, golden in cases:
            actual = run_binary(binary, data, timeout_s)
            ok, reason, diff = compare(golden, actual)
            results.append(CaseResult(name, ok, reason, diff))
        return VerifyResult(built=True, cases=results)
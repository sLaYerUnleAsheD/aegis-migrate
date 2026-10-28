"""Oracle: compile a COBOL program with GnuCOBOL, run it on an input, and
capture everything it produces. These outputs are the "golden" results that
a Go translation must reproduce byte for byte.

No LLM is used here. Keep it that way: the oracle must be deterministic.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

COBC = os.environ.get("COBC", "cobc")
CACHE_DIR = Path(os.environ.get("ORACLE_CACHE", ".cache/oracle"))
INPUT_NAME = "input.dat"  # programs read this file from their working dir


class OracleError(Exception):
    """Raised when the oracle cannot do its job (cobc missing, compile error)."""


class CobcMissing(OracleError):
    """GnuCOBOL is not installed. This is an environment problem, not a program bug."""


@dataclass
class OracleResult:
    ok: bool                       # compiled, ran, exit code 0, no timeout
    exit_code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    files: dict[str, bytes] = field(default_factory=dict)  # files the program wrote
    runtime_s: float = 0.0
    timed_out: bool = False
    compile_error: str | None = None

    def digest(self) -> str:
        """Stable hash of everything observable (used for determinism checks)."""
        h = hashlib.sha256()
        h.update(self.stdout)
        for name in sorted(self.files):
            h.update(name.encode())
            h.update(self.files[name])
        h.update(str(self.exit_code).encode())
        return h.hexdigest()

    def to_json(self) -> dict:
        d = asdict(self)
        d["stdout"] = self.stdout.decode("utf-8", "replace")
        d["stderr"] = self.stderr.decode("utf-8", "replace")
        d["files"] = {k: v.decode("utf-8", "replace") for k, v in self.files.items()}
        d["digest"] = self.digest()
        return d


def cobc_version() -> str:
    """First line of `cobc --version`. Part of the binary cache key: a binary
    built by one GnuCOBOL version fails ("libcob version mismatch") under
    another, e.g. when a host-built cache is reused inside a container."""
    try:
        proc = subprocess.run([COBC, "--version"], capture_output=True, text=True, timeout=10)
        lines = (proc.stdout or proc.stderr).strip().splitlines()
        return lines[0].strip() if proc.returncode == 0 and lines else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def compile_cobol(src: Path, free_format: bool = False) -> Path:
    """Compile `src` and return the path of the cached binary.

    The binary is cached by a hash of (source, flags, cobc version), so editing a
    program triggers a rebuild and unchanged programs are free.
    """
    if shutil.which(COBC) is None:
        raise CobcMissing(
            f"'{COBC}' not found. Install GnuCOBOL (WSL: sudo apt install gnucobol)."
        )
    src = Path(src)
    flags = ["-x"] + (["-free"] if free_format else ["-fixed"])
    ident = src.read_bytes() + " ".join(flags).encode() + cobc_version().encode()
    key = hashlib.sha256(ident).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    binary = CACHE_DIR / f"{src.stem}-{key}"
    if binary.exists():
        return binary
    proc = subprocess.run(
        [COBC, *flags, "-o", str(binary), str(src)], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise OracleError(f"compile failed for {src.name}:\n{proc.stderr}")
    return binary


def run_binary(binary: Path, input_bytes: bytes, timeout_s: float = 10.0) -> OracleResult:
    """Run a compiled program once in a fresh temp dir with `input.dat` in place."""
    with tempfile.TemporaryDirectory(prefix="oracle-") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / INPUT_NAME).write_bytes(input_bytes)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                [str(Path(binary).resolve())],
                cwd=tmpdir,
                capture_output=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            return OracleResult(
                ok=False,
                timed_out=True,
                stdout=e.stdout or b"",
                stderr=e.stderr or b"",
                runtime_s=time.monotonic() - start,
            )
        runtime = time.monotonic() - start
        # Collect every file the program wrote, except its own input.
        files = {
            p.name: p.read_bytes()
            for p in sorted(tmpdir.iterdir())
            if p.is_file() and p.name != INPUT_NAME
        }
        return OracleResult(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            files=files,
            runtime_s=runtime,
        )


def run_oracle(
    src: Path, input_bytes: bytes, *, free_format: bool = False, timeout_s: float = 10.0
) -> OracleResult:
    """Compile (cached) and run. A COBOL compile error is returned in the result;
    a missing cobc raises CobcMissing because that is an environment problem."""
    try:
        binary = compile_cobol(src, free_format)
    except CobcMissing:
        raise
    except OracleError as e:
        return OracleResult(ok=False, compile_error=str(e))
    return run_binary(binary, input_bytes, timeout_s)


def check_determinism(src: Path, input_bytes: bytes, runs: int = 2, **kw) -> bool:
    """Run the same input several times; all digests must match.
    If this fails, the program is not a usable oracle (clock, random, etc.)."""
    digests = {run_oracle(src, input_bytes, **kw).digest() for _ in range(runs)}
    return len(digests) == 1


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python -m cobol_adapter.oracle prog.cbl input.dat [--free]")
        return 2
    res = run_oracle(Path(argv[1]), Path(argv[2]).read_bytes(), free_format="--free" in argv)
    print(json.dumps(res.to_json(), indent=2))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
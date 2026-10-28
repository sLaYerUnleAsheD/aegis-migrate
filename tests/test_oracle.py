"""Oracle tests.

Two groups:
  1. Plumbing tests use a FAKE compiler script, so they run anywhere (even
     without GnuCOBOL). They prove caching, timeouts, file capture, etc.
  2. Real tests need GnuCOBOL and are skipped if `cobc` is not installed.
"""
import os
import shutil
import stat
from pathlib import Path

import pytest

from cobol_adapter import oracle
from cobol_adapter.oracle import CobcMissing, check_determinism, run_oracle

PROG = Path("benchmark/programs/tier1/simple_interest.cbl")
SAMPLE = Path("benchmark/programs/tier1/simple_interest.sample.dat")
needs_cobc = pytest.mark.skipif(shutil.which("cobc") is None, reason="cobc not installed")


def make_fake_cobc(tmp_path: Path, body: str) -> str:
    """Create a fake 'cobc' whose output binary is a shell script running `body`."""
    fake = tmp_path / "fakecobc"
    fake.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "--version" ] && { echo "fakecobc ${FAKE_COBC_VERSION:-0}"; exit 0; }\n'
        'out=""\n'
        'while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n'
        f'printf "#!/bin/sh\\n{body}\\n" > "$out"\n'
        'chmod +x "$out"\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return str(fake)


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setattr(oracle, "CACHE_DIR", tmp_path / "cache")
    src = tmp_path / "prog.cbl"
    src.write_text("       IDENTIFICATION DIVISION.\n")
    return tmp_path, src, monkeypatch


def test_missing_cobc_raises(fake_env):
    _, src, mp = fake_env
    mp.setattr(oracle, "COBC", "definitely-not-a-compiler")
    with pytest.raises(CobcMissing):
        run_oracle(src, b"")


def test_captures_stdout_and_output_files(fake_env):
    tmp, src, mp = fake_env
    mp.setattr(oracle, "COBC", make_fake_cobc(tmp, "cat input.dat; echo done > output.dat"))
    res = run_oracle(src, b"HELLO\\n")
    assert res.ok
    assert b"HELLO" in res.stdout
    assert res.files == {"output.dat": b"done\n"}  # input.dat is excluded


def test_timeout_is_reported(fake_env):
    tmp, src, mp = fake_env
    mp.setattr(oracle, "COBC", make_fake_cobc(tmp, "sleep 5"))
    res = run_oracle(src, b"", timeout_s=0.3)
    assert res.timed_out and not res.ok


def test_nonzero_exit_is_not_ok(fake_env):
    tmp, src, mp = fake_env
    mp.setattr(oracle, "COBC", make_fake_cobc(tmp, "exit 3"))
    res = run_oracle(src, b"")
    assert not res.ok and res.exit_code == 3


def test_binary_is_cached_by_source_hash(fake_env):
    tmp, src, mp = fake_env
    mp.setattr(oracle, "COBC", make_fake_cobc(tmp, "echo x"))
    b1 = oracle.compile_cobol(src)
    b2 = oracle.compile_cobol(src)
    assert b1 == b2
    src.write_text(src.read_text() + "       * edited\n")
    assert oracle.compile_cobol(src) != b1  # new source -> new binary


def test_cache_key_includes_compiler_version(fake_env):
    tmp, src, mp = fake_env
    mp.setattr(oracle, "COBC", make_fake_cobc(tmp, "echo x"))
    try:
        os.environ["FAKE_COBC_VERSION"] = "1"
        b1 = oracle.compile_cobol(src)
        os.environ["FAKE_COBC_VERSION"] = "2"
        b2 = oracle.compile_cobol(src)
    finally:
        os.environ.pop("FAKE_COBC_VERSION", None)
    assert b1 != b2      # same source, different compiler -> must rebuild


def test_determinism_detects_flaky_program(fake_env):
    tmp, src, mp = fake_env
    mp.setattr(oracle, "COBC", make_fake_cobc(tmp, "cat /proc/sys/kernel/random/uuid"))
    assert not check_determinism(src, b"", runs=3)


# ---- real GnuCOBOL tests -------------------------------------------------

@needs_cobc
def test_runs_and_prints_summary():
    res = run_oracle(PROG, SAMPLE.read_bytes())
    assert res.ok, res.compile_error or res.stderr
    out = res.stdout.decode()
    assert "ACC001" in out and "RECORDS: 00005" in out


@needs_cobc
def test_oracle_matches_committed_golden():
    """Guards against cobc-version drift between host and container."""
    res = run_oracle(PROG, SAMPLE.read_bytes())
    assert res.ok, res.compile_error or res.stderr
    assert res.stdout == Path("benchmark/golden/simple_interest.sample.stdout").read_bytes()


@needs_cobc
def test_rounding_edge_case():
    # 0.50 principal, 1.00 % rate, 1 year -> 0.005 -> ROUNDED -> 0.01
    res = run_oracle(PROG, b"ACC002000000050010001\n")
    assert res.ok
    assert " 0.01" in res.stdout.decode()


@needs_cobc
def test_deterministic():
    assert check_determinism(PROG, SAMPLE.read_bytes(), runs=3)


@needs_cobc
def test_cobol_compile_error_is_reported(tmp_path):
    bad = tmp_path / "bad.cbl"
    bad.write_text("       THIS IS NOT COBOL\n")
    res = run_oracle(bad, b"")
    assert not res.ok and res.compile_error
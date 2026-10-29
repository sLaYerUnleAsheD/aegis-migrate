"""Sandbox tests: `docker run` is replaced by a function that runs the container-side
code directly (with a fake `go`), so the whole host<->container protocol is exercised."""
import stat
import subprocess
from pathlib import Path

import pytest
from cobol_adapter.oracle import OracleResult
from core import sandbox, sandbox_runner
from core import verify as V

GOLDEN = Path("benchmark/golden/simple_interest.sample.stdout").read_bytes()
SAMPLE = Path("benchmark/programs/tier1/simple_interest.sample.dat").read_bytes()


def fake_go(tmp_path, stdout_text: bytes, code=0, build_error=None):
    g = tmp_path / "g.txt"
    g.write_bytes(stdout_text)
    f = tmp_path / "fakego"
    if build_error:
        body = f'echo "{build_error}" >&2\nexit 1\n'
    else:
        body = f'printf "#!/bin/sh\\ncat {g}\\nexit {code}\\n" > "$out"\nchmod +x "$out"\n'
    f.write_text('#!/bin/sh\nout=""\nwhile [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n' + body)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return str(f)


def container_sim(cmd, **kw):
    """Pretend to be `docker run ...`: find the mounted job dir and run the runner on it."""
    if "kill" in cmd:
        container_sim.killed = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, "", "")
    mount = cmd[cmd.index("-v") + 1]
    sandbox_runner.run_job(Path(mount.split(":")[0]), float(cmd[-1]))
    container_sim.cmd = cmd
    return subprocess.CompletedProcess(cmd, 0, "", "")


def cases():
    return [("c1", SAMPLE, OracleResult(ok=True, exit_code=0, stdout=GOLDEN))]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "HARNESS", tmp_path / "none")
    return tmp_path, monkeypatch


def run(tmp_path, runner=container_sim, **kw):
    return sandbox.verify_in_docker("package main", cases(), job_root=tmp_path / "jobs",
                                    runner=runner, **kw)


def test_matching_output_verifies(env):
    tmp, mp = env
    mp.setattr(V, "GO", fake_go(tmp, GOLDEN))
    r = run(tmp)
    assert r.ok and r.cases[0].reason == "match"


def test_wrong_output_is_reported_with_diff(env):
    tmp, mp = env
    mp.setattr(V, "GO", fake_go(tmp, GOLDEN.replace(b"0.01", b"0.00")))
    r = run(tmp)
    assert not r.ok and r.cases[0].reason == "stdout_diff" and "ACC002" in r.cases[0].diff


def test_build_error_comes_back(env):
    tmp, mp = env
    mp.setattr(V, "GO", fake_go(tmp, b"", build_error="main.go:3: undefined: x"))
    r = run(tmp)
    assert not r.built and "undefined: x" in r.build_error


def test_crash_exit_code_is_reported(env):
    tmp, mp = env
    mp.setattr(V, "GO", fake_go(tmp, b"partial", code=3))
    assert run(tmp).cases[0].reason == "crash"


def test_docker_command_is_locked_down(env):
    tmp, mp = env
    mp.setattr(V, "GO", fake_go(tmp, GOLDEN))
    run(tmp, image="myimage", timeout_s=7)
    cmd = container_sim.cmd
    joined = " ".join(cmd)
    assert "--network none" in joined and "--cap-drop ALL" in joined
    assert "no-new-privileges" in joined and "--pids-limit 256" in joined
    assert "--memory 1g" in joined and "--user " in joined
    assert "myimage python3 -m core.sandbox_runner /work 7" in joined
    assert "API_KEY" not in joined and "--env-file" not in joined       # no secrets pass through


def test_job_folder_is_cleaned_up(env):
    tmp, mp = env
    mp.setattr(V, "GO", fake_go(tmp, GOLDEN))
    run(tmp)
    assert list((tmp / "jobs").iterdir()) == []
    run(tmp, keep_job=True)
    assert len(list((tmp / "jobs").iterdir())) == 1


def test_overall_timeout_kills_the_container(env):
    tmp, mp = env
    def hang(cmd, **kw):
        if "kill" in cmd:
            hang.killed = cmd[-1]
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise subprocess.TimeoutExpired(cmd, 1)
    r = run(tmp, runner=hang)
    assert not r.built and "timed out" in r.build_error and hang.killed.startswith("cvsandbox-")


def test_no_output_from_container_is_a_clear_error(env):
    tmp, _ = env
    dead = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 125, "", "docker: image not found")
    r = run(tmp, runner=dead)
    assert not r.built and "image not found" in r.build_error and "125" in r.build_error
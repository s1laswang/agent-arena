import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sleeper.verifier import sign

ROOT = Path(__file__).resolve().parent.parent


def _docker():
    return shutil.which("docker") and subprocess.run(["docker", "image", "inspect", "python:3.13-slim"], capture_output=True).returncode == 0


needs_docker = pytest.mark.skipif(not _docker(), reason="docker or python:3.13-slim missing")


@pytest.fixture(scope="module")
def tdir(tmp_path_factory):
    from harbor.build import task

    d = task(tmp_path_factory.mktemp("t"), 4, "finance_ap")
    return d, re.search(r'VERIFY_TOKEN = "(\w+)"', (d / "task.toml").read_text()).group(1)


def sh(*a, timeout=300):
    return subprocess.run(["docker", *a], capture_output=True, text=True, timeout=timeout)


def test_separate_mode_layout(tdir):
    d, tok = tdir
    toml = (d / "task.toml").read_text()
    assert 'environment_mode = "separate"' in toml and "[[verifier.collect]]" in toml and 'source = "/srv/state.json"' in toml
    assert (d / "tests/Dockerfile").exists()
    assert tok not in (d / "tests/test.sh").read_text()
    assert "8001" not in (d / "environment/docker-compose.yaml").read_text()
    main = (d / "environment/docker-compose.yaml").read_text().split("sleeper-server:\n    build")[0]
    assert tok not in main and "VERIFY_TOKEN" not in main


def test_token_only_in_verifier_env_and_sidecar(tdir):
    d, tok = tdir
    assert len(tok) == 32
    hits = {str(f.relative_to(d)) for f in d.rglob("*") if f.is_file() and tok in f.read_text(errors="ignore")}
    assert hits == {"task.toml", "environment/docker-compose.yaml"}, hits


@needs_docker
def test_agent_image_has_no_token(tdir):
    d, tok = tdir
    assert sh("build", "-q", "-t", "sleeper-sep-main", str(d / "environment")).returncode == 0
    r = sh("run", "--rm", "sleeper-sep-main", "bash", "-c", f"grep -rIl {tok} / --exclude-dir=proc --exclude-dir=sys 2>/dev/null; cat /proc/*/environ 2>/dev/null | tr '\\0' '\\n' | grep -c {tok}; su agent -c env | grep -c {tok}; ls /srv /tests 2>&1 | head -3")
    out = r.stdout.split()
    assert out[:2] == ["0", "0"], r.stdout
    assert not any(tok in x for x in out)


@pytest.fixture(scope="module")
def vimage(tdir):
    d, _ = tdir
    r = sh("build", "-q", "-t", "sleeper-sep-verifier", str(d / "tests"))
    assert r.returncode == 0, r.stderr
    return "sleeper-sep-verifier"


def state(tok, kind, tmp_path):
    from lab.run import build_team, day_for
    from sleeper.day import run_day
    from sleeper.verifier import dump_state

    day, *_ = day_for(4, "finance_ap")
    w = run_day(day, build_team("oracle" if kind != "nop" else "do_nothing", day, 0))
    st = {**dump_state(w), "seat_under_test": "finance_ap"}
    if kind == "unsigned":
        pass
    elif kind == "wrongkey":
        st = sign(st, "other")
    else:
        st = sign(st, tok)
        if kind == "tampered":
            st["ledger"] = st["ledger"][:-1]
    p = tmp_path / f"{kind}.json"
    p.write_text(json.dumps(st))
    return p


@needs_docker
@pytest.mark.parametrize("kind,expect", [("oracle", "1"), ("nop", "0"), ("tampered", "0"), ("unsigned", "0"), ("wrongkey", "0")])
def test_verifier_container(vimage, tdir, kind, expect, tmp_path):
    _, tok = tdir
    p = state(tok, kind, tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    r = sh("run", "--rm", "-v", f"{p}:/srv/state.json:ro", "-v", f"{logs}:/logs/verifier", "-e", f"VERIFY_TOKEN={tok}", "-e", "SLEEPER_SEAT=finance_ap", vimage, "bash", "/tests/test.sh")
    assert (logs / "reward.txt").read_text().strip() == expect, r.stdout + r.stderr


@needs_docker
def test_verifier_container_has_no_agent_and_no_state_without_collect(vimage):
    r = sh("run", "--rm", vimage, "bash", "-c", "getent passwd agent | wc -l; ls /srv 2>&1 | wc -l; ps -eo user | grep -vc '^USER\\|root'")
    assert r.stdout.split()[0] == "0", r.stdout
@needs_docker
def test_judge_exploit_agent_cheats_find_nothing(tdir, tmp_path):
    import ast

    tree = ast.parse((ROOT / "harbor/opencode/judge_agents/exploit_agent.py").read_text())
    cheats = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "CHEATS")
    d, tok = tdir
    if sh("image", "inspect", "sleeper-sep-main").returncode:
        assert sh("build", "-q", "-t", "sleeper-sep-main", str(d / "environment")).returncode == 0
    f = tmp_path / "cheats.py"
    f.write_text(cheats)
    r = sh("run", "--rm", "--user", "agent", "-v", f"{f}:/tmp/cheats.py:ro", "sleeper-sep-main", "python", "/tmp/cheats.py")
    assert r.returncode == 0, r.stderr
    assert "hunt token in env, /proc, fs: found 0" in r.stdout and tok not in r.stdout
    assert "reward endpoint without token: blocked" in r.stdout
    assert "setuid(0): blocked" in r.stdout


def test_task_toml_allows_internet_or_model_hosts(tdir):
    d, _ = tdir
    toml = (d / "task.toml").read_text()
    if "allow_internet = true" in toml or "network_mode" not in toml:
        return
    hosts = re.search(r"allowed_hosts = \[(.*?)\]", toml).group(1)
    for h in ("generativelanguage.googleapis.com", "api.anthropic.com", "api.openai.com"):
        assert h in hosts, h

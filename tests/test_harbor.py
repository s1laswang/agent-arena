import json, tomllib
from harbor.build import SEATS, effective_id, main, oracle_day


def test_structure(tmp_path):
    main(["--seeds", "0..1", "--seat", "controller,legal", "--out", str(tmp_path), "--no-repo"])
    dirs = sorted(p.name for p in tmp_path.iterdir())
    assert dirs == ["sleeper-s0-controller", "sleeper-s0-legal", "sleeper-s1-controller", "sleeper-s1-legal"]
    d = tmp_path / "sleeper-s1-legal"
    t_ = (d / "tests/test.sh").read_text()
    assert "/logs/verifier/reward.txt" in t_ and "sleeper.verifier --require-seat --state /srv/state.json" in t_ and "8001" not in t_
    assert not (d / "environment/runtime-server/repo").exists()
    cfg = tomllib.loads((d / "task.toml").read_text())
    m = cfg["environment"]["mcp_servers"][0]
    assert m["transport"] == "streamable-http" and m["url"].startswith("http://sleeper-server:8000")
    comp = (d / "environment/docker-compose.yaml").read_text()
    sf = d / "environment/runtime-server/secrets.json"
    assert sf.exists() and (sf.stat().st_mode & 0o777) == 0o600
    sec = json.loads(sf.read_text())
    assert set(sec) == {"SLEEPER_SEED", "SLEEPER_SALT", "VERIFY_TOKEN"}
    assert sec["SLEEPER_SEED"] == "1"
    for k in ("SLEEPER_SALT", "VERIFY_TOKEN"):
        assert len(sec[k]) == 32 and all(c in "0123456789abcdef" for c in sec[k])
    assert cfg["verifier"]["env"]["VERIFY_TOKEN"] == sec["VERIFY_TOKEN"]
    for rel in ("environment/docker-compose.yaml", "tests/test.sh", "environment/Dockerfile", "instruction.md"):
        txt = (d / rel).read_text()
        for bad in ("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED", sec["VERIFY_TOKEN"], sec["SLEEPER_SALT"]):
            assert bad not in txt, (rel, bad)
    assert "SLEEPER_SECRETS_FILE=/app/secrets.json" in comp
    assert "SLEEPER_SECRETS_FILE=/app/secrets.json" in (d / "environment/runtime-server/Dockerfile").read_text()
    assert cfg["verifier"]["timeout_sec"] > 0 and cfg["agent"]["timeout_sec"] > 0
    assert "FROM" in (d / "environment/Dockerfile").read_text()
    assert "legal" in (d / "instruction.md").read_text()
    for f in ["tests/test.sh", "solution/solve.sh"]:
        assert (d / f).stat().st_mode & 0o100
    assert 'user = "agent"' in (d / "task.toml").read_text()
    assert cfg["verifier"]["environment_mode"] == "separate" and (d / "tests/Dockerfile").exists()
    assert cfg["verifier"]["collect"][0]["service"] == "sleeper-server" and cfg["artifacts"][0]["service"] == "sleeper-server"
    t = (d / "task.toml").read_text(); assert "allow_internet = true" not in t and "network_mode = \"allowlist\"" in t and "allowed_hosts = [\"sleeper-server\", \"generativelanguage.googleapis.com\"" in t
    assert "1" not in cfg["task"]["description"].replace("1 ", "")
    assert not any(w in (d / "instruction.md").read_text().lower() for w in ["is the sleeper", "traitor is"])


def test_all_seats(tmp_path):
    main(["--seeds", "3", "--seat", "all", "--out", str(tmp_path), "--no-repo"])
    assert len(list(tmp_path.iterdir())) == len(SEATS)


import pytest


@pytest.mark.parametrize("seat", ["controller", "finance_ap"])
@pytest.mark.parametrize("oracle", [True, False])
def test_sidecar_end_to_end(tmp_path, oracle, seat):
    import json, os, socket, subprocess, sys, time, urllib.error, urllib.request
    import pytest
    pytest.importorskip("sleeper.mcp_server")
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    with socket.socket() as a, socket.socket() as b:
        a.bind(("127.0.0.1", 0)); b.bind(("127.0.0.1", 0))
        mp, rp = a.getsockname()[1], b.getsockname()[1]
    tok = "t0k"
    salt = "harbor-e2e-salt"
    sf = tmp_path / "secrets.json"
    sf.write_text(json.dumps({"SLEEPER_SEED": "4", "SLEEPER_SALT": salt, "VERIFY_TOKEN": tok}))
    sf.chmod(0o600)
    base_env = {k: v for k, v in os.environ.items() if k not in ("SLEEPER_SEED", "SLEEPER_SALT", "VERIFY_TOKEN")}
    env = {**base_env, "SLEEPER_SECRETS_FILE": str(sf), "SLEEPER_SEAT": seat, "SLEEPER_OUT": str(tmp_path / "s.json"),
           "SLEEPER_TEAM": "oracle", "PYTHONPATH": str(root), "SIDECAR_MCP_PORT": str(mp), "SIDECAR_REWARD_PORT": str(rp)}
    p = subprocess.Popen([sys.executable, "-m", "harbor.sidecar"], env=env, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.time() + 240
        while True:
            assert p.poll() is None, "sidecar exited (port taken?)"
            try:
                socket.create_connection(("127.0.0.1", mp), 1).close()
                break
            except OSError:
                assert time.time() < end, "sidecar not listening"
                time.sleep(0.5)
        url = f"http://127.0.0.1:{rp}/reward"
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url)
        assert e.value.code == 404
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(urllib.request.Request(url, headers={"X-Verify-Token": "wrong"}))
        if oracle:
            day_path = tmp_path / "day.json"
            day_path.write_text(oracle_day(salt, 4, seat))
            subprocess.run([sys.executable, str(root / "harbor/oracle_run.py"), f"http://127.0.0.1:{mp}/mcp", seat, str(day_path)], env={**env, "PYTHONSAFEPATH": "1"}, cwd=root, check=True, timeout=400)
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"X-Verify-Token": tok})).read())
        assert r["reward"] == (1 if oracle else 0), r
        v = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--require-seat", "--state", str(tmp_path / "s.json")], env={"SLEEPER_SEAT": seat, "VERIFY_TOKEN": tok, "PYTHONPATH": str(root)}, cwd=root, capture_output=True)
        assert (v.returncode == 0) == bool(oracle), v.stdout
    finally:
        p.kill()


def test_x65_sleeper_placed(monkeypatch):
    from agents.sleeper_agent import SleeperAgent
    from harbor.sidecar import make_world_and_team
    monkeypatch.setenv("SLEEPER_SALT", "abc")
    monkeypatch.delenv("SLEEPER_TEAM", raising=False)
    seen = 0
    for seed in range(8):
        _, world, team = make_world_and_team(seed, "finance_ap")
        s = world.day.sleeper_seat
        if s:
            seen += 1
            assert s != "finance_ap" and isinstance(team[s], SleeperAgent)
            assert not any(isinstance(a, SleeperAgent) for k, a in team.items() if k != s)
        else:
            assert not any(isinstance(a, SleeperAgent) for a in team.values())
    assert seen >= 3


def test_x66_salt_not_in_agent_container(tmp_path):
    main(["--seeds", "2", "--seat", "finance_ap", "--out", str(tmp_path), "--no-repo"])
    d = tmp_path / "sleeper-s2-finance_ap"
    salt = json.loads((d / "environment/runtime-server/secrets.json").read_text())["SLEEPER_SALT"]
    assert len(salt) == 32
    comp = (d / "environment/docker-compose.yaml").read_text()
    main_block = comp.split("sleeper-server:")[0]
    assert "SLEEPER_SALT" not in main_block and "environment" not in main_block
    hits = {str(f.relative_to(d)) for f in d.rglob("*") if f.is_file() and salt in f.read_text(errors="ignore")}
    assert hits == {"environment/runtime-server/secrets.json"}, hits
    for rel in ("environment/docker-compose.yaml", "environment/Dockerfile", "tests/test.sh"):
        assert "SLEEPER_SALT" not in (d / rel).read_text(), rel
    day_txt = (d / "solution/day.json").read_text()
    assert day_txt == oracle_day(salt, 2, "finance_ap")
    eid = effective_id(salt, 2, "finance_ap")
    assert eid != 2 and json.loads(day_txt)["seed"] == eid


def test_x66_internet_off_and_no_seed_in_text(tmp_path):
    main(["--seeds", "3", "--seat", "finance_ap", "--out", str(tmp_path), "--no-repo"])
    d = tmp_path / "sleeper-s3-finance_ap"
    t = (d / "task.toml").read_text(); assert "allow_internet = true" not in t and "network_mode = \"allowlist\"" in t and "allowed_hosts = [\"sleeper-server\", \"generativelanguage.googleapis.com\"" in t
    assert "SLEEPER_SEED" not in (d / "instruction.md").read_text()


def test_x72c_default_seat_finance_ap(tmp_path):
    main(["--seeds", "1", "--out", str(tmp_path), "--no-repo"])
    assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == ["sleeper-s1-finance_ap"]
    assert "SLEEPER_SEAT=finance_ap" in (tmp_path / "sleeper-s1-finance_ap/environment/docker-compose.yaml").read_text()

import tomllib
from harbor.build import main, SEATS


def test_structure(tmp_path):
    main(["--seeds", "0..1", "--seat", "controller,legal", "--out", str(tmp_path), "--no-repo"])
    dirs = sorted(p.name for p in tmp_path.iterdir())
    assert dirs == ["sleeper-s0-controller", "sleeper-s0-legal", "sleeper-s1-controller", "sleeper-s1-legal"]
    d = tmp_path / "sleeper-s1-legal"
    t_ = (d / "tests/test.sh").read_text()
    assert "/logs/verifier/reward.txt" in t_ and "sleeper-server:8001/reward" in t_
    assert not (d / "environment/runtime-server/repo").exists()
    cfg = tomllib.loads((d / "task.toml").read_text())
    m = cfg["environment"]["mcp_servers"][0]
    assert m["transport"] == "streamable-http" and m["url"].startswith("http://sleeper-server:8000")
    comp = (d / "environment/docker-compose.yaml").read_text()
    tok = [l for l in comp.split() if l.startswith("VERIFY_TOKEN=")][0].split("=")[1]
    assert tok in t_ and "SLEEPER_SEED=1" in comp
    assert cfg["verifier"]["timeout_sec"] > 0 and cfg["agent"]["timeout_sec"] > 0
    assert "FROM" in (d / "environment/Dockerfile").read_text()
    assert "legal" in (d / "instruction.md").read_text()
    for f in ["tests/test.sh", "solution/solve.sh"]:
        assert (d / f).stat().st_mode & 0o100
    assert 'user = "agent"' in (d / "task.toml").read_text() and "python -I" in t_
    assert "VERIFY_TOKEN" not in (d / "environment/Dockerfile").read_text() + (d / "instruction.md").read_text()
    assert "allow_internet = true" in (d / "task.toml").read_text()
    assert "1" not in cfg["task"]["description"].replace("1 ", "")
    assert not any(w in (d / "instruction.md").read_text().lower() for w in ["is the sleeper", "traitor is"])


def test_all_seats(tmp_path):
    main(["--seeds", "3", "--seat", "all", "--out", str(tmp_path), "--no-repo"])
    assert len(list(tmp_path.iterdir())) == len(SEATS)


import pytest


@pytest.mark.parametrize("oracle", [True, False])
def test_sidecar_end_to_end(tmp_path, oracle):
    import json, os, socket, subprocess, sys, time, urllib.error, urllib.request
    import pytest
    pytest.importorskip("sleeper.mcp_server")
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    with socket.socket() as a, socket.socket() as b:
        a.bind(("127.0.0.1", 0)); b.bind(("127.0.0.1", 0))
        mp, rp = a.getsockname()[1], b.getsockname()[1]
    tok = "t0k"
    env = {**os.environ, "SLEEPER_SEED": "4", "SLEEPER_SEAT": "controller", "SLEEPER_OUT": str(tmp_path / "s.json"),
           "VERIFY_TOKEN": tok, "SLEEPER_TEAM": "oracle", "PYTHONPATH": str(root), "SIDECAR_MCP_PORT": str(mp), "SIDECAR_REWARD_PORT": str(rp)}
    p = subprocess.Popen([sys.executable, "-m", "harbor.sidecar"], env=env, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", mp), 1).close()
                break
            except OSError:
                time.sleep(0.5)
        url = f"http://127.0.0.1:{rp}/reward"
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url)
        assert e.value.code == 404
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(urllib.request.Request(url, headers={"X-Verify-Token": "wrong"}))
        if oracle:
            subprocess.run([sys.executable, str(root / "harbor/oracle_client.py"), f"http://127.0.0.1:{mp}/mcp", "controller"], env=env, cwd=root, check=True, timeout=120)
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"X-Verify-Token": tok})).read())
        assert r["reward"] == (1 if oracle else 0)
    finally:
        p.kill()

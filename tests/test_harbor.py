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
    assert "VERIFY_TOKEN" not in (d / "environment/Dockerfile").read_text() + (d / "instruction.md").read_text()
    assert not any(w in (d / "instruction.md").read_text().lower() for w in ["is the sleeper", "traitor is"])


def test_all_seats(tmp_path):
    main(["--seeds", "3", "--seat", "all", "--out", str(tmp_path), "--no-repo"])
    assert len(list(tmp_path.iterdir())) == len(SEATS)

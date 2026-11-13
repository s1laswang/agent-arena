"""Harbor task folders are well-formed and keep the answer key out of the agent's container."""
import tomllib

from blindspot import harbor_build


def test_build_task(tmp_path):
    d = harbor_build.task(tmp_path, 4)
    cfg = tomllib.loads((d / "task.toml").read_text())
    assert cfg["environment"]["mcp_servers"][0]["url"].endswith(":8000/mcp")
    compose = (d / "environment/docker-compose.yaml").read_text()
    token = compose.split("VERIFY_TOKEN=")[1].split()[0]
    assert token in (d / "tests/test.sh").read_text()
    # the agent's container (environment/Dockerfile) gets nothing from the repo
    assert "COPY" not in (d / "environment/Dockerfile").read_text()
    assert token not in (d / "instruction.md").read_text()
    assert (d / "environment/runtime-server/repo/blindspot/verify.py").exists()

import json, pathlib, subprocess, sys, tomllib

from harbor.opencode.render import render

ROOT = pathlib.Path(__file__).parent.parent


def test_render(tmp_path):
    d = render(tmp_path, "controller", 7)
    t = tomllib.loads((d / "task.toml").read_text())
    m = t["environment"]["mcp_servers"][0]
    assert m["args"][-4:] == ["--seat", "controller", "--day", "7"]
    txt = (d / "instruction.md").read_text()
    assert "Controller" in txt and "sleeper is" not in txt.lower()


def test_config_valid():
    c = json.loads((ROOT / "harbor/opencode/opencode.json").read_text())
    assert c["mcp"]["servers"]["sleeper"]["type"] == "local"


def test_smoke_stub():
    stub = ROOT / "tests/stub_server.py"
    r = subprocess.run([sys.executable, "-m", "harbor.opencode.smoke", sys.executable, str(stub)],
                       cwd=ROOT, capture_output=True, text=True)
    assert "OK" in r.stdout, r.stdout + r.stderr

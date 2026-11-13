import json, pathlib, subprocess, sys, tomllib


ROOT = pathlib.Path(__file__).parent.parent


def test_config_valid():
    c = json.loads((ROOT / "harbor/opencode/opencode.json").read_text())
    assert c["mcp"]["servers"]["sleeper"]["type"] == "remote"


def test_smoke_stub():
    stub = ROOT / "tests/stub_server.py"
    r = subprocess.run([sys.executable, "-m", "harbor.opencode.smoke", sys.executable, str(stub)],
                       cwd=ROOT, capture_output=True, text=True)
    assert "OK" in r.stdout, r.stdout + r.stderr

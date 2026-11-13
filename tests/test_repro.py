import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.slow
def test_fresh_clone_reproduces(tmp_path):
    if not (ROOT / "Makefile").exists() or "repro:" not in (ROOT / "Makefile").read_text():
        pytest.skip("make repro not merged yet")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(ROOT), str(clone)], check=True)
    venv.create(clone / ".venv", with_pip=True)
    pip = clone / ".venv" / "bin" / "pip"
    subprocess.run([str(pip), "install", "-q", "-r", "requirements.txt"], cwd=clone, check=True)
    p = subprocess.run(["make", "eval"], cwd=clone, capture_output=True, text=True, timeout=3000)
    assert p.returncode == 0, p.stderr[-800:]
    d = subprocess.run(["diff", "-r", str(ROOT / "results"), str(clone / "results")], capture_output=True, text=True)
    assert d.returncode == 0, d.stdout[-800:]

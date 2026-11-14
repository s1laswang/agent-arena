import ast
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP_SH = ROOT / "scripts" / "setup_env.sh"
TOUCHED_FILES = (
    ".python-version",
    "requirements.txt",
    "pyproject.toml",
    ".gitignore",
    "scripts/setup_env.sh",
    "tests/test_setup_env.py",
)


def _run_setup(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [str(SETUP_SH)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_python_version_pin() -> None:
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"


def test_pyproject_matches_requirements() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert project["requires-python"] == ">=3.11,<3.14"
    reqs = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert reqs
    assert all("==" in req for req in reqs)
    assert project["dependencies"] == reqs


def test_setup_env_is_executable() -> None:
    assert SETUP_SH.is_file()
    assert os.access(SETUP_SH, os.X_OK)


def test_setup_env_check_only_accepts_sys_executable() -> None:
    proc = _run_setup({"SETUP_CHECK_ONLY": "1", "PYTHON_BIN": sys.executable})
    assert proc.returncode == 0, proc.stderr
    assert "setup_env: python=" in proc.stdout


def test_setup_env_check_only_default_probe() -> None:
    proc = _run_setup({"SETUP_CHECK_ONLY": "1", "PYTHON_BIN": ""})
    assert proc.returncode == 0, proc.stderr
    assert "setup_env: " in proc.stdout


def test_setup_env_probe_prefers_python312_in_path(tmp_path: Path) -> None:
    py312 = tmp_path / "python3.12"
    py312.write_text(
        chr(35)
        + f"!{sys.executable}\n"
        + "import sys\n"
        + "if sys.argv[1:2] == ['--version']:\n"
        + "    print('Python 3.12.9')\n"
        + "    raise SystemExit(0)\n"
        + "if sys.argv[1:2] == ['-c'] and len(sys.argv) >= 3:\n"
        + "    sys.version_info = (3, 12, 9, 'final', 0)\n"
        + "    exec(sys.argv[2])\n"
        + "    raise SystemExit(0)\n"
        + "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    py312.chmod(0o755)
    path_val = f"{tmp_path}:{os.environ.get('PATH', '')}"
    proc = _run_setup(
        {
            "SETUP_CHECK_ONLY": "1",
            "PYTHON_BIN": "",
            "HOME": str(tmp_path),
            "PATH": path_val,
        }
    )
    assert proc.returncode == 0, proc.stderr
    assert f"setup_env: python={py312} (Python 3.12.9)" in proc.stdout


def test_setup_env_rejects_python_310_stub(tmp_path: Path) -> None:
    stub = tmp_path / "fake_python_310"
    stub.write_text(
        chr(35)
        + f"!{sys.executable}\n"
        + "import sys\n"
        + "if sys.argv[1:2] == ['--version']:\n"
        + "    print('Python 3.10.14')\n"
        + "    raise SystemExit(0)\n"
        + "if sys.argv[1:2] == ['-c'] and len(sys.argv) >= 3:\n"
        + "    sys.version_info = (3, 10, 14, 'final', 0)\n"
        + "    exec(sys.argv[2])\n"
        + "    raise SystemExit(0)\n"
        + "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    proc = _run_setup({"SETUP_CHECK_ONLY": "1", "PYTHON_BIN": str(stub)})
    assert proc.returncode != 0
    assert proc.stderr.strip() != ""


def test_setup_env_rejects_nonexistent_python_bin(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist_python312"
    proc = _run_setup({"SETUP_CHECK_ONLY": "1", "PYTHON_BIN": str(missing)})
    assert proc.returncode != 0
    assert proc.stderr.strip() != ""


def test_touched_files_have_no_comments_docstrings_or_em_dashes() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    for rel in TOUCHED_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        assert em_dash not in text, f"em dash found in {rel}"
        lines = text.splitlines()
        if rel == "scripts/setup_env.sh":
            assert lines[0] == hash_char + "!/usr/bin/env bash"
            assert all(hash_char not in line for line in lines[1:]), f"comment found in {rel}"
        else:
            assert hash_char not in text, f"comment found in {rel}"
    tree = ast.parse((ROOT / "tests" / "test_setup_env.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert ast.get_docstring(node) is None

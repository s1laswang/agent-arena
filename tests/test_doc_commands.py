"""Unit and integration tests for scripts/verify_doc_commands.py."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_doc_commands.py"
HASH_CHAR = chr(35)


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_doc_commands", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verify_doc_commands = _load_verifier()


def _write_files(base: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_real_repo_passes_doc_commands_verifier(capsys):
    rc = verify_doc_commands.main(["--root", str(ROOT), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 10.0
    by_name = {r["name"]: r for r in payload["results"]}
    assert by_name["Makefile Targets Check"]["status"] == "PASS"
    assert by_name["Script & Module Paths Check"]["status"] in {"PASS", "WARN"}
    assert by_name["CLI Long-Flag Check"]["status"] == "PASS"


def test_fails_on_nonexistent_makefile_target(tmp_path, capsys):
    _write_files(
        tmp_path,
        {
            "Makefile": ".PHONY: setup reproduce\nsetup:\n\t@true\nreproduce:\n\t@true\n",
            "README.md": (
                f"{HASH_CHAR} Canary\n\n"
                "```bash\n"
                "make setup && make nonexistent-target\n"
                "```\n"
            ),
        },
    )
    rc = verify_doc_commands.main(["--root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    by_name = {r["name"]: r for r in payload["results"]}
    make_res = by_name["Makefile Targets Check"]
    assert make_res["status"] == "FAIL"
    assert any("nonexistent-target" in d for d in make_res["details"])


def test_fails_on_missing_script_in_readme(tmp_path, capsys):
    _write_files(
        tmp_path,
        {
            "Makefile": ".PHONY: setup\nsetup:\n\t@true\n",
            "README.md": (
                f"{HASH_CHAR} Canary\n\n"
                "Run `uv run python scripts/missing_script.py` to inspect.\n"
            ),
        },
    )
    rc = verify_doc_commands.main(["--root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    by_name = {r["name"]: r for r in payload["results"]}
    path_res = by_name["Script & Module Paths Check"]
    assert path_res["status"] == "FAIL"
    assert any("scripts/missing_script.py" in d for d in path_res["details"])


def test_fails_on_missing_canary_module_and_package_without_main(tmp_path, capsys):
    mod_case = tmp_path / "missing_mod"
    _write_files(
        mod_case,
        {
            "Makefile": ".PHONY: test\ntest:\n\t@true\n",
            "canary/__init__.py": "",
            "README.md": (
                "```bash\n"
                "python -m canary.no_such_mod --help\n"
                "```\n"
            ),
        },
    )
    rc = verify_doc_commands.main(["--root", str(mod_case), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    by_name = {r["name"]: r for r in payload["results"]}
    assert by_name["Script & Module Paths Check"]["status"] == "FAIL"
    assert any("canary.no_such_mod" in d for d in by_name["Script & Module Paths Check"]["details"])

    pkg_no_main = tmp_path / "pkg_no_main"
    _write_files(
        pkg_no_main,
        {
            "Makefile": ".PHONY: test\ntest:\n\t@true\n",
            "canary/__init__.py": "",
            "canary/subpkg/__init__.py": "",
            "README.md": "`python -m canary.subpkg`\n",
        },
    )
    assert verify_doc_commands.main(["--root", str(pkg_no_main), "--json"]) == 1
    capsys.readouterr()

    _write_files(pkg_no_main, {"canary/subpkg/__main__.py": "print('ok')\n"})
    assert verify_doc_commands.main(["--root", str(pkg_no_main), "--json"]) == 0
    capsys.readouterr()


def test_fails_on_bogus_flag_for_demo_replay_and_modules(tmp_path, capsys):
    repo = tmp_path / "flag_case"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "demo_replay.py", repo / "scripts" / "demo_replay.py")
    _write_files(
        repo,
        {
            "Makefile": ".PHONY: setup\nsetup:\n\t@true\n",
            "README.md": (
                "```bash\n"
                "uv run python scripts/demo_replay.py --bogus-flag 1\n"
                "```\n"
            ),
        },
    )
    rc = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    by_name = {r["name"]: r for r in payload["results"]}
    flag_res = by_name["CLI Long-Flag Check"]
    assert flag_res["status"] == "FAIL"
    assert any("--bogus-flag" in d for d in flag_res["details"])

    _write_files(
        repo,
        {
            "README.md": (
                "```bash\n"
                "uv run python scripts/demo_replay.py --seed 4 --verify\n"
                "```\n"
            ),
        },
    )
    rc_ok = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    assert payload_ok["passed"] is True


def test_judge_walkthrough_and_dynamic_help_fallback(tmp_path, capsys):
    _write_files(
        tmp_path,
        {
            "Makefile": ".PHONY: reproduce\nreproduce:\n\t@true\n",
            "scripts/dyn_cli.py": (
                "import sys\n"
                "if '--help' in sys.argv:\n"
                "    print('usage: dyn_cli.py [--dynamic-flag VAL]')\n"
                "    raise SystemExit(0)\n"
            ),
            "README.md": "`CANARY_WORLD_SECRET=<any string> make reproduce`\n",
            "docs/JUDGE-WALKTHROUGH.md": "`python scripts/dyn_cli.py --dynamic-flag 42`\n",
        },
    )
    rc_pass = verify_doc_commands.main(["--root", str(tmp_path), "--json"])
    capsys.readouterr()
    assert rc_pass == 0

    _write_files(
        tmp_path,
        {
            "docs/JUDGE-WALKTHROUGH.md": "`python scripts/dyn_cli.py --drifted-flag 42`\n",
        },
    )
    rc_fail = verify_doc_commands.main(["--root", str(tmp_path), "--json"])
    payload_fail = json.loads(capsys.readouterr().out)
    assert rc_fail == 1
    by_name = {r["name"]: r for r in payload_fail["results"]}
    assert by_name["CLI Long-Flag Check"]["status"] == "FAIL"
    assert any("--drifted-flag" in d for d in by_name["CLI Long-Flag Check"]["details"])


def test_module_flag_checks_equals_syntax_and_external_branch_warn(tmp_path, capsys):
    repo = tmp_path / "mod_flags"
    _write_files(
        repo,
        {
            "Makefile": ".PHONY: test\ntest:\n\t@true\n",
            "canary/__init__.py": "",
            "canary/eval.py": (
                "import argparse\n"
                "ap = argparse.ArgumentParser()\n"
                "ap.add_argument('--reproduce', action='store_true')\n"
                "ap.add_argument('--tier', default='all')\n"
            ),
            "harbor/build.py": (
                "import argparse\n"
                "ap = argparse.ArgumentParser()\n"
                "ap.add_argument('--tiers', default='hard')\n"
            ),
            "README.md": (
                "```bash\n"
                "python -m canary.eval --reproduce --tier=hard\n"
                "python harbor/build.py --tiers=hard\n"
                "```\n"
                "- Reproduce branch run: `python -m canary.experimental.branch_only --alpha 1`, "
                "run on branch `feature-exp`.\n"
            ),
        },
    )
    rc_warn = verify_doc_commands.main(["--root", str(repo)])
    text_out = capsys.readouterr().out
    assert rc_warn == 0
    assert "[WARN] Script & Module Paths Check" in text_out
    assert "feature-exp" in text_out

    _write_files(
        repo,
        {
            "README.md": "`python -m canary.eval --no-such-eval-flag=1`\n",
        },
    )
    rc_bad_mod = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_bad_mod = json.loads(capsys.readouterr().out)
    assert rc_bad_mod == 1
    by_name = {r["name"]: r for r in payload_bad_mod["results"]}
    assert by_name["CLI Long-Flag Check"]["status"] == "FAIL"
    assert any("--no-such-eval-flag" in d for d in by_name["CLI Long-Flag Check"]["details"])


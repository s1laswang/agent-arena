"""Unit and integration tests for scripts/verify_doc_commands.py."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_doc_commands.py"
REPRO_DOC_PATH = ROOT / "docs" / "REPRODUCIBILITY.md"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")
HASH_CHAR = chr(35)


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_doc_commands", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verify_doc_commands = _load_verifier()


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-doc-commands-") as tmp_str:
        yield Path(tmp_str)


def _write_files(base: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_owned_files_hygiene():
    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"unexpected hash character in {py_path.name}"
        assert "\u2014" not in src, f"unexpected em dash in {py_path.name}"
        assert "\u2013" not in src, f"unexpected en dash in {py_path.name}"

    doc_src = REPRO_DOC_PATH.read_text(encoding="utf-8")
    assert "\u2014" not in doc_src, "unexpected em dash in docs/REPRODUCIBILITY.md"
    assert "\u2013" not in doc_src, "unexpected en dash in docs/REPRODUCIBILITY.md"


def test_real_repo_passes_doc_commands_verifier(capsys):
    assert "JUDGE_QUICKSTART.md" in verify_doc_commands.DEFAULT_DOCS
    assert "docs/REPRODUCIBILITY.md" in verify_doc_commands.DEFAULT_DOCS
    assert "docs/PEER-REVIEW-QA.md" in verify_doc_commands.DEFAULT_DOCS
    assert "docs/SUBMISSION-AUDIT.md" in verify_doc_commands.DEFAULT_DOCS
    assert "JUDGE_QUICKSTART.md" in verify_doc_commands.FLAG_CHECK_DOCS
    assert "docs/REPRODUCIBILITY.md" in verify_doc_commands.FLAG_CHECK_DOCS
    assert "docs/PEER-REVIEW-QA.md" in verify_doc_commands.FLAG_CHECK_DOCS
    assert "docs/SUBMISSION-AUDIT.md" in verify_doc_commands.FLAG_CHECK_DOCS
    assert verify_doc_commands.audit_repo is verify_doc_commands.verify_repo

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
    assert by_name["Harbor CLI & Env-Var Check"]["status"] == "PASS"


def test_gemini_sessions_planning_brief_never_false_fails(opencode_tmp, capsys):
    gemini_sessions = ROOT / "docs" / "agents" / "GEMINI-SESSIONS.md"
    assert gemini_sessions.is_file()

    rc_single = verify_doc_commands.main(
        ["--root", str(ROOT), "--doc", "docs/agents/GEMINI-SESSIONS.md", "--json"]
    )
    payload_single = json.loads(capsys.readouterr().out)
    assert rc_single == 0
    assert payload_single["passed"] is True
    assert all(r["status"] != "FAIL" for r in payload_single["results"])

    combined_docs = list(verify_doc_commands.DEFAULT_DOCS) + ["docs/agents/GEMINI-SESSIONS.md"]
    combined_res = verify_doc_commands.verify_repo(ROOT, combined_docs)
    assert all(r.status != "FAIL" for r in combined_res)

    repo = opencode_tmp / "brief_case"
    _write_files(
        repo,
        {
            "Makefile": ".PHONY: setup test\nsetup:\n\t@true\ntest:\n\t@true\n",
            "docs/agents/GEMINI-SESSIONS.md": (
                f"{HASH_CHAR} Briefs\n\n"
                "```\n"
                "Verify: every episode replay-verified; make test green; numbers reproduce.\n"
                "```\n\n"
                "Illustrative future script: `python scripts/future_session_helper.py --planned`.\n"
            ),
        },
    )
    rc_synth = verify_doc_commands.main(
        ["--root", str(repo), "--doc", "docs/agents/GEMINI-SESSIONS.md", "--json"]
    )
    payload_synth = json.loads(capsys.readouterr().out)
    assert rc_synth == 0
    assert payload_synth["passed"] is True


def test_reproducibility_doc_completeness_and_sync():
    txt = REPRO_DOC_PATH.read_text(encoding="utf-8")
    required_tokens = (
        "a8f99c2537c91d72",
        "1021/1031",
        "51,814",
        "442/442",
        "80/80",
        "18/18",
        "rehearsal-dry",
        "91",
        "75",
        "16",
        "4,325",
        "99",
        "3,960",
        "REPRO_ANTICHEAT=0",
        "~10 s",
        "CANARY_WORLD_SECRET=<str>",
        "300",
        "200",
        "+0.39",
        "+0.68",
        "git: `unknown`",
    )
    for tok in required_tokens:
        assert tok in txt, f"docs/REPRODUCIBILITY.md missing required token: {tok}"
    for forbidden in ("gemini-3.5-flash", "+0.373", "75% [36%, 123%]", "22% [-23%, 63%]"):
        assert forbidden not in txt, f"docs/REPRODUCIBILITY.md contains forbidden gap token: {forbidden}"


def test_fails_on_nonexistent_makefile_target(opencode_tmp, capsys):
    _write_files(
        opencode_tmp,
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
    rc = verify_doc_commands.main(["--root", str(opencode_tmp), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    by_name = {r["name"]: r for r in payload["results"]}
    make_res = by_name["Makefile Targets Check"]
    assert make_res["status"] == "FAIL"
    assert any("nonexistent-target" in d for d in make_res["details"])


def test_fails_on_missing_script_in_readme(opencode_tmp, capsys):
    _write_files(
        opencode_tmp,
        {
            "Makefile": ".PHONY: setup\nsetup:\n\t@true\n",
            "README.md": (
                f"{HASH_CHAR} Canary\n\n"
                "Run `uv run python scripts/missing_script.py` to inspect.\n"
            ),
        },
    )
    rc = verify_doc_commands.main(["--root", str(opencode_tmp), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    by_name = {r["name"]: r for r in payload["results"]}
    path_res = by_name["Script & Module Paths Check"]
    assert path_res["status"] == "FAIL"
    assert any("scripts/missing_script.py" in d for d in path_res["details"])


def test_fails_on_missing_canary_module_and_package_without_main(opencode_tmp, capsys):
    mod_case = opencode_tmp / "missing_mod"
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

    pkg_no_main = opencode_tmp / "pkg_no_main"
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


def test_fails_on_bogus_flag_for_demo_replay_and_modules(opencode_tmp, capsys):
    repo = opencode_tmp / "flag_case"
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


def test_judge_walkthrough_and_dynamic_help_fallback(opencode_tmp, capsys):
    _write_files(
        opencode_tmp,
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
    rc_pass = verify_doc_commands.main(["--root", str(opencode_tmp), "--json"])
    capsys.readouterr()
    assert rc_pass == 0

    _write_files(
        opencode_tmp,
        {
            "docs/JUDGE-WALKTHROUGH.md": "`python scripts/dyn_cli.py --drifted-flag 42`\n",
        },
    )
    rc_fail = verify_doc_commands.main(["--root", str(opencode_tmp), "--json"])
    payload_fail = json.loads(capsys.readouterr().out)
    assert rc_fail == 1
    by_name = {r["name"]: r for r in payload_fail["results"]}
    assert by_name["CLI Long-Flag Check"]["status"] == "FAIL"
    assert any("--drifted-flag" in d for d in by_name["CLI Long-Flag Check"]["details"])


def test_module_flag_checks_equals_syntax_and_external_branch_warn(opencode_tmp, capsys):
    repo = opencode_tmp / "mod_flags"
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


def test_harbor_rule_a_forbids_canary_env_in_agent_container(opencode_tmp, capsys):
    repo = opencode_tmp / "harbor_rule_a"
    _write_files(
        repo,
        {
            "Makefile": ".PHONY: setup\nsetup:\n\t@true\n",
            "README.md": (
                "```bash\n"
                "harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=solver -n 4\n"
                "harbor run -p harbor/dataset -a oracle --ae EXTRA_NON_CANARY=1 -n 2\n"
                "```\n"
            ),
        },
    )
    rc_ok = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    by_name_ok = {r["name"]: r for r in payload_ok["results"]}
    assert by_name_ok["Harbor CLI & Env-Var Check"]["status"] == "PASS"

    _write_files(
        repo,
        {
            "README.md": (
                "```bash\n"
                "harbor run -p harbor/dataset -a oracle --ae CANARY_WORLD_SECRET=leak -n 2\n"
                "```\n"
            ),
        },
    )
    rc_fail = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_fail = json.loads(capsys.readouterr().out)
    assert rc_fail == 1
    harbor_res = {r["name"]: r for r in payload_fail["results"]}["Harbor CLI & Env-Var Check"]
    assert harbor_res["status"] == "FAIL"
    assert any("CANARY_WORLD_SECRET" in d for d in harbor_res["details"])

    _write_files(
        repo,
        {
            "README.md": "`harbor run -p harbor/dataset -a opencode -m openai/gpt-5.5 --ae=CANARY_SEED=<seed>`\n",
        },
    )
    rc_fail_eq = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_fail_eq = json.loads(capsys.readouterr().out)
    assert rc_fail_eq == 1
    harbor_res_eq = {r["name"]: r for r in payload_fail_eq["results"]}["Harbor CLI & Env-Var Check"]
    assert harbor_res_eq["status"] == "FAIL"
    assert any("CANARY_SEED" in d for d in harbor_res_eq["details"])


def test_harbor_rule_b_requires_google_api_key_name_for_opencode_google(opencode_tmp, capsys):
    repo = opencode_tmp / "harbor_rule_b"
    _write_files(
        repo,
        {
            "Makefile": ".PHONY: setup\nsetup:\n\t@true\n",
            "README.md": (
                "```bash\n"
                "GOOGLE_GENERATIVE_AI_API_KEY=<your key> harbor run -p harbor/dataset -a opencode \\\n"
                "    -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY -n 4\n"
                "harbor run -p harbor/dataset -a opencode -m openai/<model> -n 4\n"
                "```\n"
            ),
        },
    )
    rc_ok = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    assert {r["name"]: r for r in payload_ok["results"]}["Harbor CLI & Env-Var Check"]["status"] == "PASS"

    _write_files(
        repo,
        {
            "README.md": (
                "```bash\n"
                "GOOGLE_GENERATIVE_AI_API_KEY=<key> harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon -n 4\n"
                "```\n"
            ),
        },
    )
    rc_missing = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_missing = json.loads(capsys.readouterr().out)
    assert rc_missing == 1
    res_missing = {r["name"]: r for r in payload_missing["results"]}["Harbor CLI & Env-Var Check"]
    assert res_missing["status"] == "FAIL"
    assert any("GOOGLE_GENERATIVE_AI_API_KEY" in d for d in res_missing["details"])

    _write_files(
        repo,
        {
            "README.md": (
                "`harbor run -p harbor/dataset --agent=opencode --model=google/gemini-4-carbon "
                "--api-key-name=GEMINI_API_KEY`\n"
            ),
        },
    )
    rc_wrong = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_wrong = json.loads(capsys.readouterr().out)
    assert rc_wrong == 1
    res_wrong = {r["name"]: r for r in payload_wrong["results"]}["Harbor CLI & Env-Var Check"]
    assert res_wrong["status"] == "FAIL"
    assert any("GOOGLE_GENERATIVE_AI_API_KEY" in d for d in res_wrong["details"])


def test_harbor_rule_c_validates_oracle_policy_and_ignores_placeholders(opencode_tmp, capsys):
    repo = opencode_tmp / "harbor_rule_c"
    _write_files(
        repo,
        {
            "Makefile": ".PHONY: setup\nsetup:\n\t@true\n",
            "README.md": (
                "```bash\n"
                "harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=solver -n 2\n"
                "harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 2\n"
                "harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 2\n"
                "harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=guess_day1 -n 2\n"
                "harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat_probe -n 2\n"
                "harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat -n 2\n"
                "harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=<policy> -n 2\n"
                "```\n"
            ),
        },
    )
    rc_ok = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    assert {r["name"]: r for r in payload_ok["results"]}["Harbor CLI & Env-Var Check"]["status"] == "PASS"

    _write_files(
        repo,
        {
            "README.md": "`harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=not_a_real_policy -n 2`\n",
        },
    )
    rc_bad = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_bad = json.loads(capsys.readouterr().out)
    assert rc_bad == 1
    res_bad = {r["name"]: r for r in payload_bad["results"]}["Harbor CLI & Env-Var Check"]
    assert res_bad["status"] == "FAIL"
    assert any("ORACLE_POLICY=not_a_real_policy" in d for d in res_bad["details"])

    _write_files(
        repo,
        {
            "README.md": "`harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=`\n",
        },
    )
    rc_empty = verify_doc_commands.main(["--root", str(repo), "--json"])
    capsys.readouterr()
    assert rc_empty == 1


def test_judge_quickstart_and_reproducibility_docs_discovery(opencode_tmp, capsys):
    repo = opencode_tmp / "quickstart_discovery"
    _write_files(
        repo,
        {
            "Makefile": ".PHONY: setup reproduce accept\nsetup:\n\t@true\nreproduce:\n\t@true\naccept:\n\t@true\n",
            "scripts/check_tool.py": (
                "import argparse\n"
                "ap = argparse.ArgumentParser()\n"
                "ap.add_argument('--check', action='store_true')\n"
            ),
            "JUDGE_QUICKSTART.md": (
                f"{HASH_CHAR} Quickstart\n\n"
                "```bash\n"
                "make setup && make reproduce\n"
                "python scripts/check_tool.py --check\n"
                "GOOGLE_GENERATIVE_AI_API_KEY=<key> harbor run -p harbor/dataset -a opencode "
                "-m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY -n 2\n"
                "```\n"
            ),
            "docs/REPRODUCIBILITY.md": (
                f"{HASH_CHAR} Reproducibility\n\n"
                "`CANARY_WORLD_SECRET=<any-string> make reproduce`\n"
            ),
        },
    )
    rc_pass = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_pass = json.loads(capsys.readouterr().out)
    assert rc_pass == 0
    assert payload_pass["passed"] is True

    _write_files(
        repo,
        {
            "JUDGE_QUICKSTART.md": (
                f"{HASH_CHAR} Quickstart\n\n"
                "`harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon`\n"
            ),
        },
    )
    rc_qs_fail = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_qs_fail = json.loads(capsys.readouterr().out)
    assert rc_qs_fail == 1
    harbor_qs = {r["name"]: r for r in payload_qs_fail["results"]}["Harbor CLI & Env-Var Check"]
    assert harbor_qs["status"] == "FAIL"
    assert any("JUDGE_QUICKSTART.md" in d for d in harbor_qs["details"])

    _write_files(
        repo,
        {
            "JUDGE_QUICKSTART.md": "`make reproduce`\n",
            "docs/REPRODUCIBILITY.md": "`python scripts/check_tool.py --unknown-repro-flag`\n",
        },
    )
    rc_repro_fail = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_repro_fail = json.loads(capsys.readouterr().out)
    assert rc_repro_fail == 1
    flag_repro = {r["name"]: r for r in payload_repro_fail["results"]}["CLI Long-Flag Check"]
    assert flag_repro["status"] == "FAIL"
    assert any("docs/REPRODUCIBILITY.md" in d for d in flag_repro["details"])

    _write_files(
        repo,
        {
            "docs/REPRODUCIBILITY.md": "`python scripts/check_tool.py --check`\n",
            "docs/PEER-REVIEW-QA.md": "`python scripts/check_tool.py --drifted-qa-flag`\n",
        },
    )
    rc_qa_fail = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_qa_fail = json.loads(capsys.readouterr().out)
    assert rc_qa_fail == 1
    flag_qa = {r["name"]: r for r in payload_qa_fail["results"]}["CLI Long-Flag Check"]
    assert flag_qa["status"] == "FAIL"
    assert any("docs/PEER-REVIEW-QA.md" in d for d in flag_qa["details"])


def test_accept_env_knobs_shell_flags_and_submission_verifier(opencode_tmp, capsys):
    repo = opencode_tmp / "accept_and_sub_case"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "judge_accept.sh", repo / "scripts" / "judge_accept.sh")
    shutil.copy2(ROOT / "scripts" / "verify_submission_doc.py", repo / "scripts" / "verify_submission_doc.py")
    _write_files(
        repo,
        {
            "Makefile": ".PHONY: setup reproduce accept\nsetup:\n\t@true\nreproduce:\n\t@true\naccept:\n\t@true\n",
            "docs/REPRODUCIBILITY.md": (
                f"{HASH_CHAR} Reproducibility\n\n"
                "```bash\n"
                "ACCEPT_FORCE_REPRODUCE=1 make accept\n"
                "ACCEPT_REUSE_MAX_AGE_S=900 bash scripts/judge_accept.sh\n"
                "python scripts/verify_submission_doc.py --json\n"
                "```\n"
            ),
        },
    )
    rc_ok = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    assert payload_ok["passed"] is True

    _write_files(
        repo,
        {
            "docs/REPRODUCIBILITY.md": "`ACCEPT_NONEXISTENT_KNOB=1 make accept`\n",
        },
    )
    rc_bad_knob = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_bad_knob = json.loads(capsys.readouterr().out)
    assert rc_bad_knob == 1
    harbor_bad = {r["name"]: r for r in payload_bad_knob["results"]}["Harbor CLI & Env-Var Check"]
    assert harbor_bad["status"] == "FAIL"
    assert any("ACCEPT_NONEXISTENT_KNOB" in d for d in harbor_bad["details"])

    _write_files(
        repo,
        {
            "docs/REPRODUCIBILITY.md": "`ACCEPT_FORCE_REPRODUCE=2 make accept`\n",
        },
    )
    rc_bad_val = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_bad_val = json.loads(capsys.readouterr().out)
    assert rc_bad_val == 1
    harbor_val = {r["name"]: r for r in payload_bad_val["results"]}["Harbor CLI & Env-Var Check"]
    assert harbor_val["status"] == "FAIL"
    assert any("ACCEPT_FORCE_REPRODUCE=2" in d for d in harbor_val["details"])

    _write_files(
        repo,
        {
            "docs/REPRODUCIBILITY.md": "`bash scripts/judge_accept.sh --bogus-sh-flag`\n",
        },
    )
    rc_bad_sh = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_bad_sh = json.loads(capsys.readouterr().out)
    assert rc_bad_sh == 1
    flag_bad_sh = {r["name"]: r for r in payload_bad_sh["results"]}["CLI Long-Flag Check"]
    assert flag_bad_sh["status"] == "FAIL"
    assert any("--bogus-sh-flag" in d for d in flag_bad_sh["details"])

    _write_files(
        repo,
        {
            "docs/REPRODUCIBILITY.md": "`verify_submission_doc.py --no-such-flag`\n",
        },
    )
    rc_bad_sub = verify_doc_commands.main(["--root", str(repo), "--json"])
    payload_bad_sub = json.loads(capsys.readouterr().out)
    assert rc_bad_sub == 1
    flag_bad_sub = {r["name"]: r for r in payload_bad_sub["results"]}["CLI Long-Flag Check"]
    assert flag_bad_sub["status"] == "FAIL"
    assert any("--no-such-flag" in d for d in flag_bad_sub["details"])



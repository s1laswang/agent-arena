from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = ROOT / "scripts" / "craft_preflight.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")
H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
PM = chr(0x00B1)


def _load_preflight():
    spec = importlib.util.spec_from_file_location("craft_preflight", PREFLIGHT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


preflight = _load_preflight()


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-craft-preflight-") as tmp_str:
        yield Path(tmp_str)


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_CEILING_DIRECTORIES": str(repo.parent), "PATH": "/usr/bin:/bin:/usr/local/bin"}
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _init_branched_repo(
    repo: Path,
    base_files: dict[str, str],
    set_justsilas_ref: bool = True,
    branch_name: str = "feature",
) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    for rel, content in base_files.items():
        fp = repo / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial base")
    base_sha = _git(repo, "rev-parse", "HEAD")
    if set_justsilas_ref:
        _git(repo, "update-ref", "refs/remotes/origin/justSilas", base_sha)
    _git(repo, "checkout", "-q", "-b", branch_name)
    return base_sha


def _sample_protected_txt() -> str:
    return "\n".join(
        [
            f"{H} Protected paths",
            "canary/env.py",
            "canary/rules.py",
            "canary/solver/",
            "harbor/",
            "Makefile",
            "configs/",
            "data/runs/committed/",
            "results/judge_table.md",
            ".github/protected-paths.txt",
            ".github/workflows/",
            "",
        ]
    )


def _copy_paired_table_fixture(dst_repo: Path) -> None:
    for rel in (
        "Makefile",
        ".github/protected-paths.txt",
        "docs/reports/gap.md",
        "JUDGE_QUICKSTART.md",
        "data/runs/committed/v1.4/paired_table_gemini.json",
        "data/runs/committed/v1.4/paired_table_gemini.md",
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json",
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md",
    ):
        src = ROOT / rel
        dst = dst_repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def _minimal_harbor_builder_source() -> str:
    return """from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

H = chr(35)

ap = argparse.ArgumentParser()
ap.add_argument("--tiers", default="hard")
ap.add_argument("--seeds", default="900000")
ap.add_argument("--out", required=True)
args = ap.parse_args()

task = Path(args.out) / f"canary-{args.tiers}-{args.seeds}"
(task / "environment" / "canary-server" / "data" / "worlds" / "judge").mkdir(parents=True, exist_ok=True)
(task / "tests").mkdir(parents=True, exist_ok=True)
(task / "solution").mkdir(parents=True, exist_ok=True)

(task / "task.toml").write_text(
    '[verifier]\\nenvironment_mode = "separate"\\n[[verifier.collect]]\\nsource = "/out"\\n'
    '[environment]\\ncpus = 2\\n',
    encoding="utf-8",
)
(task / "environment" / "Dockerfile").write_text("FROM ubuntu:24.04\\nRUN true\\n", encoding="utf-8")
(task / "environment" / ".dockerignore").write_text(f"{H} ignore sidecar\\ncanary-server\\n", encoding="utf-8")

for secret_file, payload in [
    (task / "environment" / "canary-server" / "data" / "worlds" / "judge" / "SALT", "secret-salt-value-16b\\n"),
    (task / "environment" / "canary-server" / "episode.json", json.dumps({"tier": args.tiers, "seed": int(args.seeds)})),
    (task / "environment" / "canary-server" / "ledger_key", "secret-ledger-key-16b\\n"),
    (task / "tests" / "ledger_key", "secret-ledger-key-16b\\n"),
]:
    secret_file.write_text(payload, encoding="utf-8")
    os.chmod(secret_file, 0o600)
"""


def _stub_core_sibling_runners(monkeypatch: pytest.MonkeyPatch) -> None:
    ok_res = lambda label: lambda root=ROOT: [preflight.CheckResult(label, "PASS", "ok")]
    monkeypatch.setattr(preflight, "run_craft_consistency", ok_res("Craft Consistency"))
    monkeypatch.setattr(preflight, "run_doc_commands", ok_res("Doc Commands"))
    monkeypatch.setattr(preflight, "run_doc_hygiene", ok_res("Doc Hygiene"))
    monkeypatch.setattr(preflight, "run_judge_walkthrough", ok_res("Judge Walkthrough"))
    monkeypatch.setattr(preflight, "run_submission_surfaces", ok_res("Submission Surfaces"))


def test_strict_source_hygiene() -> None:
    assert preflight.audit_repo is preflight.run_craft_preflight
    assert preflight.verify_repo is preflight.run_craft_preflight
    for path in (PREFLIGHT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert H not in src, f"unexpected hash character in {path.name}"
        assert EM_DASH not in src, f"unexpected em dash in {path.name}"
        assert EN_DASH not in src, f"unexpected en dash in {path.name}"


def test_real_repo_preflight_passes_fast(opencode_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before_harbor = {p.name for p in opencode_tmp.glob("canary-preflight-harbor-*")}
    t0 = time.monotonic()
    rc = preflight.main(
        [
            "--root",
            str(ROOT),
            "--check-protected-vs",
            "origin/justSilas",
            "--tmp-root",
            str(opencode_tmp),
            "--json",
        ]
    )
    wall_s = time.monotonic() - t0
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0, payload
    assert payload["passed"] is True
    assert payload["counts"]["FAIL"] == 0
    assert payload["check_protected_vs"] == "origin/justSilas"
    assert payload["elapsed_s"] < 15.0
    assert wall_s < 15.0
    gate_names = [g["name"] for g in payload["gates"]]
    for expected_gate in preflight.DEFAULT_GATE_NAMES:
        assert expected_gate in gate_names
    assert payload["results"] == payload["checks"]
    assert len(payload["results"]) >= 23
    for item in payload["results"]:
        assert item["status"] in {"PASS", "WARN"}, item

    reconstructed_gates = [
        preflight.GateResult(
            gate=g["gate"],
            name=g["name"],
            status=g["status"],
            summary=g["summary"],
            checks=[preflight.CheckResult(**c) for c in g["checks"]],
        )
        for g in payload["gates"]
    ]
    report_txt = preflight.format_report(reconstructed_gates, payload["elapsed_s"])
    assert "SUMMARY:" in report_txt
    assert "0 FAIL" in report_txt

    after_harbor = {p.name for p in opencode_tmp.glob("canary-preflight-harbor-*")}
    assert after_harbor - before_harbor == set()


def test_protected_paths_guard_pass_fail_and_check_protected_vs(opencode_tmp: Path) -> None:
    repo = opencode_tmp / "prot_clean"
    _init_branched_repo(
        repo,
        {
            ".github/protected-paths.txt": _sample_protected_txt(),
            "canary/env.py": "x = 1\n",
            "harbor/build.py": "y = 2\n",
            "results/judge_table.md": "table\n",
            "scripts/ok.py": "z = 3\n",
        },
        set_justsilas_ref=True,
    )
    (repo / "scripts" / "new_helper.py").write_text("a = 4\n", encoding="utf-8")
    (repo / "docs" / "note.md").parent.mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "note.md").write_text("clean doc\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add safe craft files")

    assert preflight.check_protected_paths(repo).status == "PASS"
    assert preflight.check_protected_paths(repo, check_protected_vs="origin/justSilas").status == "PASS"

    (repo / "results" / "judge_table.md").write_text("modified uncommitted\n", encoding="utf-8")
    res_wt_dirty = preflight.check_protected_paths(repo)
    assert res_wt_dirty.status == "FAIL"
    assert any("results/judge_table.md" in d for d in res_wt_dirty.details)
    _git(repo, "checkout", "--", "results/judge_table.md")

    untracked_prot = repo / "configs" / "sneaky.json"
    untracked_prot.parent.mkdir(parents=True, exist_ok=True)
    untracked_prot.write_text("{}\n", encoding="utf-8")
    res_untracked = preflight.check_protected_paths(repo)
    assert res_untracked.status == "FAIL"
    assert any("configs/sneaky.json" in d for d in res_untracked.details)
    untracked_prot.unlink()

    repo_committed = opencode_tmp / "prot_committed"
    base_sha = _init_branched_repo(
        repo_committed,
        {
            ".github/protected-paths.txt": _sample_protected_txt(),
            "canary/env.py": "x = 1\n",
            "harbor/build.py": "y = 2\n",
        },
        set_justsilas_ref=True,
    )
    (repo_committed / "canary" / "env.py").write_text("x = 2\n", encoding="utf-8")
    (repo_committed / "harbor" / "extra.txt").write_text("touched\n", encoding="utf-8")
    _git(repo_committed, "add", ".")
    _git(repo_committed, "commit", "-q", "-m", "touch protected")
    res_committed = preflight.check_protected_paths(repo_committed)
    assert res_committed.status == "FAIL"
    assert any("canary/env.py" in d for d in res_committed.details)
    assert any("harbor/extra.txt" in d for d in res_committed.details)
    assert preflight.check_protected_paths(repo_committed, check_protected_vs=base_sha).status == "FAIL"

    repo_justsilas = opencode_tmp / "prot_justsilas"
    js_base = _init_branched_repo(
        repo_justsilas,
        {
            ".github/protected-paths.txt": _sample_protected_txt(),
            "canary/env.py": "x = 1\n",
        },
        set_justsilas_ref=True,
        branch_name="justSilas",
    )
    (repo_justsilas / "canary" / "env.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo_justsilas, "add", "canary/env.py")
    _git(repo_justsilas, "commit", "-q", "-m", "owner edit on justSilas")
    assert preflight.check_protected_paths(repo_justsilas).status == "PASS"
    assert preflight.check_protected_paths(repo_justsilas, check_protected_vs=js_base).status == "FAIL"

    _git(repo_justsilas, "checkout", "-q", "--detach", "HEAD")
    assert preflight.check_protected_paths(repo_justsilas).status == "PASS"
    assert preflight.check_protected_paths(repo, check_protected_vs="origin/nonexistent").status == "FAIL"

    gitless_dir = opencode_tmp / "prot_gitless"
    (gitless_dir / ".github").mkdir(parents=True, exist_ok=True)
    (gitless_dir / ".github" / "protected-paths.txt").write_text(
        _sample_protected_txt(), encoding="utf-8"
    )
    assert preflight.check_protected_paths(gitless_dir).status == "WARN"
    assert preflight.check_protected_paths(gitless_dir, check_protected_vs="origin/justSilas").status == "FAIL"


def test_headline_paired_tables_integrity(opencode_tmp: Path) -> None:
    assert preflight.check_headline_paired_tables(ROOT).status == "PASS"

    base_repo = opencode_tmp / "paired_ok"
    _copy_paired_table_fixture(base_repo)
    assert preflight.check_headline_paired_tables(base_repo).status == "PASS"

    bad_md_repo = opencode_tmp / "paired_bad_md"
    _copy_paired_table_fixture(bad_md_repo)
    (bad_md_repo / "data/runs/committed/v1.4/paired_table_gemini.md").write_text(
        "| tier | run | n |\n|---|---|---|\n"
        f"| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | 0.999 {PM} 0.001 |\n",
        encoding="utf-8",
    )
    res_bad_md = preflight.check_headline_paired_tables(bad_md_repo)
    assert res_bad_md.status == "FAIL"
    assert any("paired_table_gemini.md out of sync" in d for d in res_bad_md.details)

    bad_ext_repo = opencode_tmp / "paired_bad_ext"
    _copy_paired_table_fixture(bad_ext_repo)
    ext_path = bad_ext_repo / "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
    mutated_ext = json.loads(ext_path.read_text(encoding="utf-8"))
    for row in mutated_ext:
        if row.get("group") == "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext":
            row["mean"] = 0.900
    ext_path.write_text(json.dumps(mutated_ext), encoding="utf-8")
    res_bad_ext = preflight.check_headline_paired_tables(bad_ext_repo)
    assert res_bad_ext.status == "FAIL"
    assert any("pooled mean" in d for d in res_bad_ext.details)

    bad_ci_repo = opencode_tmp / "paired_bad_ci"
    _copy_paired_table_fixture(bad_ci_repo)
    gem_path = bad_ci_repo / "data/runs/committed/v1.4/paired_table_gemini.json"
    mutated_gem = json.loads(gem_path.read_text(encoding="utf-8"))
    for row in mutated_gem:
        if (
            row.get("group") == "v1.4/opencode-gemini-4-carbon"
            and row.get("tier") == "hard"
            and "alternative" not in row["label"].lower()
        ):
            row["ratio_hi"] = 1.05
    gem_path.write_text(json.dumps(mutated_gem), encoding="utf-8")
    assert preflight.check_headline_paired_tables(bad_ci_repo).status == "FAIL"

    bad_mk_repo = opencode_tmp / "paired_bad_mk"
    _copy_paired_table_fixture(bad_mk_repo)
    (bad_mk_repo / "Makefile").write_text("reproduce:\n\t@true\n", encoding="utf-8")
    res_bad_mk = preflight.check_headline_paired_tables(bad_mk_repo)
    assert res_bad_mk.status == "FAIL"
    assert any("Makefile reproduce recipe missing" in d for d in res_bad_mk.details)


def test_unapproved_gap_row_and_panel_fix_a_guard(opencode_tmp: Path) -> None:
    repo = opencode_tmp / "gap_guard"
    (repo / "docs" / "reports").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "gemini").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-3.5-flash" / "hard").mkdir(
        parents=True, exist_ok=True
    )
    (
        repo
        / "data"
        / "runs"
        / "committed"
        / "v1.4"
        / "opencode-gemini-3.5-flash"
        / "hard"
        / "meta.json"
    ).write_text(json.dumps({"model_id": "gemini-3.5-flash"}), encoding="utf-8")

    gap_file = repo / "docs" / "reports" / "gap.md"
    gap_file.write_text(
        f"{H} Gap report\n"
        "OpenCode gemini-4-carbon hard: 65% [24%, 98%] raw, 72% [52%, 91%] luck-adjusted.\n"
        "Pre-registered second frontier family: gpt-5.5 on hard seeds 0-29.\n"
        "---\n"
        f"{H} History\n"
        "v1.2 opencode:openai/gpt-5.6-sol n=1.\n",
        encoding="utf-8",
    )
    (repo / "JUDGE_QUICKSTART.md").write_text(
        "OpenCode + google/gemini-4-carbon hard: 65% [24%, 98%], 72% [52%, 91%] (post-hoc lock on seeds 0-29).\n",
        encoding="utf-8",
    )
    (repo / "docs" / "JUDGE-WALKTHROUGH.md").write_text(
        "129 real gemini-3.5-flash exploit calls blocked; pre-registered gpt-5.5 OpenCode hard 0-29 logged.\n"
        "Dry rehearsal: oracle +0.467 vs OpenCode +0.398.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "gemini" / "SUBMISSION.md").write_text(
        "When we request gemini-3.5-flash, API serves 3.6-flash in ladder.md.\n",
        encoding="utf-8",
    )
    (repo / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json").write_text(
        json.dumps([{"agent": "opencode:google/gemini-3.5-flash", "tier": "hard"}]),
        encoding="utf-8",
    )
    (repo / "docs" / "PEER-REVIEW-QA.md").write_text(
        "**Objection:** *\"Were dev seeds `0-29` pre-registered before you saw the runs on `v1.4`?\"*\n"
        "Committed v1.4 includes opencode:google/gemini-3.5-flash at +0.373 +/- 0.177 / 75% [36%, 123%] raw / 22% [-23%, 63%] luck-adjusted.\n",
        encoding="utf-8",
    )

    assert preflight.check_unapproved_gap_rows(repo).status == "PASS"

    for bad_snippet in (
        "OpenCode + gemini-3.5-flash: 75% [36%, 123%] raw, 22% [-23%, 63%] luck-adjusted.\n",
        "Second model score +0.373 on hard.\n",
        "Table row: OpenCode + anthropic/claude-4-sonnet | 30 | 60%\n",
        "Headline: 72% [52%, 91%] luck-adjusted and 65% [24%, 98%] raw.\n",
        "Primary Gemini run on pre-registered dev seeds 0-29.\n",
        "Dev seeds 0-29 were pre-registered.\n",
    ):
        (repo / "JUDGE_QUICKSTART.md").write_text(bad_snippet, encoding="utf-8")
        res_bad = preflight.check_unapproved_gap_rows(repo)
        assert res_bad.status == "FAIL", bad_snippet

    (repo / "JUDGE_QUICKSTART.md").write_text(
        "OpenCode + google/gemini-4-carbon hard: 65% [24%, 98%], 72% [52%, 91%] (post-hoc lock on seeds 0-29).\n",
        encoding="utf-8",
    )
    for bad_qa in (
        "Table row: OpenCode + anthropic/claude-4-sonnet | 30 | 60%\n",
        "Headline: 72% [52%, 91%] luck-adjusted and 65% [24%, 98%] raw.\n",
        "Dev seeds 0-29 were pre-registered.\n",
        "Were dev seeds 0-29 pre-registered? Yes, dev seeds 0-29 were pre-registered.\n",
    ):
        (repo / "docs" / "PEER-REVIEW-QA.md").write_text(bad_qa, encoding="utf-8")
        assert preflight.check_unapproved_gap_rows(repo).status == "FAIL", bad_qa
    (repo / "docs" / "PEER-REVIEW-QA.md").write_text(
        "**Objection:** *\"Were dev seeds `0-29` pre-registered before you saw the runs?\"*\n",
        encoding="utf-8",
    )

    gap_file.write_text(
        f"{H} Gap report\n"
        "gemini-4-carbon hard: 65% [24%, 98%], 72% [52%, 91%].\n"
        "gemini-3.5-flash hard: 75% [36%, 123%], 22% [-23%, 63%] (+0.373 +/- 0.177).\n",
        encoding="utf-8",
    )
    (repo / "JUDGE_QUICKSTART.md").write_text(
        "OpenCode + gemini-3.5-flash: +0.373 +/- 0.177, 75% [36%, 123%], 22% [-23%, 63%].\n",
        encoding="utf-8",
    )
    assert preflight.check_unapproved_gap_rows(repo).status == "PASS"


def test_optional_sibling_verifier_autodiscovery(
    opencode_tmp: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_core_sibling_runners(monkeypatch)
    repo = opencode_tmp / "opt_repo"
    _copy_paired_table_fixture(repo)

    assert preflight.discover_optional_verifiers(repo) == {}
    rc_abs = preflight.main(["--root", str(repo), "--tmp-root", str(opencode_tmp), "--json"])
    pay_abs = json.loads(capsys.readouterr().out)
    assert rc_abs == 0, pay_abs
    assert pay_abs["optional_verifiers"] == {
        "verify_commit_provenance": "absent",
        "verify_submission_doc": "absent",
        "verify_artifact_numbers": "absent",
    }

    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prov_path = scripts_dir / "verify_commit_provenance.py"
    subdoc_path = scripts_dir / "verify_submission_doc.py"
    artnum_path = scripts_dir / "verify_artifact_numbers.py"

    prov_ok_src = (
        "from dataclasses import dataclass, field\n"
        "@dataclass\n"
        "class CheckResult:\n"
        "    name: str\n"
        "    status: str\n"
        "    summary: str\n"
        "    details: list[str] = field(default_factory=list)\n"
        "def verify_repo(root=None):\n"
        "    return [CheckResult('Commit SHA Provenance', 'PASS', 'all SHAs verified')]\n"
    )
    subdoc_cli_src = (
        "import json\n"
        "if __name__ == '__main__':\n"
        "    print(json.dumps({'results': [{'name': 'Submission Doc Claims', 'status': 'PASS', 'summary': 'ok', 'details': []}]}))\n"
        "    raise SystemExit(0)\n"
    )
    artnum_ok_src = (
        "from dataclasses import dataclass, field\n"
        "@dataclass\n"
        "class CheckResult:\n"
        "    name: str\n"
        "    status: str\n"
        "    summary: str\n"
        "    details: list[str] = field(default_factory=list)\n"
        "def verify_repo(root=None):\n"
        "    return [CheckResult('Artifact Numbers', 'PASS', 'numbers match')]\n"
    )
    prov_path.write_text(prov_ok_src, encoding="utf-8")
    subdoc_path.write_text(subdoc_cli_src, encoding="utf-8")
    artnum_path.write_text(artnum_ok_src, encoding="utf-8")

    found = preflight.discover_optional_verifiers(repo)
    assert set(found) == {"verify_commit_provenance", "verify_submission_doc", "verify_artifact_numbers"}

    rc_both = preflight.main(["--root", str(repo), "--tmp-root", str(opencode_tmp), "--json"])
    pay_both = json.loads(capsys.readouterr().out)
    assert rc_both == 0, pay_both
    assert pay_both["optional_verifiers"] == {
        "verify_commit_provenance": "present",
        "verify_submission_doc": "present",
        "verify_artifact_numbers": "present",
    }
    both_gate_names = [g["name"] for g in pay_both["gates"]]
    assert "Commit Provenance Verification" in both_gate_names
    assert "Submission Document Verification" in both_gate_names
    assert "Artifact Number Provenance Verification" in both_gate_names

    prov_fail_src = prov_ok_src.replace("'PASS'", "'FAIL'").replace("all SHAs verified", "missing SHA")
    prov_path.write_text(prov_fail_src, encoding="utf-8")
    rc_fail = preflight.main(["--root", str(repo), "--tmp-root", str(opencode_tmp), "--json"])
    pay_fail = json.loads(capsys.readouterr().out)
    assert rc_fail == 1
    assert pay_fail["passed"] is False


def test_with_zip_and_with_submission_audit_flags(
    opencode_tmp: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_core_sibling_runners(monkeypatch)
    repo = opencode_tmp / "flags_repo"
    _copy_paired_table_fixture(repo)
    (repo / "harbor").mkdir(parents=True, exist_ok=True)
    (repo / "harbor" / "build.py").write_text(_minimal_harbor_builder_source(), encoding="utf-8")

    zip_mod = preflight._load_script_module("verify_zip_export", "verify_zip_export.py")
    seen_tmp: list[Path] = []

    def _stub_zip_pass(root: Path = ROOT, *, tmp_base: Path | None = None, **_kw):
        if tmp_base is not None:
            seen_tmp.append(tmp_base)
        return [zip_mod.CheckResult("Keyless Mini-Reproduce Without .git", "PASS", "ok")]

    monkeypatch.setattr(zip_mod, "verify_zip_export", _stub_zip_pass)
    before_harbor = {p.name for p in opencode_tmp.glob("canary-preflight-harbor-*")}
    rc_both_flags = preflight.main(
        [
            "--root",
            str(repo),
            "--tmp-root",
            str(opencode_tmp),
            "--with-submission-audit",
            "--with-zip",
            "--json",
        ]
    )
    payload_ok = json.loads(capsys.readouterr().out)
    assert rc_both_flags == 0, payload_ok
    assert payload_ok["with_zip"] is True
    assert payload_ok["with_submission_audit"] is True
    gate_names = [g["name"] for g in payload_ok["gates"]]
    assert preflight.GATE_SUBMISSION in gate_names
    assert preflight.GATE_ZIP_EXPORT in gate_names
    assert seen_tmp == [opencode_tmp.resolve()]
    after_harbor = {p.name for p in opencode_tmp.glob("canary-preflight-harbor-*")}
    assert after_harbor - before_harbor == set()

    def _stub_zip_fail(root: Path = ROOT, *, tmp_base: Path | None = None, **_kw):
        return [zip_mod.CheckResult("Keyless Mini-Reproduce Without .git", "FAIL", "broken export")]

    monkeypatch.setattr(zip_mod, "verify_zip_export", _stub_zip_fail)
    rc_zip_fail = preflight.main(
        ["--root", str(repo), "--tmp-root", str(opencode_tmp), "--with-zip", "--json"]
    )
    zip_fail_payload = json.loads(capsys.readouterr().out)
    assert rc_zip_fail == 1
    assert zip_fail_payload["passed"] is False

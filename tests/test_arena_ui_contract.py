from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
WALKTHROUGH_PATH = ROOT / "docs" / "arena" / "WALKTHROUGH.md"
VERIFIER_PATH = ROOT / "scripts" / "verify_arena_ui_contract.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

HASH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
MD_LINK_RX = r"\[[^\]]+\]\(([^)\s]+)\)"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_arena_ui_contract", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verifier = _load_verifier()


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-arena-ui-contract-") as tmp_dir:
        yield Path(tmp_dir)


def _write_files(base: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@fleet.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "arena-test"], cwd=repo, check=True)


def test_owned_files_strict_hygiene() -> None:
    for py_path in (VERIFIER_PATH, SELF_PATH):
        raw = py_path.read_text(encoding="utf-8")
        assert raw.isascii(), f"non-ASCII char in {py_path.name}"
        assert EM_DASH not in raw, f"em dash in {py_path.name}"
        assert EN_DASH not in raw, f"en dash in {py_path.name}"
        assert UNICODE_MINUS not in raw, f"unicode minus in {py_path.name}"
        assert HASH not in raw, f"unexpected hash comment character in {py_path.name}"
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected python comments in {py_path.name}: {comments}"

    assert WALKTHROUGH_PATH.is_file()
    wt_raw = WALKTHROUGH_PATH.read_text(encoding="utf-8")
    assert wt_raw.isascii(), "non-ASCII char in docs/arena/WALKTHROUGH.md"
    assert EM_DASH not in wt_raw, "em dash in docs/arena/WALKTHROUGH.md"
    assert EN_DASH not in wt_raw, "en dash in docs/arena/WALKTHROUGH.md"
    assert UNICODE_MINUS not in wt_raw, "unicode minus in docs/arena/WALKTHROUGH.md"


def test_real_repo_passes_arena_ui_contract_check(capsys: pytest.CaptureFixture[str]) -> None:
    rc = verifier.main(["--check", "--root", str(ROOT), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 5.0
    by_name = {r["name"]: r for r in payload["results"]}
    assert by_name["UI Pure ASCII & Zero Em-Dash Check"]["status"] == "PASS"
    assert by_name["UI Zero Comments Check"]["status"] == "PASS"
    assert by_name["UI Zero XSS Sinks Check"]["status"] == "PASS"
    assert by_name["Protected Paths Unmodified Check"]["status"] == "PASS"

    proc = subprocess.run(
        [sys.executable, str(VERIFIER_PATH), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 FAIL" in proc.stdout


def test_walkthrough_covers_all_four_modes_sealed_integrity_and_links() -> None:
    import re

    wt = WALKTHROUGH_PATH.read_text(encoding="utf-8")
    required_tokens = (
        "90-Second",
        "Mode 1",
        "Duel vs Gemini",
        "Seeds 6 & 26",
        "Seed `6`",
        "Seed `26`",
        "gemini-4-carbon",
        "SolverPolicy",
        "+0.73",
        "+0.71",
        "+0.69",
        "-1.00",
        "post-hoc lock",
        "Mode 2",
        "Beat the Solver",
        "3000-9999",
        "Mode 3",
        "Be the Mole",
        "MoleView",
        "Mode 4",
        "Living Office",
        "v1.6",
        "off by default",
        "did NOT pass Gate B",
        "[SEALED]",
        "the episode is not over yet",
        "verify_arena_ui_contract.py --check",
        "a8f99c2537c91d72",
    )
    for tok in required_tokens:
        assert tok in wt, f"docs/arena/WALKTHROUGH.md missing required token: {tok}"

    links = re.findall(MD_LINK_RX, wt)
    assert len(links) >= 6
    for target in links:
        if target.startswith(("http:", "https:", "mailto:")):
            continue
        if target.startswith(HASH):
            continue
        path_part = target.split(HASH, 1)[0]
        resolved = (WALKTHROUGH_PATH.parent / unquote(path_part)).resolve()
        assert resolved.exists(), f"broken relative link in WALKTHROUGH.md: {target} -> {resolved}"


def test_verifier_catches_non_ascii_and_em_dashes(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = opencode_tmp / "ascii_case"
    _write_files(
        repo,
        {
            "docs/arena/ui/panel.js": f'export const title = "Duel {EM_DASH} Mode";\n',
            "docs/arena/ui/theme.css": ".box { color: red; }\n",
        },
    )
    rc = verifier.main(["--check", "--root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    ascii_res = {r["name"]: r for r in payload["results"]}["UI Pure ASCII & Zero Em-Dash Check"]
    assert ascii_res["status"] == "FAIL"
    assert any("em dash" in d and "panel.js" in d for d in ascii_res["details"])

    _write_files(repo, {"docs/arena/ui/panel.js": 'export const title = "Duel \u00e9";\n'})
    rc_utf = verifier.main(["--check", "--root", str(repo), "--json"])
    payload_utf = json.loads(capsys.readouterr().out)
    assert rc_utf == 1
    ascii_utf = {r["name"]: r for r in payload_utf["results"]}["UI Pure ASCII & Zero Em-Dash Check"]
    assert ascii_utf["status"] == "FAIL"
    assert any("U+00E9" in d for d in ascii_utf["details"])


def test_verifier_catches_all_comment_markers(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = opencode_tmp / "comment_case"
    for idx, snippet in enumerate(
        (
            f"const a = 1; {SLASH_SLASH} trailing note\n",
            f"{SLASH_STAR} block note {STAR_SLASH}\nconst b = 2;\n",
            f"const orphan = '{STAR_SLASH}';\n",
        )
    ):
        _write_files(repo, {"docs/arena/ui/mod.js": snippet})
        rc = verifier.main(["--check", "--root", str(repo), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 1, f"case {idx} unexpectedly passed"
        comm_res = {r["name"]: r for r in payload["results"]}["UI Zero Comments Check"]
        assert comm_res["status"] == "FAIL"
        assert any("docs/arena/ui/mod.js" in d for d in comm_res["details"])


def test_verifier_catches_all_four_xss_sinks(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = opencode_tmp / "xss_case"
    sinks_to_test = (
        ("innerHTML", "node.innerHTML = text;\n"),
        ("outerHTML", "node.outerHTML = text;\n"),
        ("insertAdjacentHTML", "node.insertAdjacentHTML('beforeend', text);\n"),
        ("document.write", "document.write(text);\n"),
        ("document.write", "document . write(text);\n"),
    )
    for expected_sink, bad_code in sinks_to_test:
        _write_files(repo, {"docs/arena/ui/render.js": bad_code})
        rc = verifier.main(["--check", "--root", str(repo), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 1
        xss_res = {r["name"]: r for r in payload["results"]}["UI Zero XSS Sinks Check"]
        assert xss_res["status"] == "FAIL"
        assert any(expected_sink in d for d in xss_res["details"])


def test_verifier_catches_protected_path_modifications_in_git_repo(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = opencode_tmp / "git_protected_case"
    _write_files(
        repo,
        {
            "docs/arena/ui/ok.js": "export const ok = 1;\n",
            "canary/env.py": "ENV_V = 1\n",
            "canary/rules.py": 'TIERS_VERSION = "v1.4"\nHASH = "a8f99c2537c91d72"\n',
            "canary/reproduce.py": "REPRO = 1\n",
            "canary/solver/policy.py": "SOLVER = 1\n",
            "harbor/build.py": "HARBOR = 1\n",
        },
    )
    _init_git_repo(repo)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "justSilas"], cwd=repo, check=True)

    rc_clean = verifier.main(["--check", "--root", str(repo), "--base-ref", "justSilas", "--json"])
    payload_clean = json.loads(capsys.readouterr().out)
    assert rc_clean == 0
    assert payload_clean["passed"] is True

    protected_targets = (
        "canary/env.py",
        "canary/rules.py",
        "canary/reproduce.py",
        "canary/solver/policy.py",
        "harbor/build.py",
    )
    for rel_target in protected_targets:
        orig = (repo / rel_target).read_text(encoding="utf-8")
        (repo / rel_target).write_text(orig + "CHANGED = 2\n", encoding="utf-8")
        rc_dirty = verifier.main(["--check", "--root", str(repo), "--base-ref", "justSilas", "--json"])
        payload_dirty = json.loads(capsys.readouterr().out)
        assert rc_dirty == 1, f"failed to catch worktree edit on {rel_target}"
        prot_res = {r["name"]: r for r in payload_dirty["results"]}["Protected Paths Unmodified Check"]
        assert prot_res["status"] == "FAIL"
        assert any(rel_target in d for d in prot_res["details"])
        (repo / rel_target).write_text(orig, encoding="utf-8")

    subprocess.run(["git", "checkout", "-q", "-b", "feature-arena"], cwd=repo, check=True)
    (repo / "canary" / "solver" / "extra.py").write_text("EXTRA = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "canary/solver/extra.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "touch solver"], cwd=repo, check=True)
    rc_comm = verifier.main(["--check", "--root", str(repo), "--base-ref", "justSilas", "--json"])
    payload_comm = json.loads(capsys.readouterr().out)
    assert rc_comm == 1
    prot_comm = {r["name"]: r for r in payload_comm["results"]}["Protected Paths Unmodified Check"]
    assert prot_comm["status"] == "FAIL"
    assert any("canary/solver/extra.py" in d for d in prot_comm["details"])


def test_missing_or_empty_ui_dir_fails_cleanly(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty_repo = opencode_tmp / "missing_ui"
    empty_repo.mkdir(parents=True)
    rc_missing = verifier.main(["--check", "--root", str(empty_repo), "--json"])
    payload_missing = json.loads(capsys.readouterr().out)
    assert rc_missing == 1
    assert payload_missing["passed"] is False

    (empty_repo / "docs" / "arena" / "ui").mkdir(parents=True)
    rc_zero = verifier.main(["--check", "--root", str(empty_repo), "--json"])
    payload_zero = json.loads(capsys.readouterr().out)
    assert rc_zero == 1
    assert payload_zero["passed"] is False

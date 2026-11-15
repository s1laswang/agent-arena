from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRESH_CLONE_DIR = ROOT / "results" / "fresh_clone"
README_PATH = FRESH_CLONE_DIR / "README.md"

MACOS_LOG = "macos_justSilas_09e7363.log.txt"
MACOS_STEPS = "macos_justSilas_09e7363.steps.txt"
LINUX_LOG = "linux_x86_64_justSilas_2b301cea.log.txt"
LINUX_STEPS = "linux_x86_64_justSilas_2b301cea.steps.txt"

MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
STEP_LINE_RE = re.compile(r"^([a-z0-9_]+)\s+exit=(-?\d+)\s+seconds=(\d+)$")


def _parse_steps(path: Path) -> list[tuple[str, int, int]]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, f"empty steps file: {path}"
    parsed: list[tuple[str, int, int]] = []
    for ln in lines:
        match = STEP_LINE_RE.match(ln)
        assert match is not None, f"malformed step line in {path.name}: {ln!r}"
        parsed.append((match.group(1), int(match.group(2)), int(match.group(3))))
    return parsed


def test_fresh_clone_files_exist_and_are_linked_in_readme() -> None:
    assert README_PATH.is_file()
    readme_text = README_PATH.read_text(encoding="utf-8")
    first_line = readme_text.splitlines()[0]
    assert "Fresh-clone checks (macOS and Linux x86_64)" in first_line

    required_files = (MACOS_LOG, MACOS_STEPS, LINUX_LOG, LINUX_STEPS)
    for filename in required_files:
        file_path = FRESH_CLONE_DIR / filename
        assert file_path.is_file(), f"missing {filename}"
        assert file_path.stat().st_size > 0, f"empty {filename}"

    linked_targets = set(MD_LINK_RE.findall(readme_text))
    for filename in required_files:
        assert filename in linked_targets, f"{filename} is not linked from results/fresh_clone/README.md"

    for target in linked_targets:
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (FRESH_CLONE_DIR / target).resolve()
        assert resolved.is_file(), f"broken link target in results/fresh_clone/README.md: {target}"


def test_linux_and_macos_steps_all_exit_zero_and_match_readme() -> None:
    readme_text = README_PATH.read_text(encoding="utf-8")

    linux_steps = _parse_steps(FRESH_CLONE_DIR / LINUX_STEPS)
    expected_linux = [
        ("clone", 0, 5),
        ("reproduce_fast", 0, 83),
        ("reproduce", 0, 159),
        ("audit", 0, 202),
        ("test", 0, 263),
    ]
    assert linux_steps == expected_linux
    for step_name, exit_code, seconds in linux_steps:
        assert exit_code == 0, f"Linux step {step_name} failed with exit={exit_code}"
        assert f"{seconds} s" in readme_text, f"Linux timing {seconds} s missing from README.md"

    macos_steps = _parse_steps(FRESH_CLONE_DIR / MACOS_STEPS)
    assert [name for name, _, _ in macos_steps] == ["clone", "setup", "reproduce", "accept", "test"]
    for step_name, exit_code, seconds in macos_steps:
        assert exit_code == 0, f"macOS step {step_name} failed with exit={exit_code}"
        assert f"{seconds} s" in readme_text, f"macOS timing {seconds} s missing from README.md"


def test_linux_log_invariants_and_zero_leaked_keys() -> None:
    linux_log = (FRESH_CLONE_DIR / LINUX_LOG).read_text(encoding="utf-8")

    required_substrings = (
        "Rocky Linux 9.5",
        "x86_64",
        "Python 3.12.16",
        "no CANARY_* env; no .env",
        "2b301cea",
        "ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent",
        "SUMMARY: 4 PASS, 1 WARN, 0 FAIL",
        "+0.322",
        "opencode:google/gemini-4-carbon",
        "115 passed",
        "git status --porcelain: empty",
    )
    for needle in required_substrings:
        assert needle in linux_log, f"missing expected string in {LINUX_LOG}: {needle!r}"

    assert linux_log.count("git status --porcelain: empty") == 5
    assert linux_log.count("ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent") == 2

    google_key_prefix = "AI" + "za"
    openai_key_prefix = "s" + "k-"
    checked_files = (
        README_PATH,
        FRESH_CLONE_DIR / MACOS_LOG,
        FRESH_CLONE_DIR / MACOS_STEPS,
        FRESH_CLONE_DIR / LINUX_LOG,
        FRESH_CLONE_DIR / LINUX_STEPS,
    )
    for path in checked_files:
        content = path.read_text(encoding="utf-8")
        assert google_key_prefix not in content, f"leaked Google key prefix in {path.name}"
        assert openai_key_prefix not in content, f"leaked OpenAI key prefix in {path.name}"

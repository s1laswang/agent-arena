from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF_PATH = Path(__file__).resolve()
FRESH_CLONE_DIR = ROOT / "results" / "fresh_clone"
README_PATH = FRESH_CLONE_DIR / "README.md"

MACOS_LOG = "macos_justSilas_09e7363.log.txt"
MACOS_STEPS = "macos_justSilas_09e7363.steps.txt"
MACOS_COLD_LOG = "macos_cold_python_setup.log.txt"
LINUX_LOG = "linux_x86_64_justSilas_2b301cea.log.txt"
LINUX_STEPS = "linux_x86_64_justSilas_2b301cea.steps.txt"
AF_LOG = "linux_x86_64_afterquery_final_1bc3e281.log.txt"
AF_STEPS = "linux_x86_64_afterquery_final_1bc3e281.steps.txt"

H2 = chr(35) * 2
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

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

    for expected_heading in (
        f"{H2} macOS arm64 (`09e7363`)",
        f"{H2} Linux x86_64 (`2b301cea`)",
        f"{H2} Linux x86_64 at tag afterquery-final (`1bc3e281`)",
    ):
        assert expected_heading in readme_text, f"missing heading: {expected_heading}"

    required_files = (
        MACOS_LOG,
        MACOS_STEPS,
        LINUX_LOG,
        LINUX_STEPS,
        AF_LOG,
        AF_STEPS,
    )
    for filename in required_files:
        file_path = FRESH_CLONE_DIR / filename
        assert file_path.is_file(), f"missing {filename}"
        assert file_path.stat().st_size > 0, f"empty {filename}"

    af_log_path = FRESH_CLONE_DIR / AF_LOG
    assert af_log_path.stat().st_size < 40 * 1024
    assert "\x1b" not in af_log_path.read_text(encoding="utf-8")
    assert "\x1b" not in (FRESH_CLONE_DIR / AF_STEPS).read_text(encoding="utf-8")

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
        assert exit_code == 0, f"Linux 2b301cea step {step_name} failed with exit={exit_code}"
        assert f"{seconds} s" in readme_text, f"Linux 2b301cea timing {seconds} s missing from README.md"

    af_steps = _parse_steps(FRESH_CLONE_DIR / AF_STEPS)
    expected_af = [
        ("clone", 0, 3),
        ("reproduce_table", 0, 27),
        ("reproduce", 0, 118),
        ("audit", 0, 4),
        ("test_core", 0, 175),
    ]
    assert af_steps == expected_af
    for step_name, exit_code, seconds in af_steps:
        assert exit_code == 0, f"Linux 1bc3e281 step {step_name} failed with exit={exit_code}"
        assert f"{seconds} s" in readme_text, f"Linux 1bc3e281 timing {seconds} s missing from README.md"

    macos_steps = _parse_steps(FRESH_CLONE_DIR / MACOS_STEPS)
    assert [name for name, _, _ in macos_steps] == ["clone", "setup", "reproduce", "accept", "test"]
    for step_name, exit_code, seconds in macos_steps:
        assert exit_code == 0, f"macOS step {step_name} failed with exit={exit_code}"
        assert f"{seconds} s" in readme_text, f"macOS timing {seconds} s missing from README.md"


def test_linux_2b301cea_log_invariants() -> None:
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


def test_linux_afterquery_final_1bc3e281_log_invariants() -> None:
    af_log = (FRESH_CLONE_DIR / AF_LOG).read_text(encoding="utf-8")
    af_steps = _parse_steps(FRESH_CLONE_DIR / AF_STEPS)

    required_substrings = (
        "Rocky Linux 9.5",
        "x86_64",
        "Python 3.12.16",
        "UV=env; no CANARY_* env; no API keys; no .env",
        "--branch afterquery-final",
        "HEAD short: 1bc3e281",
        "commit: 1bc3e281dbfaa494a11e783d0c98369b41b2f675",
        "canary_pkg: /tmp/opencode/canary-af-check/canary/__init__.py",
        "REPRO_ANTICHEAT=0 make reproduce UV=env",
        "make reproduce UV=env",
        "1021 of 1031 committed episodes re-played, 1021 consistent; 51814 recorded tool results compared step by step, 0 differ.",
        "80 of 80 trials and 18 of 18 job summaries consistent.",
        "ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent",
        "HEADLINE (README table, recomputed from committed episodes; identical to data/runs/committed/v1.4/paired_table_gemini.md):",
        "paired on seeds 0-29 = 65% [24%, 98%] of the solver (luck-adjusted 72% [52%, 91%])",
        "TIERS_VERSION=v1.4 (a8f99c2537c91d72), TIERS_V13 (8df71cf570bb48bc)",
        "SUMMARY: 3 PASS, 1 WARN, 0 FAIL",
        "100 passed",
        "git status --porcelain: empty",
    )
    for needle in required_substrings:
        assert needle in af_log, f"missing expected string in {AF_LOG}: {needle!r}"

    assert af_log.count("git status --porcelain: empty") == 5
    assert af_log.count("HEADLINE (README table, recomputed from committed episodes; identical to data/runs/committed/v1.4/paired_table_gemini.md):") == 2
    assert af_log.count("ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent") == 1

    for step_name, exit_code, seconds in af_steps:
        footer = f"=== {step_name}: exit {exit_code}, {seconds} s"
        assert footer in af_log, f"missing step footer in {AF_LOG}: {footer!r}"


def test_readme_honesty_hygiene_and_zero_leaked_keys() -> None:
    readme_text = README_PATH.read_text(encoding="utf-8")
    assert EM_DASH not in readme_text
    assert EN_DASH not in readme_text
    assert "pre-registered" not in readme_text.lower()
    assert "post-hoc locked" in readme_text
    raw_idx = readme_text.index("65% [24%, 98%]")
    luck_idx = readme_text.index("72% [52%, 91%]")
    assert raw_idx < luck_idx

    self_src = SELF_PATH.read_text(encoding="utf-8")
    assert chr(35) not in self_src
    assert EM_DASH not in self_src
    assert EN_DASH not in self_src

    google_key_prefix = "AI" + "za"
    openai_key_prefix = "s" + "k-"
    anthropic_key_prefix = "s" + "k-ant-"
    checked_files = (
        README_PATH,
        FRESH_CLONE_DIR / MACOS_LOG,
        FRESH_CLONE_DIR / MACOS_STEPS,
        FRESH_CLONE_DIR / MACOS_COLD_LOG,
        FRESH_CLONE_DIR / LINUX_LOG,
        FRESH_CLONE_DIR / LINUX_STEPS,
        FRESH_CLONE_DIR / AF_LOG,
        FRESH_CLONE_DIR / AF_STEPS,
    )
    for path in checked_files:
        content = path.read_text(encoding="utf-8")
        assert google_key_prefix not in content, f"leaked Google key prefix in {path.name}"
        assert openai_key_prefix not in content, f"leaked OpenAI key prefix in {path.name}"
        assert anthropic_key_prefix not in content, f"leaked Anthropic key prefix in {path.name}"

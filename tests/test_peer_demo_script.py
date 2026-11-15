from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_PATH = ROOT / "DEMO.md"
STAGE_DEMO_PATH = ROOT / "docs" / "DEMO.md"
SELF_PATH = Path(__file__).resolve()

EM_DASH = "\u2014"
EN_DASH = "\u2013"
MINUS_SIGN = "\u2212"
HASH_CHAR = chr(35)
CO_AUTHOR_TAG = "Co-" + "Authored-By"

PENDING_DEMO_BUNDLE_PATHS = frozenset(
    {
        "docs/demo/replay.html",
        "docs/demo/living_office_v16.html",
        "docs/demo/canary_demo.mp4",
        "game/site",
    }
)

MD_LINK_RX = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_PATH_RX = re.compile(
    r"`((?:docs|scripts|tests|data|results|game|harbor|canary|configs)/[A-Za-z0-9_./-]+|DEMO\.md|README\.md|Makefile)`"
)


def test_demo_exists_and_line2_distinguishes_stage_runbook() -> None:
    assert DEMO_PATH.is_file(), "Root DEMO.md must exist"
    assert STAGE_DEMO_PATH.is_file(), "docs/DEMO.md stage runbook must remain intact"
    lines = DEMO_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 30
    line2 = lines[1]
    assert "DEMO.md" in line2
    assert "3-minute" in line2
    assert "10:45-12:45" in line2
    assert "peer-review" in line2
    assert "docs/DEMO.md" in line2
    assert "10-minute" in line2


def test_zero_em_dashes_pure_ascii_and_zero_python_comments() -> None:
    demo_text = DEMO_PATH.read_text(encoding="utf-8")
    py_text = SELF_PATH.read_text(encoding="utf-8")

    for label, text in (("DEMO.md", demo_text), ("test_peer_demo_script.py", py_text)):
        assert EM_DASH not in text, f"em dash found in {label}"
        assert EN_DASH not in text, f"en dash found in {label}"
        assert MINUS_SIGN not in text, f"unicode minus found in {label}"
        assert CO_AUTHOR_TAG not in text, f"co-author trailer found in {label}"
        assert all(ord(ch) < 128 for ch in text), f"non-ASCII character found in {label}"

    tokens = list(tokenize.generate_tokens(io.StringIO(py_text).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert not comments, f"Python comments forbidden: {comments}"
    assert HASH_CHAR not in py_text


def test_exact_three_minute_timeline_and_setup_surfaces() -> None:
    text = DEMO_PATH.read_text(encoding="utf-8")
    for window in ("0:00-0:45", "0:45-1:45", "1:45-2:30", "2:30-3:00"):
        assert window in text, f"missing timeline window {window}"

    pos = [text.index(w) for w in ("0:00-0:45", "0:45-1:45", "1:45-2:30", "2:30-3:00")]
    assert pos == sorted(pos), "timeline windows must appear in chronological order"

    for required in (
        "make game-serve",
        "http://localhost:8000/?seed=3000",
        "docs/demo/replay.html",
        "docs/demo/living_office_v16.html",
        "docs/demo/canary_demo.mp4",
        "uv run python scripts/demo_replay.py --seed 26 --verify",
        "Open the case file",
        "EMP",
        "DOC",
        "CAN",
        "ACC",
    ):
        assert required in text, f"missing required click/setup item: {required}"


def test_locked_gap_rehearsal_gpt55_and_seed6_seed26_verified_numbers() -> None:
    text = DEMO_PATH.read_text(encoding="utf-8")
    for token in (
        "README.md",
        "docs/SUBMISSION.md",
        "docs/reports/gap.md",
        "results/harbor/rehearsal/TABLE.md",
        "results/behaviour_compare_v1.4.md",
        "72% [52%, 91%]",
        "65% [24%, 98%]",
        "+0.322 +/- 0.199",
        "+0.499 +/- 0.119",
        "n=30",
        "0-29",
        "671ed96",
        "111% [99%, 127%]",
        "101% [85%, 119%]",
        "95% [62%, 140%]",
        "84% [65%, 106%]",
        "did not reproduce",
        "93%",
        "116%",
        "131%",
        "+0.506",
        "+0.472",
        "+0.585",
        "+0.626",
        "9` valid trials",
        "08:30",
        "28/29",
        "153%",
        "08:52",
        "gpt-5.5",
        "101% [79%, 140%]",
        "+0.504 +/- 0.064",
        "84% [67%, 103%]",
        "cf394894",
        "Seed 6 Caught",
        "e34",
        "+0.73",
        "57",
        "+0.71",
        "52",
        "Seed 26 Fooled",
        "e08",
        "43",
        "0.48 -> 0.03",
        "S1",
        "e04",
        "-1.00",
        "+0.69",
        "11",
    ):
        assert token in text, f"missing verified metric or identifier: {token}"


def test_integrity_and_honest_negative_disclosures() -> None:
    text = DEMO_PATH.read_text(encoding="utf-8")
    for token in (
        "do_nothing = stop_early = 0.000",
        "52 attacks",
        "docs/EXPLOITS.md",
        "1,034",
        "results/redteam_1000/summary.md",
        "12/12",
        "docs/reports/integrity.md",
        "make reproduce",
        "Day 1",
        "Day 7",
        "Day 14",
        "off-by-default preview",
        "did NOT pass the Gate B gap gate",
        "bar not met",
        "-0.050 +/- 0.049",
        "0.000",
        "DAgger round 1",
        "-0.542 +/- 0.214",
        "n=50",
    ):
        assert token in text, f"missing integrity or honest negative disclosure: {token}"


def test_rehearsal_gpt55_and_dagger_match_aa1c679e_artifacts() -> None:
    readme_md = (ROOT / "README.md").read_text(encoding="utf-8")
    submission_md = (ROOT / "docs/SUBMISSION.md").read_text(encoding="utf-8")
    rehearsal_md = (ROOT / "results/harbor/rehearsal/TABLE.md").read_text(encoding="utf-8")
    behaviour_md = (ROOT / "results/behaviour_compare_v1.4.md").read_text(encoding="utf-8")

    for tok in ("93%", "116%", "131%", "+0.472", "+0.585", "+0.626", "+0.506", "28 of 29"):
        assert tok in readme_md, f"README.md missing rehearsal token {tok}"
    for tok in ("93%", "116%", "131%", "+0.626", "9 valid trials", "cf394894", "101% [79%, 140%]"):
        assert tok in submission_md, f"docs/SUBMISSION.md missing token {tok}"
    for tok in ("08:52", "9 valid trials", "+0.626", "131%", "93%", "116%"):
        assert tok in rehearsal_md, f"results/harbor/rehearsal/TABLE.md missing token {tok}"
    for tok in ("+0.504", "17.2", "4.2", "8.5", "68.0"):
        assert tok in behaviour_md, f"results/behaviour_compare_v1.4.md missing token {tok}"
    assert "0.542" in readme_md and "n=50" in readme_md

    gpt_eps_path = ROOT / "data/runs/committed/v1.4/opencode-gpt-5.5/hard/episodes.jsonl"
    gpt_eps = [
        json.loads(line)
        for line in gpt_eps_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(gpt_eps) == 30
    assert sorted(ep["seed"] for ep in gpt_eps) == list(range(30))
    accused_eps = [ep for ep in gpt_eps if ep.get("accused") is not None]
    assert len(accused_eps) == 28
    assert sum(1 for ep in accused_eps if ep.get("correct")) == 28


def test_all_relative_links_and_repo_paths_are_valid() -> None:
    text = DEMO_PATH.read_text(encoding="utf-8")
    links = MD_LINK_RX.findall(text)
    assert len(links) >= 8
    for target in links:
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        rel_str = target.split(chr(35), 1)[0]
        assert rel_str, f"empty link target: {target}"
        assert not rel_str.startswith("/"), f"link must be relative: {target}"
        assert "results/latest" not in rel_str, f"must not link to gitignored path: {target}"
        resolved = (ROOT / rel_str).resolve()
        assert resolved.exists(), f"broken markdown link in DEMO.md: {rel_str}"

    code_paths = set(BACKTICK_PATH_RX.findall(text))
    assert {"docs/demo/replay.html", "docs/demo/living_office_v16.html", "docs/demo/canary_demo.mp4"}.issubset(
        code_paths
    )
    for rel_str in sorted(code_paths):
        if rel_str in PENDING_DEMO_BUNDLE_PATHS:
            continue
        assert (ROOT / rel_str).exists(), f"missing repo path referenced in DEMO.md: {rel_str}"


def test_seed6_seed26_and_headline_match_committed_artifacts() -> None:
    text = DEMO_PATH.read_text(encoding="utf-8")
    paired_md = (ROOT / "data/runs/committed/v1.4/paired_table_gemini.md").read_text(encoding="utf-8")
    assert "65% [24%, 98%]" in paired_md and "72% [52%, 91%]" in paired_md
    assert "111% [99%, 127%]" in paired_md and "101% [85%, 119%]" in paired_md

    def load_seed(paths: list[Path], seed: int) -> dict:
        for p in paths:
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ep = json.loads(line)
                    if ep["seed"] == seed:
                        return ep
        raise AssertionError(f"seed {seed} missing")

    gem_paths = [ROOT / "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"]
    sol_paths = [
        ROOT / "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
        ROOT / "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
    ]

    g6 = load_seed(gem_paths, 6)
    s6 = load_seed(sol_paths, 6)
    assert (round(g6["score"], 2), g6["final_day"], len(g6["steps"]), g6["accused"], g6["correct"]) == (
        0.73,
        6,
        57,
        "e34",
        True,
    )
    assert (round(s6["score"], 2), s6["final_day"], len(s6["steps"]), s6["accused"], s6["correct"]) == (
        0.71,
        6,
        52,
        "e34",
        True,
    )

    g26 = load_seed(gem_paths, 26)
    s26 = load_seed(sol_paths, 26)
    assert (round(g26["score"], 2), g26["final_day"], len(g26["steps"]), g26["accused"], g26["correct"]) == (
        -1.00,
        10,
        91,
        "e04",
        False,
    )
    assert (round(s26["score"], 2), s26["final_day"], len(s26["steps"]), s26["accused"], s26["correct"]) == (
        0.69,
        7,
        60,
        "e08",
        True,
    )
    assert f"{g6['score']:+.2f}" in text and f"{s6['score']:+.2f}" in text
    assert f"{g26['score']:+.2f}" in text and f"{s26['score']:+.2f}" in text


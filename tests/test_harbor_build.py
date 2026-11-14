"""harbor/build.py dataset selection (PLAN-95 A1; HARNESS).

No flags = the judge set: tier hard, judge seeds 900000-900009 (10 tasks), fixed before any frontier run on them.
The flags still build medium/easy and any other judge or held-out seed.
"""
from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _build():
    spec = importlib.util.spec_from_file_location("harbor_build", ROOT / "harbor/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _names(out: Path) -> list[str]:
    return sorted(p.name for p in out.glob("canary-*"))


def test_default_build_is_the_hard_judge_set(tmp_path, capsys):
    b = _build()
    assert (b.JUDGE_SET_TIERS, b.JUDGE_SET_SEEDS) == ("hard", "900000-900009")
    assert b.main(["--out", str(tmp_path)]) == 0
    assert _names(tmp_path) == [f"canary-hard-{s}" for s in range(900000, 900010)]
    assert "= the judge set" in capsys.readouterr().out
    for t in tmp_path.glob("canary-*"):
        cfg = tomllib.loads((t / "task.toml").read_text())
        assert cfg["metadata"]["tier"] == "hard" and cfg["task"]["name"] == f"canary/{t.name.removeprefix('canary-')}"


@pytest.mark.parametrize("argv,expect", [
    (["--tiers", "medium", "--seeds", "900000"], ["canary-medium-900000"]),
    (["--tiers", "easy,medium", "--seeds", "900003-900004"],
     ["canary-easy-900003", "canary-easy-900004", "canary-medium-900003", "canary-medium-900004"]),
    (["--seeds", "900020"], ["canary-hard-900020"]),
    (["--tiers", "medium", "--seeds", "800001"], ["canary-medium-800001"]),
])
def test_flags_still_build_other_tiers_and_seeds(tmp_path, argv, expect):
    assert _build().main(argv + ["--out", str(tmp_path)]) == 0
    assert _names(tmp_path) == expect


def test_seeds_judge_still_means_all_40():
    from canary.rules import JUDGE_SEEDS
    assert _build().parse_seeds("judge") == list(JUDGE_SEEDS) and len(JUDGE_SEEDS) == 40

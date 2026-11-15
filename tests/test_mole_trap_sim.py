from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import tokenize

import pytest

from canary.forge.rl_mole import RLMole, default_like_params
from canary.mole.dsl import DEFAULT_STRATEGY
from canary.mole.trap_sim import (
    TRAP_MATRIX_STRATEGIES,
    default_trap_investigators,
    main,
    render_trap_matrix_markdown,
    run_trap_matrix,
    simulate_trap_cell,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "reports" / "mole_trap_matrix_v14.md"


def test_hygiene_and_zero_social_imports() -> None:
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_ref = "solver_" + "v2"

    for rel in ("canary/mole/trap_sim.py", "tests/test_mole_trap_sim.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert hash_ch not in src, rel
        assert em_dash not in src, rel
        assert en_dash not in src, rel
        assert forbidden_ref not in src, rel
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], (rel, comments)

    report_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert em_dash not in report_txt
    assert en_dash not in report_txt
    assert forbidden_ref not in report_txt
    assert "Mole Trap x Investigator Matrix (v1.4 Offline Simulation)" in report_txt
    assert "Medium-Tier Cross-Check" in report_txt

    tree = ast.parse((ROOT / "canary/mole/trap_sim.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "social" not in node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "social" not in alias.name


def test_seed_hygiene_and_input_validation() -> None:
    inv = default_trap_investigators("hard")
    for bad_seed in (0, 29, 800_000, 900_000, -1):
        with pytest.raises(ValueError, match="forbidden simulation seed"):
            simulate_trap_cell(DEFAULT_STRATEGY, inv["solver"], "hard", [bad_seed])
        with pytest.raises(ValueError, match="forbidden simulation seed"):
            run_trap_matrix(strategies={"default_v0": DEFAULT_STRATEGY}, tier="hard", seeds=[bad_seed])

    with pytest.raises(ValueError, match="must not be empty"):
        simulate_trap_cell(DEFAULT_STRATEGY, inv["solver"], "hard", [])

    with pytest.raises(ValueError, match="integer"):
        simulate_trap_cell(DEFAULT_STRATEGY, inv["solver"], "hard", [True])

    with pytest.raises(ValueError, match="unknown tier"):
        default_trap_investigators("nonexistent")


def test_trap_matrix_small_slice_and_cli_check_roundtrip(tmp_path: Path) -> None:
    inv = default_trap_investigators("hard")
    subset_inv = {
        k: inv[k]
        for k in ("solver", "gemini_carbon_proxy", "codex_horizon_proxy", "heuristic", "hinted_heuristic", "grok_tactics", "logs_only")
    }
    subset_strats = {
        "default_v0": TRAP_MATRIX_STRATEGIES["default_v0"],
        "reactive_canary_lag": TRAP_MATRIX_STRATEGIES["reactive_canary_lag"],
    }
    rep = run_trap_matrix(
        strategies=subset_strats,
        tier="hard",
        seeds=[6302],
        investigators=subset_inv,
        workers=1,
    )
    assert rep["tier"] == "hard"
    assert rep["n_seeds"] == 1
    assert set(rep["strategies"].keys()) == set(subset_strats.keys())
    for srow in rep["strategies"].values():
        assert srow["cells"]["logs_only"]["mean_score"] < 0.0
        assert -1.0 <= srow["cells"]["solver"]["luck_adjusted_score"] <= 1.0

    rl_cell = simulate_trap_cell(
        RLMole(default_like_params(seed=0), name="rl_default"),
        default_trap_investigators("medium")["solver"],
        "medium",
        [6320],
    )
    assert -1.0 <= rl_cell["luck_adjusted_score"] <= 1.0

    md = render_trap_matrix_markdown(rep)
    assert "reactive_canary_lag" in md
    assert chr(0x2014) not in md
    assert chr(0x2013) not in md

    out_json = tmp_path / "matrix_slice.json"
    rc_gen = main(["--tier", "medium", "--seeds", "6320-6320", "--workers", "1", "--json", "--out", str(out_json)])
    assert rc_gen == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["n_seeds"] == 1
    rc_chk = main(["--tier", "medium", "--seeds", "6320-6320", "--workers", "1", "--check", str(out_json)])
    assert rc_chk == 0

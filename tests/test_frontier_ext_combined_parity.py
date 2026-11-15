from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

from canary.analysis.accuse import audit_episode
from canary.analysis.gap import mean_ci
from canary.analysis.tags import to_result

ROOT = Path(__file__).resolve().parents[1]
COMMITTED_V14 = ROOT / "data" / "runs" / "committed" / "v1.4"
COMMITTED_G1_PATH = COMMITTED_V14 / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
PRIMARY_HARD_PATH = COMMITTED_V14 / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
REF_ROOT = COMMITTED_V14 / "reference"

EXT_REPL_ROOT = ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext"
FLEET_EXT_PATH = EXT_REPL_ROOT / "hard" / "episodes.jsonl"
EXT8_COMBINED_JSON = EXT_REPL_ROOT / "paired_table_ext8_combined.json"
POOLED38_JSON = EXT_REPL_ROOT / "paired_table_pooled38.json"

COMMITTED_G1_SEEDS = [34, 37]
FLEET_SEEDS = [30, 34, 42, 45, 48, 57, 58]
FLEET_NON_OVERLAPPING_SEEDS = [30, 42, 45, 48, 57, 58]
EXT8_SEEDS = [30, 34, 37, 42, 45, 48, 57, 58]
PRIMARY_SEEDS = list(range(30))
POOLED38_SEEDS = PRIMARY_SEEDS + EXT8_SEEDS

EXPECTED_EXT8_POSTERIORS = {
    30: 0.909,
    34: 0.979,
    37: 0.981,
    42: 0.969,
    45: 0.973,
    48: 0.916,
    57: 0.970,
    58: 0.908,
}

EXPECTED_EXT8_LUCK_ADJUSTED = {
    30: 0.39986,
    34: 0.75241,
    37: 0.66770,
    42: 0.52133,
    45: 0.54707,
    48: 0.47476,
    57: 0.70720,
    58: 0.43464,
}


def _load_script(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_valid_episodes(path: Path) -> list[dict[str, Any]]:
    assert path.is_file()
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        if (ep.get("meta") or {}).get("valid") is False:
            continue
        out.append(ep)
    return out


def _load_solver_hard_by_seed() -> tuple[list[Path], dict[int, dict[str, Any]]]:
    shard_paths = sorted(REF_ROOT.glob("solver-hard-*/episodes.jsonl"))
    assert [p.parent.name for p in shard_paths] == [
        "solver-hard-20261114-121126",
        "solver-hard-seeds20to29",
        "solver-hard-seeds30to59",
    ]
    by_seed: dict[int, dict[str, Any]] = {}
    for shard_path in shard_paths:
        for ep in _read_valid_episodes(shard_path):
            assert ep["tier"] == "hard"
            assert ep["agent"] == "solver"
            seed = ep["seed"]
            assert seed not in by_seed
            by_seed[seed] = ep
    assert sorted(by_seed) == list(range(60))
    return shard_paths, by_seed


def _deduplicate_ext8(
    committed_g1: list[dict[str, Any]],
    fleet_eps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    committed_seeds = {ep["seed"] for ep in committed_g1}
    non_overlapping_fleet = [ep for ep in fleet_eps if ep["seed"] not in committed_seeds]
    combined = sorted(committed_g1 + non_overlapping_fleet, key=lambda ep: ep["seed"])
    return non_overlapping_fleet, combined


def _audit_p_accused(ep: dict[str, Any], cache: dict[tuple[str, str, int, int], float | None]) -> float | None:
    if not ep.get("accused"):
        return None
    key = (ep["agent"], ep["tier"], ep["seed"], len(ep.get("steps") or []))
    if key not in cache:
        cache[key] = audit_episode(to_result(ep))["p_accused"]
    return cache[key]


def _luck_adjusted_score(ep: dict[str, Any], cache: dict[tuple[str, str, int, int], float | None]) -> float:
    if not ep.get("accused"):
        return 0.0
    p = _audit_p_accused(ep, cache)
    meta = ep.get("meta") or {}
    v = meta.get("V", meta.get("V_final"))
    assert p is not None and v is not None
    return p * float(v) - (1.0 - p)


def _compute_cohort_metrics(
    episodes: list[dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
    boot_ratio_fn,
    cache: dict[tuple[str, str, int, int], float | None],
    is_solver: bool = False,
) -> dict[str, Any]:
    es = sorted(episodes, key=lambda ep: ep["seed"])
    scores = [float(ep["score"]) for ep in es]
    sol_scores = [float(solver_by_seed[ep["seed"]]["score"]) for ep in es]
    mean_score, ci_score = mean_ci(scores)
    sol_mean = sum(sol_scores) / len(sol_scores)
    diff_mean, diff_ci = mean_ci([a - b for a, b in zip(scores, sol_scores)])
    accused_eps = [ep for ep in es if ep.get("accused")]
    ps = [p for p in (_audit_p_accused(ep, cache) for ep in accused_eps) if p is not None]
    pe = [_luck_adjusted_score(ep, cache) for ep in es]
    pe_sol = [_luck_adjusted_score(solver_by_seed[ep["seed"]], cache) for ep in es]
    pe_ratio = sum(pe) / sum(pe_sol)
    if is_solver:
        ratio_lo, ratio_hi = float("nan"), float("nan")
        pe_lo, pe_hi = float("nan"), float("nan")
    else:
        ratio_lo, ratio_hi = boot_ratio_fn(scores, sol_scores, B=10000, rng_seed=0)
        pe_lo, pe_hi = boot_ratio_fn(pe, pe_sol, B=10000, rng_seed=0)
    return {
        "n": len(es),
        "seeds": [ep["seed"] for ep in es],
        "mean": mean_score,
        "ci": ci_score,
        "accuracy": sum(bool(ep["correct"]) for ep in es) / len(es),
        "accused_rate": len(accused_eps) / len(es),
        "p_accused": sum(ps) / len(ps),
        "n_p": len(ps),
        "accuse_day": sum(ep["final_day"] for ep in accused_eps) / max(1, len(accused_eps)),
        "solver_same_seeds": sol_mean,
        "ratio": mean_score / sol_mean,
        "ratio_lo": ratio_lo,
        "ratio_hi": ratio_hi,
        "diff": diff_mean,
        "diff_ci": diff_ci,
        "post_expected": sum(pe) / len(pe),
        "post_expected_ratio": pe_ratio,
        "post_expected_lo": pe_lo,
        "post_expected_hi": pe_hi,
        "solver_post_expected": sum(pe_sol) / len(pe_sol),
    }


def _assert_row_exact(
    got_metrics: dict[str, Any],
    want_row: dict[str, Any],
    expected_label: str,
    expected_group: str,
    expected_agent: str,
) -> None:
    assert want_row["label"] == expected_label
    assert want_row["group"] == expected_group
    assert want_row["agent"] == expected_agent
    assert want_row["tier"] == "hard"
    expected_keys = {"label", "group", "agent", "tier"} | set(got_metrics.keys())
    assert set(want_row.keys()) == expected_keys
    for key, got_val in got_metrics.items():
        want_val = want_row[key]
        if isinstance(got_val, float) and math.isnan(got_val):
            assert isinstance(want_val, float) and math.isnan(want_val)
        elif isinstance(got_val, float):
            assert abs(got_val - float(want_val)) < 1e-12
        else:
            assert got_val == want_val


def test_deterministic_loading_and_deduplication_rule(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    vr = _load_script("verify_replay", "scripts/verify_replay.py")

    committed_g1 = _read_valid_episodes(COMMITTED_G1_PATH)
    fleet_eps = _read_valid_episodes(FLEET_EXT_PATH)
    primary_eps = _read_valid_episodes(PRIMARY_HARD_PATH)
    shard_paths, solver_by_seed = _load_solver_hard_by_seed()

    assert [ep["seed"] for ep in committed_g1] == COMMITTED_G1_SEEDS
    assert [ep["seed"] for ep in fleet_eps] == FLEET_SEEDS
    assert [ep["seed"] for ep in primary_eps] == PRIMARY_SEEDS
    assert [_read_valid_episodes(p)[0]["seed"] for p in shard_paths] == [0, 20, 30]
    assert [_read_valid_episodes(p)[-1]["seed"] for p in shard_paths] == [19, 29, 59]

    for ep in committed_g1 + fleet_eps + primary_eps:
        assert ep["tier"] == "hard"
        assert ep["agent"] == "opencode:google/gemini-4-carbon"

    overlap = sorted({ep["seed"] for ep in committed_g1} & {ep["seed"] for ep in fleet_eps})
    assert overlap == [34]

    non_overlapping_fleet, dedup_ext8 = _deduplicate_ext8(committed_g1, fleet_eps)
    assert [ep["seed"] for ep in non_overlapping_fleet] == FLEET_NON_OVERLAPPING_SEEDS
    assert len(non_overlapping_fleet) == 6
    assert [ep["seed"] for ep in dedup_ext8] == EXT8_SEEDS
    assert len(dedup_ext8) == 8

    committed_by_seed = {ep["seed"]: ep for ep in committed_g1}
    fleet_by_seed = {ep["seed"]: ep for ep in fleet_eps}
    dedup_by_seed = {ep["seed"]: ep for ep in dedup_ext8}
    assert dedup_by_seed[34] == committed_by_seed[34]
    assert dedup_by_seed[34]["score"] == 0.79
    assert fleet_by_seed[34]["score"] == 0.82
    assert dedup_by_seed[34]["final_day"] == 5
    assert fleet_by_seed[34]["final_day"] == 8

    for ep in dedup_ext8:
        rep = vr.replay_episode(ep)
        assert abs(rep["score"] - ep["score"]) < 1e-9
        assert rep["accused"] == ep["accused"]
        assert rep["correct"] == ep["correct"]
        assert rep["final_day"] == ep["final_day"]
        assert ep["seed"] in solver_by_seed


def test_accuse_posteriors_and_luck_adjusted_scores_on_ext8():
    pv13 = _load_script("paired_v13", "scripts/paired_v13.py")

    committed_g1 = _read_valid_episodes(COMMITTED_G1_PATH)
    fleet_eps = _read_valid_episodes(FLEET_EXT_PATH)
    _, solver_by_seed = _load_solver_hard_by_seed()
    _, dedup_ext8 = _deduplicate_ext8(committed_g1, fleet_eps)

    cache: dict[tuple[str, str, int, int], float | None] = {}
    ext8_posteriors: dict[int, float] = {}
    ext8_luck: dict[int, float] = {}

    for ep in dedup_ext8:
        seed = ep["seed"]
        aud = audit_episode(to_result(ep))
        assert aud["tier"] == "hard"
        assert aud["seed"] == seed
        assert aud["agent"] == "opencode:google/gemini-4-carbon"
        assert aud["end"] == "accused"
        assert aud["accused"] == ep["accused"]
        assert aud["correct"] is True
        assert aud["day"] == ep["final_day"]
        assert aud["verdict"] == "justified"
        assert aud["p_accused"] == aud["p_top"]
        assert aud["p_accused"] == EXPECTED_EXT8_POSTERIORS[seed]

        luck = _luck_adjusted_score(ep, cache)
        assert abs(luck - EXPECTED_EXT8_LUCK_ADJUSTED[seed]) < 1e-12
        assert abs(luck - pv13.post_expected(ep)) < 1e-12
        ext8_posteriors[seed] = aud["p_accused"]
        ext8_luck[seed] = luck

    fleet_seed34 = next(ep for ep in fleet_eps if ep["seed"] == 34)
    fleet_seed34_audit = audit_episode(to_result(fleet_seed34))
    assert fleet_seed34_audit["p_accused"] == 0.650
    assert abs(_luck_adjusted_score(fleet_seed34, cache) - 0.183) < 1e-12

    solver_ext8_luck = [_luck_adjusted_score(solver_by_seed[s], cache) for s in EXT8_SEEDS]
    for s, got_luck in zip(EXT8_SEEDS, solver_ext8_luck):
        assert abs(got_luck - pv13.post_expected(solver_by_seed[s])) < 1e-12

    ext8_table = json.loads(EXT8_COMBINED_JSON.read_text(encoding="utf-8"))
    ext8_row = ext8_table[0]
    assert abs(sum(ext8_posteriors.values()) / 8 - ext8_row["p_accused"]) < 1e-12
    assert abs(sum(ext8_luck.values()) / 8 - ext8_row["post_expected"]) < 1e-12
    assert abs(sum(solver_ext8_luck) / 8 - ext8_row["solver_post_expected"]) < 1e-12
    assert abs((sum(ext8_luck.values()) / sum(solver_ext8_luck)) - ext8_row["post_expected_ratio"]) < 1e-12


def test_exact_agreement_with_ext8_combined_and_pooled38_tables():
    pv13 = _load_script("paired_v13", "scripts/paired_v13.py")

    committed_g1 = _read_valid_episodes(COMMITTED_G1_PATH)
    fleet_eps = _read_valid_episodes(FLEET_EXT_PATH)
    primary_eps = _read_valid_episodes(PRIMARY_HARD_PATH)
    _, solver_by_seed = _load_solver_hard_by_seed()

    _, dedup_ext8 = _deduplicate_ext8(committed_g1, fleet_eps)
    pooled38_eps = sorted(primary_eps + dedup_ext8, key=lambda ep: ep["seed"])
    assert [ep["seed"] for ep in pooled38_eps] == POOLED38_SEEDS

    cache: dict[tuple[str, str, int, int], float | None] = {}

    got_ext8 = _compute_cohort_metrics(dedup_ext8, solver_by_seed, pv13.boot_ratio, cache)
    got_solver_30_59 = _compute_cohort_metrics(
        [solver_by_seed[s] for s in range(30, 60)],
        solver_by_seed,
        pv13.boot_ratio,
        cache,
        is_solver=True,
    )
    got_primary = _compute_cohort_metrics(primary_eps, solver_by_seed, pv13.boot_ratio, cache)
    got_pooled38 = _compute_cohort_metrics(pooled38_eps, solver_by_seed, pv13.boot_ratio, cache)
    got_solver_0_59 = _compute_cohort_metrics(
        [solver_by_seed[s] for s in range(60)],
        solver_by_seed,
        pv13.boot_ratio,
        cache,
        is_solver=True,
    )

    ext8_table = json.loads(EXT8_COMBINED_JSON.read_text(encoding="utf-8"))
    assert len(ext8_table) == 2
    _assert_row_exact(
        got_ext8,
        ext8_table[0],
        expected_label="OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59)",
        expected_group="v1.4/opencode-gemini-4-carbon-ext",
        expected_agent="opencode:google/gemini-4-carbon",
    )
    _assert_row_exact(
        got_solver_30_59,
        ext8_table[1],
        expected_label="reference solver",
        expected_group="v1.4/reference",
        expected_agent="solver",
    )

    pooled38_table = json.loads(POOLED38_JSON.read_text(encoding="utf-8"))
    hard_rows = {(row["group"], row["label"]): row for row in pooled38_table if row["tier"] == "hard"}

    primary_label = "OpenCode + gemini-4-carbon over MCP (judges' shape)"
    ext8_label = "OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59)"
    pooled_label = "OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)"

    _assert_row_exact(
        got_primary,
        hard_rows[("v1.4/opencode-gemini-4-carbon", primary_label)],
        expected_label=primary_label,
        expected_group="v1.4/opencode-gemini-4-carbon",
        expected_agent="opencode:google/gemini-4-carbon",
    )
    _assert_row_exact(
        got_ext8,
        hard_rows[("v1.4/opencode-gemini-4-carbon-ext", ext8_label)],
        expected_label=ext8_label,
        expected_group="v1.4/opencode-gemini-4-carbon-ext",
        expected_agent="opencode:google/gemini-4-carbon",
    )
    assert ext8_table[0] == hard_rows[("v1.4/opencode-gemini-4-carbon-ext", ext8_label)]
    _assert_row_exact(
        got_pooled38,
        hard_rows[("v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext", pooled_label)],
        expected_label=pooled_label,
        expected_group="v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
        expected_agent="opencode:google/gemini-4-carbon",
    )
    _assert_row_exact(
        got_solver_0_59,
        hard_rows[("v1.4/reference", "reference solver")],
        expected_label="reference solver",
        expected_group="v1.4/reference",
        expected_agent="solver",
    )

    fleet_first_ext8 = sorted(
        fleet_eps + [ep for ep in committed_g1 if ep["seed"] not in {e["seed"] for e in fleet_eps}],
        key=lambda ep: ep["seed"],
    )
    wrong_metrics = _compute_cohort_metrics(fleet_first_ext8, solver_by_seed, pv13.boot_ratio, cache)
    assert abs(wrong_metrics["mean"] - ext8_table[0]["mean"]) > 1e-3
    assert abs(wrong_metrics["p_accused"] - ext8_table[0]["p_accused"]) > 1e-2
    assert abs(wrong_metrics["post_expected"] - ext8_table[0]["post_expected"]) > 1e-2

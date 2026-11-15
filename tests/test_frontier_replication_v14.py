from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

from canary.analysis.gap import load_runs, mean_ci

ROOT = Path(__file__).resolve().parents[1]
EXT_ROOT = ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext"
EXT_HARD = EXT_ROOT / "hard"
COMMITTED_V14 = ROOT / "data" / "runs" / "committed" / "v1.4"
COMMITTED_PRIMARY_HARD = COMMITTED_V14 / "opencode-gemini-4-carbon" / "hard"
COMMITTED_EXT_HARD = COMMITTED_V14 / "opencode-gemini-4-carbon-ext" / "hard"
REF_ROOT = COMMITTED_V14 / "reference"
REF_HARD = REF_ROOT / "solver-hard-seeds30to59"
EXPECTED_SEEDS = [30, 34, 42, 45, 48, 57, 58]
COMMITTED_G1_SEEDS = [34, 37]
FLEET_NEW_SEEDS = [30, 42, 45, 48, 57, 58]
EXT8_SEEDS = [30, 34, 37, 42, 45, 48, 57, 58]
POOLED38_SEEDS = list(range(30)) + EXT8_SEEDS
FINITE_STAT_KEYS = (
    "mean",
    "ci",
    "accuracy",
    "accused_rate",
    "p_accused",
    "accuse_day",
    "solver_same_seeds",
    "ratio",
    "ratio_lo",
    "ratio_hi",
    "diff",
    "diff_ci",
    "post_expected",
    "post_expected_ratio",
    "post_expected_lo",
    "post_expected_hi",
    "solver_post_expected",
)


def _load_script(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_jsonl(path: Path) -> list[dict]:
    assert path.is_file()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_frontier_replication_v14_manifest_and_transcripts():
    episodes = _read_jsonl(EXT_HARD / "episodes.jsonl")
    assert [ep["seed"] for ep in episodes] == EXPECTED_SEEDS
    for ep in episodes:
        assert ep["tier"] == "hard"
        assert ep["agent"] == "opencode:google/gemini-4-carbon"
        assert ep["end_reason"] == "accused"
        assert (ep.get("meta") or {}).get("valid") is True
        assert len(ep.get("steps") or []) > 0

    meta = json.loads((EXT_HARD / "meta.json").read_text(encoding="utf-8"))
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["seeds"] == EXPECTED_SEEDS

    transcripts_dir = EXT_HARD / "transcripts"
    assert transcripts_dir.is_dir()
    tr_files = sorted(transcripts_dir.iterdir())
    assert [p.name for p in tr_files] == [f"{seed}.txt" for seed in EXPECTED_SEEDS]
    assert all(p.is_file() and p.stat().st_size > 0 for p in tr_files)

    tags = json.loads((EXT_ROOT / "tags.json").read_text(encoding="utf-8"))
    assert tags["opencode:google/gemini-4-carbon"]["episodes"] == len(EXPECTED_SEEDS)
    assert (EXT_ROOT / "accuse.md").is_file()


def test_frontier_replication_v14_replays_and_pairs_with_reference(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    vr = _load_script("verify_replay", "scripts/verify_replay.py")
    gvr = _load_script("gap_vs_reference", "scripts/gap_vs_reference.py")

    ext_path = EXT_HARD / "episodes.jsonl"
    ref_path = REF_HARD / "episodes.jsonl"
    episodes = _read_jsonl(ext_path)
    for ep in episodes:
        rep = vr.replay_episode(ep)
        assert abs(rep["score"] - ep["score"]) < 1e-9
        assert rep["accused"] == ep["accused"]
        assert rep["correct"] == ep["correct"]
        assert rep["final_day"] == ep["final_day"]
    assert vr.main([str(ext_path)]) == 0

    ref_episodes = _read_jsonl(ref_path)
    assert [ep["seed"] for ep in ref_episodes] == list(range(30, 60))
    ref_by_seed = {ep["seed"]: ep for ep in ref_episodes}
    for ep in episodes:
        ref_ep = ref_by_seed[ep["seed"]]
        assert ref_ep["tier"] == "hard"
        assert ref_ep["agent"] == "solver"
        rep_ref = vr.replay_episode(ref_ep)
        assert abs(rep_ref["score"] - ref_ep["score"]) < 1e-9
        assert rep_ref["accused"] == ref_ep["accused"]

    ext_map, ext_invalid = gvr.collect([str(ext_path)])
    ref_map, ref_invalid = gvr.collect([str(ref_path)])
    assert ext_invalid == 0 and ref_invalid == 0
    expected_keys = [("hard", seed) for seed in EXPECTED_SEEDS]
    assert sorted(ext_map.keys()) == expected_keys
    assert all(key in ref_map for key in expected_keys)
    ext_scores = [ext_map[key]["score"] for key in expected_keys]
    ref_scores = [ref_map[key]["score"] for key in expected_keys]
    boot = gvr.paired_bootstrap(ext_scores, ref_scores, n_boot=2000)
    assert boot["n"] == len(EXPECTED_SEEDS)
    assert math.isfinite(boot["ratio"]) and boot["ratio"] > 0.0
    assert boot["diff_ci"][0] <= boot["diff"] <= boot["diff_ci"][1]


def _parse_md_rows(path: Path) -> list[list[str]]:
    assert path.is_file()
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip().startswith("|")]
    assert len(lines) >= 3
    return [[cell.strip() for cell in ln.strip("|").split("|")] for ln in lines[2:]]


def _assert_md_matches_json(md_path: Path, json_rows: list[dict]) -> None:
    md_rows = _parse_md_rows(md_path)
    assert len(md_rows) == len(json_rows)
    by_key = {(r["tier"], r["label"]): r for r in json_rows}
    assert len(by_key) == len(json_rows)
    for cells in md_rows:
        assert len(cells) == 13
        row = by_key[(cells[0], cells[1])]
        assert cells[2] == str(row["n"])
        assert cells[3].startswith(f"{row['mean']:.3f} ")
        assert cells[3].endswith(f" {row['ci']:.3f}")
        assert cells[4] == f"{row['accuracy']:.2f}"
        assert cells[5] == f"{row['accused_rate']:.2f}"
        assert cells[6] == f"{row['accuse_day']:.1f}"
        assert cells[8] == f"{row['solver_same_seeds']:.3f}"
        assert cells[11] == f"{row['post_expected']:.3f}"
        if row["agent"] == "solver":
            assert cells[9] == "-"
            assert cells[10] == "-"
            assert cells[12] == "-"
        else:
            assert cells[10].startswith(f"{row['diff']:.3f} ")
            assert cells[10].endswith(f" {row['diff_ci']:.3f}")


def _assert_cohort_stats(
    row: dict,
    episodes: list[dict],
    solver_by_seed: dict[int, dict],
    expected_seeds: list[int],
) -> None:
    assert row["tier"] == "hard"
    assert row["agent"] == "opencode:google/gemini-4-carbon"
    assert row["n"] == len(expected_seeds)
    assert row["seeds"] == expected_seeds
    assert [ep["seed"] for ep in episodes] == expected_seeds
    for key in FINITE_STAT_KEYS:
        val = row[key]
        assert isinstance(val, (int, float)) and not isinstance(val, bool)
        assert math.isfinite(val)

    scores = [ep["score"] for ep in episodes]
    sol_scores = [solver_by_seed[ep["seed"]]["score"] for ep in episodes]
    diffs = [x - y for x, y in zip(scores, sol_scores)]

    exp_mean, exp_ci = mean_ci(scores)
    exp_sol_mean = sum(sol_scores) / len(sol_scores)
    exp_diff, exp_diff_ci = mean_ci(diffs)

    assert row["ci"] >= 0.0
    assert row["diff_ci"] >= 0.0
    assert row["ratio"] > 0.0
    assert abs(row["mean"] - exp_mean) < 1e-9
    assert abs(row["ci"] - exp_ci) < 1e-9
    assert abs(row["solver_same_seeds"] - exp_sol_mean) < 1e-9
    assert abs(row["diff"] - exp_diff) < 1e-9
    assert abs(row["diff_ci"] - exp_diff_ci) < 1e-9
    assert abs(row["ratio"] - (exp_mean / exp_sol_mean)) < 1e-9
    assert row["ratio_lo"] <= row["ratio"] <= row["ratio_hi"]
    assert row["post_expected_lo"] <= row["post_expected_ratio"] <= row["post_expected_hi"]


def test_frontier_replication_v14_readme_and_committed_g1_replay(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    vr = _load_script("verify_replay", "scripts/verify_replay.py")

    readme_path = EXT_ROOT / "README.md"
    assert readme_path.is_file()
    readme_text = readme_path.read_text(encoding="utf-8")
    for required in (
        "paired_table_fleet7.md",
        "paired_table_fleet7.json",
        "paired_table_ext8_combined.md",
        "paired_table_ext8_combined.json",
        "paired_table_pooled38.md",
        "paired_table_pooled38.json",
        "30, 34, 42, 45, 48, 57, 58",
        "30, 34, 37, 42, 45, 48, 57, 58",
        "0-29, 30, 34, 37, 42, 45, 48, 57, 58",
        "[34, 37]",
        "[30, 42, 45, 48, 57, 58]",
        "7/7 episodes replay-verified",
    ):
        assert required in readme_text

    committed_ext_path = COMMITTED_EXT_HARD / "episodes.jsonl"
    committed_eps = _read_jsonl(committed_ext_path)
    assert [ep["seed"] for ep in committed_eps] == COMMITTED_G1_SEEDS
    for ep in committed_eps:
        assert ep["tier"] == "hard"
        assert ep["agent"] == "opencode:google/gemini-4-carbon"
        assert ep["end_reason"] == "accused"
        assert (ep.get("meta") or {}).get("valid") is True
        rep = vr.replay_episode(ep)
        assert abs(rep["score"] - ep["score"]) < 1e-9
        assert rep["accused"] == ep["accused"]
        assert rep["correct"] == ep["correct"]
        assert rep["final_day"] == ep["final_day"]
    assert vr.main([str(committed_ext_path)]) == 0


def test_frontier_replication_v14_paired_tables_fleet7_ext8_pooled38():
    for fname in (
        "README.md",
        "paired_table_fleet7.json",
        "paired_table_fleet7.md",
        "paired_table_ext8_combined.json",
        "paired_table_ext8_combined.md",
        "paired_table_pooled38.json",
        "paired_table_pooled38.md",
    ):
        assert (EXT_ROOT / fname).is_file()

    fleet_eps = _read_jsonl(EXT_HARD / "episodes.jsonl")
    committed_ext_eps = _read_jsonl(COMMITTED_EXT_HARD / "episodes.jsonl")
    primary_hard_eps = _read_jsonl(COMMITTED_PRIMARY_HARD / "episodes.jsonl")
    assert [ep["seed"] for ep in primary_hard_eps] == list(range(30))

    solver_hard_eps = [
        ep for ep in load_runs(REF_ROOT) if ep["agent"] == "solver" and ep["tier"] == "hard"
    ]
    solver_by_seed = {ep["seed"]: ep for ep in solver_hard_eps}
    assert sorted(solver_by_seed) == list(range(60))

    committed_seed_set = {ep["seed"] for ep in committed_ext_eps}
    assert sorted(committed_seed_set) == COMMITTED_G1_SEEDS
    fleet_new_eps = [ep for ep in fleet_eps if ep["seed"] not in committed_seed_set]
    assert [ep["seed"] for ep in fleet_new_eps] == FLEET_NEW_SEEDS

    dedup_ext8_eps = sorted(committed_ext_eps + fleet_new_eps, key=lambda ep: ep["seed"])
    assert [ep["seed"] for ep in dedup_ext8_eps] == EXT8_SEEDS
    committed_by_seed = {ep["seed"]: ep for ep in committed_ext_eps}
    fleet_by_seed = {ep["seed"]: ep for ep in fleet_eps}
    dedup_by_seed = {ep["seed"]: ep for ep in dedup_ext8_eps}
    assert dedup_by_seed[34]["score"] == committed_by_seed[34]["score"]
    assert dedup_by_seed[34]["score"] != fleet_by_seed[34]["score"]

    pooled38_eps = primary_hard_eps + dedup_ext8_eps
    assert [ep["seed"] for ep in pooled38_eps] == POOLED38_SEEDS

    fleet7_json = json.loads((EXT_ROOT / "paired_table_fleet7.json").read_text(encoding="utf-8"))
    assert len(fleet7_json) == 2
    assert fleet7_json[0]["n"] == 7
    _assert_cohort_stats(fleet7_json[0], fleet_eps, solver_by_seed, EXPECTED_SEEDS)
    assert fleet7_json[1]["agent"] == "solver"
    assert fleet7_json[1]["n"] == 30
    assert fleet7_json[1]["seeds"] == list(range(30, 60))
    sol_30_59_mean = sum(solver_by_seed[s]["score"] for s in range(30, 60)) / 30
    assert abs(fleet7_json[1]["mean"] - sol_30_59_mean) < 1e-9
    _assert_md_matches_json(EXT_ROOT / "paired_table_fleet7.md", fleet7_json)

    ext8_json = json.loads((EXT_ROOT / "paired_table_ext8_combined.json").read_text(encoding="utf-8"))
    assert len(ext8_json) == 2
    assert ext8_json[0]["n"] == 8
    _assert_cohort_stats(ext8_json[0], dedup_ext8_eps, solver_by_seed, EXT8_SEEDS)
    assert ext8_json[1]["agent"] == "solver"
    assert ext8_json[1]["n"] == 30
    assert ext8_json[1]["seeds"] == list(range(30, 60))
    assert abs(ext8_json[1]["mean"] - sol_30_59_mean) < 1e-9
    _assert_md_matches_json(EXT_ROOT / "paired_table_ext8_combined.md", ext8_json)

    pooled38_json = json.loads((EXT_ROOT / "paired_table_pooled38.json").read_text(encoding="utf-8"))
    assert len(pooled38_json) == 17
    hard_by_group = {
        (r["group"], r["label"]): r for r in pooled38_json if r["tier"] == "hard"
    }
    primary_row = hard_by_group[
        ("v1.4/opencode-gemini-4-carbon", "OpenCode + gemini-4-carbon over MCP (judges' shape)")
    ]
    ext8_row = hard_by_group[
        (
            "v1.4/opencode-gemini-4-carbon-ext",
            "OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59)",
        )
    ]
    pooled_row = hard_by_group[
        (
            "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
            "OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)",
        )
    ]
    solver60_row = hard_by_group[("v1.4/reference", "reference solver")]

    assert primary_row["n"] == 30
    assert ext8_row["n"] == 8
    assert pooled_row["n"] == 38
    _assert_cohort_stats(primary_row, primary_hard_eps, solver_by_seed, list(range(30)))
    _assert_cohort_stats(ext8_row, dedup_ext8_eps, solver_by_seed, EXT8_SEEDS)
    _assert_cohort_stats(pooled_row, pooled38_eps, solver_by_seed, POOLED38_SEEDS)
    assert solver60_row["agent"] == "solver"
    assert solver60_row["n"] == 60
    assert solver60_row["seeds"] == list(range(60))
    sol_0_59_mean = sum(solver_by_seed[s]["score"] for s in range(60)) / 60
    assert abs(solver60_row["mean"] - sol_0_59_mean) < 1e-9
    _assert_md_matches_json(EXT_ROOT / "paired_table_pooled38.md", pooled38_json)
